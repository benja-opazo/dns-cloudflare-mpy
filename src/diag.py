import time
import socket
import network


def _connect_wifi():
    from config import ConfigManager
    cfg = ConfigManager()
    ssid = cfg.get_wifi_ssid()
    password = cfg.get_wifi_password()
    if not ssid:
        print('[diag] No WiFi credentials in config')
        return None, None

    ap = network.WLAN(network.AP_IF)
    if ap.active():
        print('[diag] AP interface was active — disabling it')
        ap.active(False)
        time.sleep(1)

    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    try:
        sta.config(pm=network.WLAN.PM_NONE)
        print('[diag] WiFi power-save disabled (PM_NONE)')
    except Exception:
        try:
            sta.config(pm=0)
            print('[diag] WiFi power-save disabled (pm=0)')
        except Exception as e:
            print(f'[diag] Could not disable WiFi PM: {e}')

    if sta.isconnected():
        print('[diag] Already connected — disconnecting for a clean reconnect')
        sta.disconnect()
        time.sleep(2)

    print(f'[diag] Connecting to "{ssid}"...')
    sta.connect(ssid, password)
    for i in range(20):
        if sta.isconnected():
            break
        time.sleep(1)

    if not sta.isconnected():
        print('[diag] WiFi connection failed')
        return None, None

    time.sleep(2)

    ip, subnet, gw, dns = sta.ifconfig()
    print(f'[diag] ifconfig after DHCP: IP:{ip}  subnet:{subnet}  GW:{gw}  DNS:{dns}')

    sta.ifconfig((ip, subnet, gw, gw))
    ip2, subnet2, gw2, dns2 = sta.ifconfig()
    print(f'[diag] ifconfig after re-apply:  IP:{ip2}  subnet:{subnet2}  GW:{gw2}  DNS:{dns2}')

    return sta, gw


def _test(label, fn):
    print(f'  {label}')
    try:
        t = time.ticks_ms()
        result = fn()
        ms = time.ticks_diff(time.ticks_ms(), t)
        print(f'    OK  {ms} ms  {result}')
        return True
    except Exception as e:
        print(f'    FAIL  {e}')
        return False


