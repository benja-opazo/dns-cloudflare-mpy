import gc
import json
import time
from log import log, fmt_datetime

CHECK_INTERVAL_MS = 60 * 1000  # 1 minute
HTTP_TIMEOUT = 10  # seconds — bound each request so a hung call can't stall the loop

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
        self._wdt = None              # optional hardware watchdog to feed during I/O

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def set_wdt(self, wdt):
        """Register the hardware watchdog so long network calls can feed it."""
        self._wdt = wdt

    def _feed(self):
        """Feed the watchdog (if any) before a blocking network call, so a slow
        request doesn't trip the WDT and reset the board mid-refresh."""
        if self._wdt:
            self._wdt.feed()

    @staticmethod
    def _format_time():
        t = time.localtime()
        if t[0] < 2026:  # clock not yet synced (ESP32 boots at year 2000)
            return None
        return fmt_datetime(t)

    def _cf_headers(self, api_key):
        return {
            'Authorization': 'Bearer ' + api_key,
            'Content-Type': 'application/json',
        }

    def _cf_config(self):
        """Return (api_key, zone_id, record_name), or None if any field is unset."""
        api_key = self.config.get_cf_api_key()
        zone_id = self.config.get_cf_zone_id()
        record_name = self.config.get_cf_record_name()
        if not api_key or not zone_id or not record_name:
            return None
        return api_key, zone_id, record_name

    def _get_record(self, api_key, zone_id, record_name):
        """GET the DNS record by name from Cloudflare.

        Returns (data, record): data is the parsed API response (check
        data['success'] / data['errors']); record is data['result'][0], or
        None if the zone has no matching record. Raises on network/parse
        errors — callers wrap the call with their own contextual logging.
        """
        import urequests
        gc.collect()
        self._feed()
        r = urequests.get(CF_BASE + zone_id + CF_RECORDS_EXT + record_name,
                          headers=self._cf_headers(api_key), timeout=HTTP_TIMEOUT)
        try:
            data = r.json()
        finally:
            r.close()
        results = data.get('result') or []
        return data, (results[0] if results else None)

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
            gc.collect()
            self._feed()
            r = urequests.get('http://api.ipify.org', timeout=HTTP_TIMEOUT)
            try:
                ip = r.text.strip()
            finally:
                r.close()
            log(f'Public IP check: {ip}')
            return ip
        except Exception as e:
            log(f'get_public_ip error [{type(e).__name__}]: {e}')
            gc.collect()
            return None

    def _apply_ip(self, ip):
        """Compare ip against the last known value and call update_dns if it changed."""
        if ip != self._last_ip:
            log(f'Public IP changed: {self._last_ip} -> {ip}')
            self._last_ip = ip
            self.update_dns(ip)
        else:
            log(f'Public IP unchanged: {ip}')
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
        if self.wifi.get_mode() != 'client':
            log(f'IP check skipped — not in client mode (mode={self.wifi.get_mode()})')
            return None
        if not self.wifi.is_connected():
            log('IP check skipped — Wi-Fi not connected')
            return None
        ip = self.get_public_ip()
        if ip is None:
            log('IP check failed — could not fetch public IP')
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
        cfg = self._cf_config()
        if cfg is None:
            self._cf_status = 'unconfigured'
            log('Cloudflare status: unconfigured (missing api_key/zone_id/record_name)')
            return
        api_key, zone_id, record_name = cfg

        try:
            data, record = self._get_record(api_key, zone_id, record_name)
            if not data.get('success'):
                self._cf_status = 'invalid'
                log(f'Cloudflare status: invalid — {data.get("errors")}')
                return
            self._cf_status = 'valid'
            if record:
                self._zone_ip = record['content']
                self._record_type = record['type']
                log(f'Cloudflare status: valid — {self._record_type} record '
                    f'{record_name} = {self._zone_ip}')
            else:
                log(f'Cloudflare status: valid — no record found for {record_name}')
        except Exception as e:
            log(f'_fetch_cf_status error [{type(e).__name__}]: {e}')
            gc.collect()

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
        cfg = self._cf_config()
        if cfg is None:
            log('update_dns: Cloudflare config incomplete, skipping')
            return
        api_key, zone_id, record_name = cfg

        if ip == self._zone_ip:
            log(f'update_dns: zone already at {ip} — updating anyway')

        # Step 1 — find the record ID and type
        try:
            data, record = self._get_record(api_key, zone_id, record_name)
            if not data.get('success'):
                log(f'update_dns: API error fetching record: {data.get("errors")}')
                self._cf_status = 'invalid'
                return
            if not record:
                log(f'update_dns: record not found for {record_name}')
                return
            record_id   = record['id']
            record_type = record['type']  # 'A' or 'CNAME'
            self._record_type = record_type
        except Exception as e:
            log(f'update_dns: error fetching record id [{type(e).__name__}]: {e}')
            gc.collect()
            return

        # Step 2 — update the record content
        headers = self._cf_headers(api_key)
        import urequests
        try:
            url = CF_BASE + zone_id + '/dns_records/' + record_id
            body = json.dumps({'type': record_type, 'name': record_name, 'content': ip, 'ttl': 1})
            gc.collect()
            self._feed()
            r = urequests.put(url, data=body, headers=headers, timeout=HTTP_TIMEOUT)
            try:
                result = r.json()
            finally:
                r.close()
            if result.get('success'):
                log(f'update_dns: updated {record_name} -> {ip}')
                self._zone_ip = ip
                self._cf_status = 'valid'
                ts = self._format_time()
                if ts:
                    self._last_dns_update = ts
                if self._led:
                    self._led.set_dns_update()
            else:
                log(f'update_dns: API error: {result.get("errors")}')
                self._cf_status = 'invalid'
        except Exception as e:
            log(f'update_dns: error updating record [{type(e).__name__}]: {e}')

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
