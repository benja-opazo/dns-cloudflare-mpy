import network
import time
from log import log

AP_SSID = 'ESP32-DNSConfig'
AP_PASSWORD = 'configure'
CONNECT_TIMEOUT = 20  # seconds


class WiFiManager:
    def __init__(self):
        self.sta = network.WLAN(network.STA_IF)
        self.ap = network.WLAN(network.AP_IF)
        self._mode = None

    def start_ap_mode(self):
        log('Starting AP mode...')
        self.sta.active(False)
        self.ap.active(True)
        self.ap.config(essid=AP_SSID, password=AP_PASSWORD)
        time.sleep(1)
        cfg = self.ap.ifconfig()
        self._mode = 'ap'
        log(f'AP active — SSID: {AP_SSID}  IP: {cfg[0]}  subnet: {cfg[1]}  gw: {cfg[2]}')
        return cfg[0]

    def connect_sta(self, ssid, password, hostname=None):
        log(f'Connecting to "{ssid}"...')
        self.ap.active(False)
        self.sta.active(True)
        # Disable WiFi power-save — the radio sleeps between beacons and drops
        # incoming packets, causing UDP/NTP timeouts and intermittent DNS/HTTPS.
        try:
            self.sta.config(pm=network.WLAN.PM_NONE)
            log('  WiFi power-save disabled (PM_NONE)')
        except Exception as e:
            try:
                self.sta.config(pm=0)
                log('  WiFi power-save disabled (pm=0)')
            except Exception as e2:
                log(f'  Could not disable WiFi PM: {e2}')
        if hostname:
            try:
                self.sta.config(dhcp_hostname=hostname)
                log(f'  Hostname: {hostname}')
            except Exception as e:
                log(f'  Hostname set failed: {e}')
        if self.sta.isconnected():
            log('STA already connected — disconnecting first')
            self.sta.disconnect()
            time.sleep(1)
        self.sta.connect(ssid, password)
        for i in range(CONNECT_TIMEOUT):
            status = self.sta.status()
            log(f'  [{i+1}/{CONNECT_TIMEOUT}] status={status}')
            if self.sta.isconnected():
                cfg = self.sta.ifconfig()
                self._mode = 'client'
                log(f'Connected — IP: {cfg[0]}  subnet: {cfg[1]}  gw: {cfg[2]}  dns: {cfg[3]}')
                return cfg[0]
            time.sleep(1)
        log(f'Connection failed after {CONNECT_TIMEOUT}s — final status={self.sta.status()}')
        return None

    def is_connected(self):
        return self.sta.isconnected()

    def get_gateway(self):
        if self._mode == 'client' and self.sta.isconnected():
            return self.sta.ifconfig()[2]
        return None

    def get_ip(self):
        if self._mode == 'client' and self.sta.isconnected():
            return self.sta.ifconfig()[0]
        if self._mode == 'ap':
            return self.ap.ifconfig()[0]
        return '0.0.0.0'

    def get_mode(self):
        return self._mode or 'none'

    def get_ssid(self):
        if self._mode == 'client' and self.sta.isconnected():
            return self.sta.config('essid')
        return ''

    def scan(self):
        """Scan for nearby networks.
        Returns a list of SSIDs sorted by signal strength (strongest first).
        Works in both AP and client mode.
        """
        was_active = self.sta.active()
        if not was_active:
            self.sta.active(True)
            time.sleep(1)  # Let the interface settle before scanning
        try:
            results = self.sta.scan()
            # Each result: (ssid_bytes, bssid, channel, rssi, authmode, hidden)
            seen = set()
            networks = []
            for net in results:
                raw = net[0]
                ssid = raw.decode('utf-8', 'ignore') if isinstance(raw, bytes) else str(raw)
                rssi = net[3]
                if ssid and ssid not in seen:
                    seen.add(ssid)
                    networks.append((ssid, rssi))
            networks.sort(key=lambda x: -x[1])  # RSSI is negative; less negative = stronger
            return networks
        except Exception as e:
            log('Scan error:', e)
            return []
        finally:
            if not was_active:
                self.sta.active(False)
