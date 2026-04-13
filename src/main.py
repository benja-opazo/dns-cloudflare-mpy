from config import ConfigManager
from wifi_manager import WiFiManager
from server import Server


def main():
    config = ConfigManager()
    wifi = WiFiManager()

    if config.has_wifi():
        ip = wifi.connect_sta(config.get_wifi_ssid(), config.get_wifi_password())
        if not ip:
            print('Could not connect to saved network — falling back to AP mode')
            wifi.start_ap_mode()
    else:
        print('No Wi-Fi credentials saved — starting AP mode')
        wifi.start_ap_mode()

    server = Server(wifi, config)
    server.start()
    server.run_forever()


main()
