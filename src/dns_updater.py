import json
import time

CHECK_INTERVAL_MS = 60 * 1000  # 1 minute

CF_BASE        = 'https://api.cloudflare.com/client/v4/zones/'
CF_RECORDS_EXT = '/dns_records?name='


class DnsUpdater:
    def __init__(self, wifi_manager, config_manager, status_led=None):
        self.wifi = wifi_manager
        self.config = config_manager
        self._led = status_led
        self._last_ip = None
        self._last_check = None       # ticks_ms() of last check attempt
        self._zone_ip = None          # content currently in the Cloudflare record
        self._record_type = None      # 'A' or 'CNAME', detected from the API
        self._cf_status = None        # None=unknown, 'valid', 'invalid', 'unconfigured'
        self._last_dns_update = None  # formatted timestamp of last successful update

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_time():
        t = time.localtime()
        if t[0] < 2026:  # clock not yet synced (ESP32 boots at year 2000)
            return None
        return '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
            t[0], t[1], t[2], t[3], t[4], t[5])

    def _cf_headers(self, api_key):
        return {
            'Authorization': 'Bearer ' + api_key,
            'Content-Type': 'application/json',
        }

    # ------------------------------------------------------------------ #
    #  Public IP                                                           #
    # ------------------------------------------------------------------ #

    def get_public_ip(self):
        """Fetch the current public IP from api.ipify.org.
        Returns None immediately if not in client mode or if wifi is down."""
        if self.wifi.get_mode() != 'client' or not self.wifi.is_connected():
            return None
        try:
            import urequests
            r = urequests.get('http://api.ipify.org')
            ip = r.text.strip()
            r.close()
            return ip
        except Exception as e:
            print('get_public_ip error:', e)
            return None

    def _apply_ip(self, ip):
        """Compare ip against the last known value and call update_dns if it changed."""
        if ip != self._last_ip:
            print('Public IP changed:', self._last_ip, '->', ip)
            self._last_ip = ip
            self.update_dns(ip)
        else:
            self._last_ip = ip

    def force_check(self):
        """Force an immediate IP check, bypassing the 1-minute timer.
        Fetches Cloudflare zone status on the first call.
        Resets the timer so the next automatic check is 1 minute from now.
        Returns the current public IP or None."""
        self._last_check = time.ticks_ms()
        # Guard the LED call: set_ip_check() must not overwrite set_ap() when
        # we are in AP mode and will return None without making any request.
        if self._led and self.wifi.get_mode() == 'client' and self.wifi.is_connected():
            self._led.set_ip_check()
        ip = self.get_public_ip()
        if ip is None:
            return None
        if self._cf_status is None:
            self._fetch_cf_status()
        self._apply_ip(ip)
        return self._last_ip

    def current_ip(self):
        """Return the last known public IP, or None if not yet fetched."""
        return self._last_ip

    # ------------------------------------------------------------------ #
    #  Cloudflare status                                                   #
    # ------------------------------------------------------------------ #

    def _fetch_cf_status(self):
        """Query Cloudflare for the current record value and validate the API key.
        Sets _cf_status ('valid'/'invalid'/'unconfigured'), _zone_ip, and _record_type."""
        api_key = self.config.get_cf_api_key()
        zone_id = self.config.get_cf_zone_id()
        record_name = self.config.get_cf_record_name()

        if not api_key or not zone_id or not record_name:
            self._cf_status = 'unconfigured'
            return

        import urequests
        try:
            r = urequests.get(CF_BASE + zone_id + CF_RECORDS_EXT + record_name,
                              headers=self._cf_headers(api_key))
            data = r.json()
            r.close()
            if data.get('success'):
                self._cf_status = 'valid'
                results = data.get('result', [])
                if results:
                    self._zone_ip = results[0]['content']
                    self._record_type = results[0]['type']
            else:
                self._cf_status = 'invalid'
        except Exception as e:
            print('_fetch_cf_status error:', e)

    def status(self):
        """Return a dict with all status fields for the /cf-status endpoint."""
        return {
            'zone_ip':         self._zone_ip         or 'unknown',
            'record_type':     self._record_type      or 'unknown',
            'cf_status':       self._cf_status        or 'unknown',
            'last_dns_update': self._last_dns_update  or 'never',
        }

    # ------------------------------------------------------------------ #
    #  DNS update                                                          #
    # ------------------------------------------------------------------ #

    def update_dns(self, ip):
        """Update the configured Cloudflare record (A or CNAME) with the new public IP."""
        api_key = self.config.get_cf_api_key()
        zone_id = self.config.get_cf_zone_id()
        record_name = self.config.get_cf_record_name()

        if not api_key or not zone_id or not record_name:
            print('update_dns: Cloudflare config incomplete, skipping')
            return

        headers = self._cf_headers(api_key)
        import urequests

        # Step 1 — find the record ID and type
        try:
            r = urequests.get(CF_BASE + zone_id + CF_RECORDS_EXT + record_name,
                              headers=headers)
            data = r.json()
            r.close()
            if not data.get('success'):
                print('update_dns: API error fetching record:', data.get('errors'))
                self._cf_status = 'invalid'
                return
            if not data.get('result'):
                print('update_dns: record not found for', record_name)
                return
            record = data['result'][0]
            record_id   = record['id']
            record_type = record['type']  # 'A' or 'CNAME'
            self._record_type = record_type
        except Exception as e:
            print('update_dns: error fetching record id:', e)
            return

        # Step 2 — update the record content
        try:
            url = CF_BASE + zone_id + '/dns_records/' + record_id
            body = json.dumps({'type': record_type, 'name': record_name, 'content': ip, 'ttl': 1})
            r = urequests.put(url, data=body, headers=headers)
            result = r.json()
            r.close()
            if result.get('success'):
                print('update_dns: updated', record_name, '->', ip)
                self._zone_ip = ip
                self._cf_status = 'valid'
                ts = self._format_time()
                if ts:
                    self._last_dns_update = ts
                if self._led:
                    self._led.set_dns_update()
            else:
                print('update_dns: API error:', result.get('errors'))
                self._cf_status = 'invalid'
        except Exception as e:
            print('update_dns: error updating record:', e)

    # ------------------------------------------------------------------ #
    #  Periodic tick                                                       #
    # ------------------------------------------------------------------ #

    def tick(self):
        """Call from the main loop; checks public IP every minute (client mode only)."""
        now = time.ticks_ms()
        if self._last_check is not None and time.ticks_diff(now, self._last_check) < CHECK_INTERVAL_MS:
            return
        self._last_check = now
        self.force_check()
