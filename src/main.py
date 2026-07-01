import time

from config import ConfigManager
from dns_updater import DnsUpdater
from log import log
from pins import StatusLed
from server import Server
from timesync import sync_time
from wifi_manager import WiFiManager


def main():
    log("--- boot ---")
    t0 = time.ticks_ms()

    log("[1/5] Loading config...")
    config = ConfigManager()
    log(f"  saved SSID: {config.get_wifi_ssid() or '(none)'}")

    log("[2/5] Initialising status LED...")
    led_pin = config.get_led_pin()
    led = StatusLed(led_pin) if led_pin is not None else StatusLed()

    log("[3/5] Setting up Wi-Fi...")
    wifi = WiFiManager()

    if config.has_wifi():
        led.set_connecting()
        ip = wifi.connect_sta(
            config.get_wifi_ssid(), config.get_wifi_password(), config.get_hostname()
        )
        if ip:
            led.set_connected()
            sync_time(wifi)
        else:
            log("Could not connect to saved network — falling back to AP mode")
            wifi.start_ap_mode()
            led.set_ap()
    else:
        log("No Wi-Fi credentials saved — starting AP mode")
        wifi.start_ap_mode()
        led.set_ap()

    log(
        f"  Wi-Fi ready in {time.ticks_diff(time.ticks_ms(), t0)}ms"
        f"  mode={wifi.get_mode()}  ip={wifi.get_ip()}"
    )

    log("[4/5] Creating DNS updater...")
    dns_updater = DnsUpdater(wifi, config, led)

    log("[5/5] Starting server...")
    server = Server(wifi, config, dns_updater, led)
    server.start()

    log(f"Boot complete in {time.ticks_diff(time.ticks_ms(), t0)}ms")
    server.run_forever()


main()

# Network diagnostics: to run the connectivity test suite (DNS, HTTP, NTP,
# HTTPS/TLS), comment out the main() call above and uncomment the line below —
# or just run `import diag` from the REPL. See src/diag.py.
# import diag
