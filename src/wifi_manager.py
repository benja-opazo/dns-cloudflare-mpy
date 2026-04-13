import network
import time

AP_SSID = 'ESP32-DNSConfig'
AP_PASSWORD = 'configure'
CONNECT_TIMEOUT = 20  # seconds


class WiFiManager:
    def __init__(self):
        self.sta = network.WLAN(network.WLAN.IF_STA)
        self.ap = network.WLAN(network.WLAN.IF_AP)
        self._mode = None

    def start_ap_mode(self):
        print('Starting AP mode...')
        self.sta.active(False)
        self.ap.active(True)
        self.ap.config(essid=AP_SSID, password=AP_PASSWORD)
        time.sleep(1)
        ip = self.ap.ifconfig()[0]
        self._mode = 'ap'
        print(f'AP active — SSID: {AP_SSID}  IP: {ip}')
        return ip

    def connect_sta(self, ssid, password):
        print(f'Connecting to "{ssid}"...')
        self.ap.active(False)
        self.sta.active(True)
        if self.sta.isconnected():
            self.sta.disconnect()
            time.sleep(1)
        self.sta.connect(ssid, password)
        for _ in range(CONNECT_TIMEOUT):
            if self.sta.isconnected():
                ip = self.sta.ifconfig()[0]
                self._mode = 'client'
                print(f'Connected — IP: {ip}')
                return ip
            time.sleep(1)
        print('Connection failed')
        return None

    def is_connected(self):
        return self.sta.isconnected()

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
            print('Scan error:', e)
            return []
        finally:
            if not was_active:
                self.sta.active(False)
