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
    def __init__(self, wifi_manager, config_manager):
        self.wifi = wifi_manager
        self.config = config_manager
        self._sock = None       # port 80  – HTTP
        self._sock_tls = None   # port 443 – plaintext redirect to HTTP

    def _make_socket(self, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', port))
        s.listen(5)
        return s

    def start(self):
        for attr in ('_sock', '_sock_tls'):
            old = getattr(self, attr)
            if old:
                try:
                    old.close()
                except Exception:
                    pass
        self._sock     = self._make_socket(80)
        self._sock_tls = self._make_socket(443)
        print(
            'Listening — HTTP :80  HTTPS-redirect :443'
            '  (' + self.wifi.get_mode() + '  ' + self.wifi.get_ip() + ')'
        )

    def run_forever(self):
        assert self._sock is not None, 'call start() before run_forever()'
        poller = select.poll()
        poller.register(self._sock,     select.POLLIN)
        poller.register(self._sock_tls, select.POLLIN)

        while True:
            try:
                for fd, _ in poller.poll():
                    conn, addr = fd.accept()
                    if fd is self._sock_tls:
                        print('HTTPS->HTTP redirect for', addr)
                        try:
                            self._https_redirect(conn)
                        except Exception:
                            pass
                        finally:
                            conn.close()
                    else:
                        print('HTTP from', addr)
                        reboot = False
                        try:
                            reboot = self._handle(conn)
                        except Exception as e:
                            print('Handler error [' + type(e).__name__ + ']:', e)
                        finally:
                            conn.close()
                        if reboot:
                            time.sleep(2)
                            machine.reset()
            except Exception as e:
                print('Poll error:', e)

    # ------------------------------------------------------------------ #
    #  Request / response helpers                                          #
    # ------------------------------------------------------------------ #

    def _https_redirect(self, conn):
        """Send a plaintext 301 redirect from HTTPS to HTTP.
        No TLS handshake — works for clients that aren't strict about TLS on LAN."""
        ip = self.wifi.get_ip()
        conn.send((
            'HTTP/1.1 301 Moved Permanently\r\n'
            'Location: http://' + ip + '/\r\n'
            'Connection: close\r\n'
            'Content-Length: 0\r\n'
            '\r\n'
        ).encode())

    def _recv_request(self, conn):
        conn.settimeout(10)
        raw = b''
        try:
            while len(raw) < MAX_HEADER_SIZE:
                chunk = conn.recv(256)
                if not chunk:
                    break
                raw += chunk
                if b'\r\n\r\n' in raw:
                    break
        except Exception:
            pass

        sep = raw.find(b'\r\n\r\n')
        if sep == -1:
            return 'GET', '/', ''

        headers_raw = raw[:sep].decode('utf-8', 'ignore')
        body_bytes = raw[sep + 4:]

        lines = headers_raw.split('\r\n')
        parts = lines[0].split(' ')
        method = parts[0] if len(parts) > 0 else 'GET'
        path = parts[1].split('?')[0] if len(parts) > 1 else '/'

        headers = {}
        for line in lines[1:]:
            if ': ' in line:
                k, v = line.split(': ', 1)
                headers[k.lower()] = v

        content_length = int(headers.get('content-length', 0))
        try:
            while len(body_bytes) < content_length:
                chunk = conn.recv(256)
                if not chunk:
                    break
                body_bytes += chunk
        except Exception:
            pass

        return method, path, body_bytes[:content_length].decode('utf-8', 'ignore')

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
        conn.send(header + body)

    def _redirect(self, conn, location='/'):
        conn.send((
            f'HTTP/1.1 302 Found\r\n'
            f'Location: {location}\r\n'
            f'Connection: close\r\n'
            f'\r\n'
        ).encode())

    def _serve_static(self, conn, path, content_type):
        """Serve a file in chunks (memory-efficient for large CSS)."""
        try:
            import os
            size = os.stat(path)[6]
            conn.send((
                f'HTTP/1.1 200 OK\r\n'
                f'Content-Type: {content_type}\r\n'
                f'Content-Length: {size}\r\n'
                f'Connection: close\r\n'
                f'\r\n'
            ).encode())
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    conn.send(chunk)
        except Exception as err:
            self._send_response(conn, '404 Not Found', 'text/plain', f'Not found: {path} ({err})')

    def _serve_template(self, conn, path, content_type, variables):
        """Read the full template, substitute variables, and send."""
        try:
            with open(path, 'r') as f:
                content = f.read()
            for key, value in variables.items():
                content = content.replace('{{' + key + '}}', value)
            self._send_response(conn, '200 OK', content_type, content)
        except Exception as err:
            self._send_response(conn, '500 Internal Server Error', 'text/plain', str(err))

    def _template_vars(self):
        mode = self.wifi.get_mode()
        return {
            'CURRENT_STATUS':       'Client Mode' if mode == 'client' else 'AP Mode',
            'CURRENT_IP':           self.wifi.get_ip(),
            'CURRENT_SSID':         self.wifi.get_ssid(),
            'SAVED_SSID':           self.config.get_wifi_ssid() or '(not set)',
            'SAVED_CF_TOKEN_MASKED': _mask_secret(self.config.get_cf_api_key()),
            'SAVED_CF_ZONE_ID':     self.config.get_cf_zone_id() or '(not set)',
            'SAVED_CF_RECORD':      self.config.get_cf_record_name() or '(not set)',
        }

    # ------------------------------------------------------------------ #
    #  Route handler                                                       #
    # ------------------------------------------------------------------ #

    def _handle(self, conn):
        """Dispatch the request and return True if a reboot is required."""
        method, path, body = self._recv_request(conn)
        print(f'{method} {path}')

        # Wi-Fi network scan (called by the refresh button via fetch)
        if path == '/scan-wifi':
            networks = self.wifi.scan()
            ssids = json.dumps([n[0] for n in networks])
            self._send_response(conn, '200 OK', 'application/json', ssids)
            return False

        # Static assets
        if path == '/tailwind.css':
            self._serve_static(conn, f'{DATA_DIR}/tailwind.css', 'application/javascript')
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
                self._send_response(conn, '200 OK', 'text/html', _reboot_page(ssid))
                return True  # triggers machine.reset() after conn.close()
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
            self._redirect(conn)
            return False

        self._send_response(conn, '404 Not Found', 'text/plain', 'Not Found')
        return False


def _reboot_page(ssid):
    # Avoid mixing f-strings and regular strings in implicit concatenation —
    # older MicroPython builds cannot parse that combination.
    return (
        '<!DOCTYPE html><html><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>Wi-Fi Saved</title>'
        '<style>'
        'body{font-family:sans-serif;display:flex;align-items:center;'
        'justify-content:center;min-height:100vh;background:#f3f4f6;margin:0}'
        '.card{background:#fff;border-radius:12px;padding:2rem;'
        'box-shadow:0 4px 24px rgba(0,0,0,.06);text-align:center;max-width:400px}'
        'h1{color:#4f46e5}p{color:#374151}'
        '</style></head><body>'
        '<div class="card">'
        '<h1>Wi-Fi Saved</h1>'
        '<p>Connecting to <strong>' + ssid + '</strong>...</p>'
        '<p>Device will reboot now. '
        'Check your router for the new IP and navigate to it.</p>'
        '</div></body></html>'
    )
