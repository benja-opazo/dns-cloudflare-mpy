# ESP32-DNS-Cloudflare

![Logo](./imgs/logo.png)

> [!NOTE]
> This app has been partially vibe-coded.
> I made it for my personal use, but I am sharing it because it works perfectly for my use case and may be useful for others.
> If you have an issue with the app being vibe-coded, please refrain from making any comments. Thanks.

## Prerequisites

- `uv`
- A Microcontroller with [Micropython](https://micropython.org/) installed

## Initialization

### Project Dependencies

To initialize the project

`uv sync`

then activate with:

`source .venv/bin/activate`

### MicroPython Stubs (Optional)

With the environment activated, install the Stubs with

`pip install -U micropython-esp32-stubs==1.26.0.post1 --target typings --no-user`

Create a `.vscode` folder with a `settings.json` file:

```json
{
    "python.languageServer": "Pylance",
    "python.analysis.typeCheckingMode": "basic",
    "python.analysis.diagnosticSeverityOverrides": {
    "reportMissingModuleSource": "none"
    },
    "python.analysis.typeshedPaths": [
        "typings"
    ],
} 
```

## Installation on ESP32

Using mpremote, copy the files inside the src folder. The following code should work.

```bash
cd src
mpremote fs cp -r . :/
```

## Usage

After uploading the project files to the ESP-32, do a Soft Reset and connect to the microcontroller AP. The AP SSID is `ESP32-DNSConfig`.

Once connected, go to `192.168.4.1` and the main page should load. If it's not loading, check that you are connecting with `http` and not `https`. If you are still having trouble, you can add port `80` explicitly: `192.168.4.1:80`.

Once inside, you can configure the Wi-Fi and Cloudflare credentials, and check the status of the program.

<p float="left">
  <img src="./imgs/wifi_credentials.jpg" width="250"/>
  <img src="./imgs/dns_credentials.jpg" width="250"/> 
  <img src="./imgs/status.jpg" width="250"/>
</p>

In the Wifi Credentials tab, the ESP32 automatically scans for available SSIDs, if you want to connect to a hidden SSID, choose `other`. You can also configure your preferred Hostname.

For the Cloudflare DNS tab you will need an API token with `Zone:DNS:Edit` permissions, the Zone ID, and the DNS record name (e.g. `home.example.com`). Both A and CNAME records are supported, but only an A Record can be filled with an IP Adress.

In the status tab, you can check the current IP address, if the API Key is valid, what IP is in the Zone and the Last DNS Update. You can force a refresh clicking the Refresh button.

## Leds

A LED on GPIO 2 shows the current status of the board. The following table lists the possible states.

| State | LED behaviour | Trigger |
|---|---|---|
| `ap` | Slow breathing | No saved Wi-Fi credentials, or STA connect failed — device started AP mode |
| `connecting` | 2 Hz blink (infinite) | `wifi.connect_sta()` called, waiting for association |
| `connected` | Solid on for 3 s, then off | STA successfully associated and got an IP |
| `ip_check` | 1 blink | Periodic or forced public IP check (`force_check()`), client mode only |
| `dns_update` | 3 blinks | Cloudflare A/CNAME record successfully updated with new IP |
| `off` | Off | Idle — after `connected` timer expires, or initial state |

If the device fails to connect to Wi-Fi, it falls back to AP mode so it can be reconfigured. Once Wi-Fi is available again, a reset is enough to revert to client mode.

## Manually Uploading config.json

To skip the web interface, upload a `config.json` file directly to the device root:

```json
{
  "wifi": {
    "ssid": "<your_ssid>",
    "password": "<your_password>",
    "hostname": "<optional: override the hostname>"
  },
  "cloudflare": {
    "api_key": "<api_key>",
    "record_name": "<record_name>",
    "zone_id": "<zone_id>"
  },
  "led_pin": 2
}
```

```bash
mpremote fs cp config.json :/
```

> [!NOTE]
>`led_pin` is optional and can only be set manually. It is not exposed in the web interface. Omit it to use the default GPIO 2.

## Troubleshooting

If you encounter any problems, connect via serial port to get debug output and diagnose the issue.
