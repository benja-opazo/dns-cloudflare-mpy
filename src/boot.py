import webrepl
import network

webrepl.start()


wlan = network.WLAN()
wlan.active(True)
wlan.connect('<ssid>', '-')