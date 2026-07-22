# XIAO ESP32-C3 Industrial Telemetry Client

This MicroPython project simulates `Pump-01` and sends 20 newline-delimited JSON
telemetry messages to `192.168.1.42:5005`. One message is sent per TCP connection,
the gateway acknowledgement is validated, and the simulation stops after one hour.

## 1. Install MicroPython

1. Download the current `ESP32_GENERIC_C3` firmware from the MicroPython ESP32-C3
   download page linked by the [Seeed XIAO ESP32-C3 MicroPython guide](https://wiki.seeedstudio.com/XIAO_ESP32C3_MicroPython/).
2. Install Thonny, connect the XIAO with a data-capable USB-C cable, and select
   **Run > Configure interpreter > MicroPython (ESP32)** plus the board's COM port.
3. If firmware is not installed, use Thonny's **Install or update MicroPython**
   dialog, select the ESP32-C3 target and downloaded `.bin`, then install it.
4. Reconnect and confirm that the `>>>` MicroPython prompt appears.

The board can also be put into its ROM bootloader by holding **BOOT** while connecting
USB. Follow the Seeed guide for recovery or command-line flashing details.

## 2. Configure the client

Edit `config.py` before uploading. The important settings are:

```python
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
GATEWAY_IP = "192.168.1.42"
GATEWAY_PORT = 5005
```

For another physical client, assign a unique `NODE_ID` and appropriate device
metadata. `node_id`, rather than the changing client IP address, is the permanent
gateway identity.

## 3. Copy with Thonny

1. Open Thonny and select the XIAO's **MicroPython (ESP32)** interpreter.
2. In **View > Files**, browse to this project on the upper/local pane.
3. Select all eight `.py` files and choose **Upload to /**.
4. Verify that `boot.py`, `main.py`, and the six modules appear in the device pane.
5. Press the board reset button, or press `Ctrl+D` in the Thonny shell.

Do not copy this README to the board; it is not needed at runtime.

## 4. Copy with mpremote

Install the official MicroPython tool and enter this project directory:

```powershell
py -m pip install mpremote
cd C:\Users\Admin\Downloads\Liliygo\iiot_gateway_web_dashboard\xiao_esp32c3_client
```

List devices and copy the runtime files:

```powershell
mpremote connect list
mpremote fs cp boot.py config.py main.py wifi_manager.py tcp_client.py simulator.py logger.py utils.py :
mpremote reset
mpremote repl
```

If auto-detection selects the wrong device, add the port to each command, for example
`mpremote connect COM3 fs cp ...`. The remote `:` syntax and filesystem commands are
documented in the [official mpremote manual](https://docs.micropython.org/en/latest/reference/mpremote.html).

## 5. Run the simulation

Start the LILYGO gateway first. Reset the XIAO after all files have been uploaded.
MicroPython runs `boot.py` and then `main.py` automatically. The first packet is sent
immediately, the remaining packets follow a three-second schedule, and the process
stops at the configured one-hour boundary after 1,200 packet cycles.

Expected console output resembles:

```text
[INFO] Connecting to Wi-Fi: YOUR_WIFI_SSID
[INFO] Wi-Fi connected
[INFO] Client IP: 192.168.1.43
[INFO] Gateway: 192.168.1.42:5005
[INFO] Sending packet 1/1200
[INFO] Gateway ACK: OK
...
[INFO] Packets planned: 1200
[INFO] Packets acknowledged: 1200
[INFO] Packets failed: 0
[INFO] Simulation duration: 3600 seconds
[INFO] Simulation Complete
```

If TCP delivery fails, the same packet and sequence number are retried once after two
seconds. The program then continues to the next scheduled telemetry cycle.

## 6. Replace the simulator with sensors

Keep the transport and message-building modules unchanged. Replace `simulator.py` with
a driver-backed module that retains these two functions:

```python
def read_telemetry():
    return {"temperature_c": 32.6, "running": True}

def status_for(telemetry):
    return "RUNNING"
```

`read_telemetry()` can later collect values from MPU6050, ADXL345, SHT31, or DS18B20
drivers. Return a small dictionary of JSON-compatible values; `main.py` adds identity,
sequence, uptime, status, and routing metadata before handing it to `tcp_client.py`.

## Unified Namespace readiness

The stable metadata can be mapped by the gateway to a future topic such as:

```text
factory01/process/line01/pump01/telemetry
```

The XIAO intentionally publishes TCP JSON only. MQTT, NTP time synchronization, and
Unified Namespace publication remain gateway-side future integrations.
