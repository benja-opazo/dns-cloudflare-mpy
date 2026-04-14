import json

CONFIG_PATH = '/config.json'


class ConfigManager:
    def __init__(self):
        self._cfg = {}
        self._load()

    def _load(self):
        try:
            with open(CONFIG_PATH, 'r') as f:
                self._cfg = json.load(f)
        except Exception:
            self._cfg = {
                'wifi': {'ssid': '', 'password': '', 'hostname': 'esp32-dns'},
                'cloudflare': {'api_key': '', 'zone_id': '', 'record_name': ''}
            }

    def save(self):
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(self._cfg, f)
            return True
        except Exception as e:
            print('Config save error:', e)
            return False

    def set_wifi(self, ssid, password):
        wifi = self._cfg.setdefault('wifi', {})
        wifi['ssid'] = ssid
        wifi['password'] = password
        return self.save()

    def set_cloudflare(self, api_key, zone_id, record_name):
        self._cfg['cloudflare'] = {
            'api_key': api_key,
            'zone_id': zone_id,
            'record_name': record_name
        }
        return self.save()

    def get_wifi_ssid(self):
        return self._cfg.get('wifi', {}).get('ssid', '')

    def get_wifi_password(self):
        return self._cfg.get('wifi', {}).get('password', '')

    def get_hostname(self):
        return self._cfg.get('wifi', {}).get('hostname', 'esp32-dns')

    def set_hostname(self, hostname):
        self._cfg.setdefault('wifi', {})['hostname'] = hostname
        return self.save()

    def get_led_pin(self):
        return self._cfg.get('led_pin', None)

    def get_cf_api_key(self):
        return self._cfg.get('cloudflare', {}).get('api_key', '')

    def get_cf_zone_id(self):
        return self._cfg.get('cloudflare', {}).get('zone_id', '')

    def get_cf_record_name(self):
        return self._cfg.get('cloudflare', {}).get('record_name', '')

    def has_wifi(self):
        return bool(self._cfg.get('wifi', {}).get('ssid'))

    def has_cloudflare(self):
        return bool(self._cfg.get('cloudflare', {}).get('api_key'))
