# Industrial IoT Edge Gateway

[![Repository checks](https://github.com/wattagent-lgtm/industrial-iot-edge-gateway/actions/workflows/quality.yml/badge.svg)](https://github.com/wattagent-lgtm/industrial-iot-edge-gateway/actions/workflows/quality.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MicroPython](https://img.shields.io/badge/runtime-MicroPython-2b2728.svg)](https://micropython.org/)

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

## Architecture and data-flow guide

Read the complete Thai reference directly on GitHub:

- [Client → TCP Gateway → 4G MQTT → AWS IoT Core data flow](docs/IIoT_Gateway_Client_to_AWS_Data_Flow_TH.md)
- [Original Microsoft Word edition](docs/IIoT_Gateway_Client_to_AWS_Data_Flow_TH_v2.docx)

The guide covers immediate TCP acknowledgement, asynchronous MQTT queues,
UNS topics, multi-rate sampling, deadband, traffic calculation, DynamoDB,
failure recovery, and laboratory comparison results.

## Security

See [SECURITY.md](SECURITY.md). Real credentials, certificates, private keys,
and runtime logs are intentionally excluded.

## Contributing

Bug reports, test evidence, and focused improvements are welcome. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before opening an issue or pull request.

Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Roadmap

- SD-card store-and-forward
- OTA firmware updates and secure device provisioning
- Grafana/analytics integration
- Sensor anomaly detection and predictive maintenance
- Edge inference and SageMaker model lifecycle
