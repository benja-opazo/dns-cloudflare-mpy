import machine
import network
import time

pin = machine.Pin(2, machine.Pin.OUT)

wlan = network.WLAN()
wlan.active(True)
wlan.connect('<ssid>', '-')

for i in range(10):

	pin.on()
	time.sleep(0.5)
	pin.off()
	time.sleep(1)