def _ntp_udp_verbose(ip):
    """Send NTP request and report what comes back, including the source address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(5)
    try:
        s.sendto(b'\x1b' + b'\x00' * 47, (ip, 123))
        data, addr = s.recvfrom(48)
        return f'got {len(data)} bytes from {addr}'
    finally:
        s.close()


def _urequests_get(url):
    import urequests
    r = urequests.get(url)
    try:
        return r.text.strip()[:60]
    finally:
        r.close()


def _free():
    """Free heap after a full collection."""
    import gc
    gc.collect()
    return gc.mem_free()


def _largest_block():
    """Largest single allocation the heap can currently satisfy (contiguous).
    A TLS handshake needs a big contiguous block, so this matters more than total free."""
    import gc
    gc.collect()
    lo, hi, best = 0, gc.mem_free(), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            b = bytearray(mid)
            del b
            best = mid
            lo = mid + 1
        except MemoryError:
            hi = mid - 1
    gc.collect()
    return best


def _idf_heap():
    """ESP-IDF internal heap — this is where mbedtls (TLS) allocates, NOT the
    MicroPython GC heap. largest_block here is what a TLS handshake needs."""
    try:
        import esp32
        cap = getattr(esp32, 'HEAP_DATA', None)
        if cap is None:
            return 'idf_heap: HEAP_DATA constant not available'
        regions = esp32.idf_heap_info(cap)
        total_free = sum(r[1] for r in regions)
        largest = max((r[2] for r in regions), default=0)
        return 'idf_data free={} largest_block={}'.format(total_free, largest)
    except Exception as e:
        return 'idf_heap_info unavailable: {}'.format(e)


def _mem_report(label):
    print(f'  [mem] {label}:')
    print(f'    mpy_heap  free={_free()}  largest_block={_largest_block()}')
    print(f'    {_idf_heap()}')


def run():
    print('=== DIAGNOSTIC START ===')

    sta, gw = _connect_wifi()
    if sta is None:
        print('=== DIAGNOSTIC ABORTED ===')
        return

    print()
    print('--- DNS ---')
    dns_works = _test('getaddrinfo("google.com")',
                      lambda: socket.getaddrinfo('google.com', 80)[0][-1][0])
    _test('getaddrinfo("api.ipify.org")',
          lambda: socket.getaddrinfo('api.ipify.org', 80)[0][-1][0])

    print()
    print('--- urequests HTTP (confirms routing is live) ---')
    http_works = _test('urequests http://api.ipify.org',
                       lambda: _urequests_get('http://api.ipify.org'))

    print()
    print('--- urequests timeout= kwarg (production DNS code depends on this) ---')
    # The dns_updater passes timeout= to every urequests call. If the on-device
    # urequests does not accept it, all Cloudflare updates fail silently with a
    # swallowed TypeError. This test surfaces that: a FAIL here means the code
    # will not update DNS on this firmware even though plain HTTP works.
    def _timeout_kwarg_check():
        import urequests
        try:
            r = urequests.get('http://api.ipify.org', timeout=10)
        except TypeError as e:
            raise Exception('timeout= NOT supported by on-device urequests: ' + str(e))
        try:
            return 'timeout= accepted -> ' + r.text.strip()[:40]
        finally:
            r.close()
    _test('urequests.get(url, timeout=10)', _timeout_kwarg_check)

    print()
    print('--- NTP UDP port 123 (run after HTTP to ensure routing is warmed up) ---')
    _test(f'NTP UDP -> router {gw}  (verbose)',
          lambda: _ntp_udp_verbose(gw))
    _test('NTP UDP -> 162.159.200.1  Cloudflare  (verbose)',
          lambda: _ntp_udp_verbose('162.159.200.1'))
    _test('NTP UDP -> 216.239.35.0   Google      (verbose)',
          lambda: _ntp_udp_verbose('216.239.35.0'))

    print()
    print('--- ntptime.settime() (run after HTTP) ---')
    def _ntptime(host):
        import ntptime
        ntptime.host = host
        ntptime.timeout = 5
        ntptime.settime()
        t = time.localtime()
        return '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
            t[0], t[1], t[2], t[3], t[4], t[5])

    # These mirror the production host list in timesync.sync_time (gateway,
    # Cloudflare IP, then pool.ntp.org); 216.239.35.0 is an extra Google probe.
    _test(f'ntptime -> {gw}  (gateway)',
          lambda: _ntptime(gw))
    _test('ntptime -> 162.159.200.1  (Cloudflare)',
          lambda: _ntptime('162.159.200.1'))
    _test('ntptime -> pool.ntp.org  (DNS fallback)',
          lambda: _ntptime('pool.ntp.org'))
    _test('ntptime -> 216.239.35.0   (Google)',
          lambda: _ntptime('216.239.35.0'))

    print()
    print('--- HTTPS (SSL/TLS) ---')
    _mem_report('before any HTTPS')
    _test('getaddrinfo("api.cloudflare.com")',
          lambda: socket.getaddrinfo('api.cloudflare.com', 443)[0][-1][0])
    _mem_report('before generic TLS (ipify)')
    _test('urequests https://api.ipify.org (tests SSL works at all)',
          lambda: _urequests_get('https://api.ipify.org'))
    _mem_report('before CF TLS')
    _test('urequests https://api.cloudflare.com/client/v4/user/tokens/verify (tests CF reachability)',
          lambda: _urequests_get('https://api.cloudflare.com/client/v4/user/tokens/verify'))
    _mem_report('after CF TLS')

    if http_works:
        print()
        print('--- HTTP Date header time (fallback for blocked NTP) ---')
        def _time_from_date_header():
            import urequests
            r = urequests.get('http://api.ipify.org')
            try:
                date = r.headers.get('Date', '')
            finally:
                r.close()
            if not date:
                raise Exception('no Date header')
            # "Mon, 12 May 2026 14:30:00 GMT"
            months = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
                      'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
            p = date.split()
            day, mon, year = int(p[1]), months[p[2]], int(p[3])
            h, m, sec = (int(x) for x in p[4].split(':'))
            return f'{year}-{mon:02d}-{day:02d} {h:02d}:{m:02d}:{sec:02d}'

        _test('time from HTTP Date header (api.ipify.org)',
              _time_from_date_header)

    print()
    print('=== DIAGNOSTIC END ===')


run()
