# Industrial IoT Edge Gateway

A production-oriented MicroPython gateway for the LILYGO T-A7670E
(ESP32 + A7670E LTE). It receives industrial telemetry over TCP/JSON,
acknowledges local clients immediately, and publishes data through a bounded
asynchronous MQTT queue over 4G LTE to AWS IoT Core and DynamoDB.

## Architecture

```text
XIAO ESP32-C3 clients
        | TCP/JSON :5005
        v
LILYGO T-A7670E Gateway
  |-- Immediate TCP ACK
  |-- Device Manager and REST dashboard
  |-- Multi-rate/deadband processing
  `-- Priority + coalescing MQTT queue
        | MQTT/TLS over 4G
        v
AWS IoT Core --> IoT Rule --> DynamoDB
```

## Engineering highlights

- Preserves the legacy TCP port 5005 and `{\"status\":\"OK\"}` response.
- Decouples local TCP ingestion from LTE/AWS latency.
- Supports bounded NDJSON frames and persistent TCP connections.
- Uses priority handling and latest-value coalescing for MQTT overload.
- Supports fast, slow, event, and diagnostic telemetry classes.
- Monitors SIM, LTE registration, signal, mobile IP, and internet reachability.
- Provides a responsive dashboard and REST health/status APIs.
- Uses Wi-Fi/HTTP supervisors, static addressing, and fatal crash recovery.
- Includes PowerShell workload and reliability test tools.

## Validated laboratory result

| Metric | 30-minute result |
|---|---:|
| TCP ACK | 2,032 / 2,032 (100%) |
| Gateway availability | 100% (60/60 samples) |
| MQTT dropped / failed | 0 / 0 |
| Service restarts | 0 |
| Average / maximum TCP latency | 182.9 / 627.2 ms |
| Start / end free memory | 68.2 / 67.7 KB |
| Average LTE signal | -70.4 dBm |

These are laboratory observations, not certification results.

## Quick start

1. Copy `gateway/config.example.py` to `gateway/config.py`.
2. Set local Wi-Fi, APN, AWS IoT endpoint, topics, and certificate paths.
3. Place AWS certificates in a local `certs/` folder (never commit them).
4. Copy the gateway Python files and dashboard assets to the ESP32.
5. Open `http://GATEWAY_IP` and send JSON to TCP port 5005.

Run a three-minute simulator test from Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tests\simulate_multirate_workload.ps1 `
  -GatewayIp 192.168.1.42 `
  -DurationSeconds 180
```

## Repository layout

- `gateway/` - MicroPython gateway runtime and configuration template
- `clients/` - XIAO ESP32-C3 example client
- `dashboard/` - responsive local web dashboard
- `tests/` - multi-rate load and reliability tools
- `docs/` - Thai architecture and data-flow reference

## Security

See [SECURITY.md](SECURITY.md). Real credentials, certificates, private keys,
and runtime logs are intentionally excluded.

## Roadmap

- SD-card store-and-forward
- OTA firmware updates and secure device provisioning
- Grafana/analytics integration
- Sensor anomaly detection and predictive maintenance
- Edge inference and SageMaker model lifecycle
