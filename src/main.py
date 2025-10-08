import machine
import network
import time
import socket
import os

def replace_with_dict(data, dictionary):
	for key, value in dictionary.items():
		data = data.replace(f"{{{{{key}}}}}", value)
	return data

pin = machine.Pin(2, machine.Pin.OUT)

data_buffer = 1024*8
ssid = '<ssid>'
password = '-'

wlan = network.WLAN(network.WLAN.IF_STA)
wlan_ap = network.WLAN(network.WLAN.IF_AP)

wlan.active(True)
wlan.connect(ssid, password)

while not wlan.isconnected():
	pass

if wlan.isconnected():
	print("Connected!!")
	ip = wlan.ifconfig()[0]
	print(f"IP: {ip}")

# Create a socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind((ip, 80))  # Bind to port 80 (HTTP)
server_socket.listen(5)  # Listen for connections

# Get webpage
response = open("data/index.html").read()
#css = open("data/tailwind.css").read()

data_dictionary = {
	'CURRENT_STATUS': '',
	'CURRENT_SSID': '',
	'CURRENT_IP': '',
	'SAVED_SSID': ''
}

while True:
	conn, addr = server_socket.accept()
	print("Client connected from:", addr)
	
	request = conn.recv(1024).decode().splitlines()  # Read request from client
	print("Request:", request[0])

	if request[0].startswith("GET /tailwind.css"):
		file = open("data/tailwind.css")
	elif request[0].startswith("POST /save-wifi"):
		file = open("data/index.html")
		save_wifi_request = request[-1].split("&")
		print(save_wifi_request)
		ssid = save_wifi_request[0].split("=")[1].replace("+", " ")
		password = save_wifi_request[1].split("=")[1]

		wlan.disconnect()
		time.sleep(1)
		wlan.connect(ssid, password)
		while not wlan.isconnected():
			pass

		if wlan.isconnected():
			print("Connected!!")
			ip = wlan.ifconfig()[0]
			print(f"IP: {ip}")
			data_dictionary['SAVED_SSID'] = ssid

		print(ssid)
		print(password)
	else:
		file = open("data/index.html")

	if file is not None:
		data = file.read(data_buffer)
		while data:
			if(wlan.active()):
				data_dictionary['CURRENT_STATUS'] = "Client Mode"
			elif wlan_ap.active():
				data_dictionary['CURRENT_STATUS'] = "AP Mode"

			data_dictionary['CURRENT_SSID'] = wlan.config('essid')
			data_dictionary['CURRENT_IP'] = wlan.ifconfig()[0]

			data_replaced = replace_with_dict(data, data_dictionary)
			conn.send(data_replaced.encode())
			data = file.read(data_buffer)

		file.close()
	conn.close()  # Close connection