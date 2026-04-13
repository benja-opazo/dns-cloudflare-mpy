import json
import select
import socket
import machine
import time

DATA_DIR = 'data'
MAX_HEADER_SIZE = 4096
CHUNK_SIZE = 1024


def _url_decode(s):
    """Decode a URL-encoded string (handles %XX and + → space)."""
    s = s.replace('+', ' ')
    result = bytearray()
    i = 0
    while i < len(s):
        if s[i] == '%' and i + 2 < len(s):
            try:
                result.append(int(s[i + 1:i + 3], 16))
                i += 3
            except ValueError:
                result.append(ord(s[i]))
                i += 1
        else:
            result.append(ord(s[i]))
            i += 1
    return result.decode('utf-8', 'ignore')


def _parse_form(body):
    """Parse application/x-www-form-urlencoded body into a dict."""
    params = {}
    for pair in body.split('&'):
        if '=' in pair:
            k, v = pair.split('=', 1)
            params[_url_decode(k)] = _url_decode(v)
    return params


def _mask_secret(s):
    """Mask a secret string, showing only the first and last 4 chars."""
    if not s:
        return '(not set)'
    if len(s) <= 8:
        return '*' * len(s)
    return s[:4] + '*' * (len(s) - 8) + s[-4:]


class Server:
    def __init__(self, wifi_manager, config_manager, dns_updater=None, led=None):
        self.wifi = wifi_manager
        self.config = config_manager
        self.dns_updater = dns_updater
        self._led = led
        self._sock = None       # port 80  – HTTP

    def _make_socket(self, port):
        print(f'  Binding port {port}...')
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('0.0.0.0', port))
            s.listen(5)
            print(f'  Port {port} ready')
            return s
        except Exception as e:
            print(f'  Port {port} bind failed [{type(e).__name__}]: {e}')
            raise

    def start(self):
        print('Server.start() — closing any existing sockets')
        if self._sock:
            try:
                self._sock.close()
                print('  Closed old _sock')
            except Exception as e:
                print(f'  Could not close _sock: {e}')
        print('Creating sockets...')
        self._sock = self._make_socket(80)
        print('Listening — HTTP :80  (' + self.wifi.get_mode() + '  ' + self.wifi.get_ip() + ')')

    def _restart_sockets(self, poller):
        """Close and recreate the listening socket, updating the poller."""
        if self._sock:
            try:
                poller.unregister(self._sock)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = self._make_socket(80)
        poller.register(self._sock, select.POLLIN)
        print('Socket restarted')

    def run_forever(self):
        assert self._sock is not None, 'call start() before run_forever()'
        poller = select.poll()
        poller.register(self._sock, select.POLLIN)
        print('run_forever() — entering poll loop')

        while True:
            try:
                if self._led:
                    self._led.tick()
                if self.dns_updater:
                    self.dns_updater.tick()
                events = poller.poll(20)  # 20 ms — keeps LED tick responsive
                for fd, event in events:
                    conn, addr = fd.accept()
                    print('HTTP from', addr)
                    reboot = False
                    try:
                        reboot = self._handle(conn)
                    except OSError as e:
                        if e.args[0] != 113:  # suppress ECONNABORTED (client hung up)
                            print('Handler error [' + type(e).__name__ + ']:', e)
                    except Exception as e:
                        print('Handler error [' + type(e).__name__ + ']:', e)
                    finally:
                        conn.close()
                    if reboot:
                        time.sleep(2)
                        machine.reset()
            except OSError as e:
                if e.args[0] == 128:  # ENOTCONN — wifi dropped, sockets are invalid
                    print('Network lost — attempting reconnect...')
                    time.sleep(5)
                    if self.wifi.get_mode() == 'client':
                        ip = self.wifi.connect_sta(
                            self.config.get_wifi_ssid(),
                            self.config.get_wifi_password())
                        if not ip:
                            print('Reconnect failed — falling back to AP mode')
                            self.wifi.start_ap_mode()
                    self._restart_sockets(poller)
                else:
                    print('Poll error [' + type(e).__name__ + ']:', e)
                    time.sleep(1)
            except Exception as e:
                print('Poll error [' + type(e).__name__ + ']:', e)
                time.sleep(1)

    # ------------------------------------------------------------------ #
    #  Request / response helpers                                          #
    # ------------------------------------------------------------------ #

    def _recv_request(self, conn):
        t0 = time.ticks_ms()
        conn.settimeout(10)
        # bytearray extends in-place — avoids a new bytes allocation on every recv.
        raw = bytearray()
        try:
            while len(raw) < MAX_HEADER_SIZE:
                chunk = conn.recv(256)
                if not chunk:
                    break
                raw += chunk
                if b'\r\n\r\n' in raw:
                    break
        except Exception as e:
            print('  recv error:', type(e).__name__, e)

        sep = raw.find(b'\r\n\r\n')
        if sep == -1:
            print('  recv: no header terminator ({} bytes, {} ms)'.format(
                len(raw), time.ticks_diff(time.ticks_ms(), t0)))
            return 'GET', '/', ''

        # Parse request line (first line only — no full headers dict needed).
        line_end = raw.find(b'\r\n')
        parts = bytes(raw[:line_end]).decode('utf-8', 'ignore').split(' ', 2)
        method = parts[0] if len(parts) >= 1 else 'GET'
        path   = parts[1].split('?')[0] if len(parts) >= 2 else '/'

        # Scan for Content-Length without allocating a headers dict.
        content_length = 0
        header_lower = bytes(raw[:sep]).lower()
        cl_idx = header_lower.find(b'content-length:')
        if cl_idx != -1:
            cl_end = header_lower.find(b'\r\n', cl_idx)
            try:
                content_length = int(header_lower[cl_idx + 15:cl_end].strip())
            except Exception:
                pass

        body = bytearray(raw[sep + 4:])
        try:
            while len(body) < content_length:
                chunk = conn.recv(256)
                if not chunk:
                    break
                body += chunk
        except Exception:
            pass

        print('  recv: {} {} ({} ms)'.format(
            method, path, time.ticks_diff(time.ticks_ms(), t0)))
        return method, path, bytes(body[:content_length]).decode('utf-8', 'ignore')

    def _send_response(self, conn, status, content_type, body):
        if isinstance(body, str):
            body = body.encode()
        header = (
            f'HTTP/1.1 {status}\r\n'
            f'Content-Type: {content_type}\r\n'
            f'Content-Length: {len(body)}\r\n'
            f'Connection: close\r\n'
            f'\r\n'
        ).encode()
        t0 = time.ticks_ms()
        # Send header and body separately — avoids allocating a third copy of
        # the body in RAM.  Body is streamed in CHUNK_SIZE slices via memoryview
        # so each sendall() call works on a small window without copying.
        conn.sendall(header)
        mv = memoryview(body)
        sent = 0
        while sent < len(body):
            conn.sendall(mv[sent:sent + CHUNK_SIZE])
            sent += CHUNK_SIZE
        print(f'  send_response: {status}  {content_type}  {len(body)} bytes  {time.ticks_diff(time.ticks_ms(), t0)} ms')

    def _redirect(self, conn, location='/'):
        conn.sendall((
            f'HTTP/1.1 302 Found\r\n'
            f'Location: {location}\r\n'
            f'Connection: close\r\n'
            f'\r\n'
        ).encode())
        print(f'  redirect -> {location}')

    def _serve_static(self, conn, path, content_type):
        """Serve a file in chunks (memory-efficient for large files)."""
        try:
            import os
            size = os.stat(path)[6]
            print(f'  serve_static: {path}  {size} bytes')
            conn.sendall((
                f'HTTP/1.1 200 OK\r\n'
                f'Content-Type: {content_type}\r\n'
                f'Content-Length: {size}\r\n'
                f'Connection: close\r\n'
                f'\r\n'
            ).encode())
            t0 = time.ticks_ms()
            sent = 0
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    conn.sendall(chunk)
                    sent += len(chunk)
            print(f'  serve_static: sent {sent}/{size} bytes  {time.ticks_diff(time.ticks_ms(), t0)} ms')
        except Exception as err:
            print(f'  serve_static error: {err}')
            self._send_response(conn, '404 Not Found', 'text/plain', f'Not found: {path} ({err})')

    def _serve_template(self, conn, path, content_type, variables):
        """Read template, substitute variables, send with Content-Length."""
        try:
            t0 = time.ticks_ms()
            with open(path, 'r') as f:
                content = f.read()
            for key, value in variables.items():
                content = content.replace('{{' + key + '}}', value)
            print('  serve_template: {} bytes in {} ms'.format(
                len(content), time.ticks_diff(time.ticks_ms(), t0)))
            self._send_response(conn, '200 OK', content_type, content)
        except Exception as err:
            print('  serve_template error:', err)
            try:
                self._send_response(conn, '500 Internal Server Error', 'text/plain', str(err))
            except Exception:
                pass

    def _template_vars(self):
        mode = self.wifi.get_mode()
        return {
            'CURRENT_STATUS':        'Client Mode' if mode == 'client' else 'AP Mode',
            'CURRENT_IP':            self.wifi.get_ip(),
            'CURRENT_SSID':          self.wifi.get_ssid(),
            'SAVED_SSID':            self.config.get_wifi_ssid() or '(not set)',
            'SAVED_HOSTNAME':        self.config.get_hostname(),
            'SAVED_CF_TOKEN_MASKED': _mask_secret(self.config.get_cf_api_key()),
            'SAVED_CF_ZONE_ID':      self.config.get_cf_zone_id() or '(not set)',
            'SAVED_CF_RECORD':       self.config.get_cf_record_name() or '(not set)',
        }

    # ------------------------------------------------------------------ #
    #  Route handler                                                       #
    # ------------------------------------------------------------------ #

    def _handle(self, conn):
        """Dispatch the request and return True if a reboot is required."""
        t_handle = time.ticks_ms()
        method, path, body = self._recv_request(conn)
        print(f'{method} {path}  (recv took {time.ticks_diff(time.ticks_ms(), t_handle)} ms)')

        # Public IP — cached value
        if path == '/public-ip':
            ip = self.dns_updater.current_ip() if self.dns_updater else None
            self._send_response(conn, '200 OK', 'application/json',
                                json.dumps({'ip': ip or 'unknown'}))
            return False

        # Force an immediate IP check (used by the Status tab Refresh button)
        if method == 'POST' and path == '/refresh-ip':
            ip = self.dns_updater.force_check() if self.dns_updater else None
            self._send_response(conn, '200 OK', 'application/json',
                                json.dumps({'ip': ip or 'unknown'}))
            return False

        # Cloudflare zone status (API key validity, zone IP, last update time)
        if path == '/cf-status':
            data = self.dns_updater.status() if self.dns_updater else {
                'zone_ip': 'unknown', 'cf_status': 'unknown', 'last_dns_update': 'never'
            }
            self._send_response(conn, '200 OK', 'application/json', json.dumps(data))
            return False

        # Wi-Fi network scan (called by the refresh button via fetch)
        if path == '/scan-wifi':
            networks = self.wifi.scan()
            ssids = json.dumps([n[0] for n in networks])
            self._send_response(conn, '200 OK', 'application/json', ssids)
            return False

        # Static assets
        if path == '/logo.png':
            self._serve_static(conn, f'{DATA_DIR}/logo.png', 'image/png')
            return False

        if path == '/tailwind.css':
            self._serve_static(conn, f'{DATA_DIR}/tailwind.css', 'text/css')
            return False

        if path == '/app.js':
            self._serve_static(conn, f'{DATA_DIR}/app.js', 'application/javascript')
            return False

        # Main configuration page
        if path in ('/', '/index.html'):
            self._serve_template(conn, f'{DATA_DIR}/index.html', 'text/html', self._template_vars())
            return False

        # Save Wi-Fi credentials → reboot
        if method == 'POST' and path == '/save-wifi':
            params = _parse_form(body)
            ssid = params.get('ssid', '').strip()
            password = params.get('password', '').strip()
            if ssid:
                self.config.set_wifi(ssid, password)
                self._send_response(conn, '200 OK', 'text/html',
                                    _reboot_page('Connecting to <strong>' + ssid + '</strong>...'))
                return True  # triggers machine.reset() after conn.close()
            self._redirect(conn)
            return False

        # Save hostname → no reboot needed (takes effect on next connection)
        if method == 'POST' and path == '/save-hostname':
            params = _parse_form(body)
            hostname = params.get('hostname', '').strip()
            if hostname:
                self.config.set_hostname(hostname)
            self._redirect(conn)
            return False

        # Save Cloudflare config → no reboot needed
        if method == 'POST' and path == '/save-cloudflare':
            params = _parse_form(body)
            api_key = params.get('cf_token', '').strip()
            zone_id = params.get('cf_zone_id', '').strip()
            record_name = params.get('cf_record_name', '').strip()
            # Keep existing value for any field left blank
            if not api_key:
                api_key = self.config.get_cf_api_key()
            if not zone_id:
                zone_id = self.config.get_cf_zone_id()
            if not record_name:
                record_name = self.config.get_cf_record_name()
            self.config.set_cloudflare(api_key, zone_id, record_name)
            self._send_response(conn, '200 OK', 'text/html', _reboot_page('Cloudflare config saved'))
            return True

        print(f'404 {method} {path}')
        self._send_response(conn, '404 Not Found', 'text/plain', 'Not Found')
        return False


def _reboot_page(message):
    # Avoid mixing f-strings and regular strings in implicit concatenation —
    # older MicroPython builds cannot parse that combination.
    return (
        '<!DOCTYPE html><html><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>Saved</title>'
        '<style>'
        'body{font-family:sans-serif;display:flex;align-items:center;'
        'justify-content:center;min-height:100vh;background:#f3f4f6;margin:0}'
        '.card{background:#fff;border-radius:12px;padding:2rem;'
        'box-shadow:0 4px 24px rgba(0,0,0,.06);text-align:center;max-width:400px}'
        'h1{color:#4f46e5}p{color:#374151}'
        '</style></head><body>'
        '<div class="card">'
        '<h1>Saved</h1>'
        '<p>' + message + '</p>'
        '<p>Device will reboot now.</p>'
        '</div></body></html>'
    )
