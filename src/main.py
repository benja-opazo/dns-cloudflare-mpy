import time
from config import ConfigManager
from wifi_manager import WiFiManager
from server import Server
from dns_updater import DnsUpdater
from pins import StatusLed


def main():
    print('--- boot ---')
    t0 = time.ticks_ms()

    print('[1/5] Initialising status LED...')
    led = StatusLed()

    print('[2/5] Loading config...')
    config = ConfigManager()
    print(f'  saved SSID: {config.get_wifi_ssid() or "(none)"}')

    print('[3/5] Setting up Wi-Fi...')
    wifi = WiFiManager()

    if config.has_wifi():
        led.set_connecting()
        ip = wifi.connect_sta(config.get_wifi_ssid(), config.get_wifi_password(),
                              config.get_hostname())
        if ip:
            led.set_connected()
            try:
                import ntptime
                ntptime.settime()
                print('  NTP sync OK')
            except Exception as e:
                print('  NTP sync failed:', e)
        else:
            print('Could not connect to saved network — falling back to AP mode')
            wifi.start_ap_mode()
            led.set_ap()
    else:
        print('No Wi-Fi credentials saved — starting AP mode')
        wifi.start_ap_mode()
        led.set_ap()

    print(f'  Wi-Fi ready in {time.ticks_diff(time.ticks_ms(), t0)}ms'
          f'  mode={wifi.get_mode()}  ip={wifi.get_ip()}')

    print('[4/5] Creating DNS updater...')
    dns_updater = DnsUpdater(wifi, config, led)

    print('[5/5] Starting server...')
    server = Server(wifi, config, dns_updater, led)
    server.start()

    print(f'Boot complete in {time.ticks_diff(time.ticks_ms(), t0)}ms')
    server.run_forever()


main()
