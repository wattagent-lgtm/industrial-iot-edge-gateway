# IIoT Data Traffic Calculation Principle

This guide estimates traffic across the complete path:

```text
Sensor tags → JSON → TCP/LAN → Gateway queue → MQTT/TLS/4G → AWS IoT Core
```

The calculations are engineering estimates for sizing a SIM data plan,
publish interval, MQTT queue, and cloud storage. Validate the final design with
measured modem counters and AWS metrics.

## 1. Measure bytes, not characters or tag count

One MQTT message may contain one tag or many tags. Therefore, `messages/s`
does not directly determine capacity.

Measure the serialized UTF-8 JSON:

```python
payload_bytes = len(json_string.encode("utf-8"))
```

Compact field names reduce traffic, but names must remain understandable.
Whitespace should normally be removed from production JSON.

## 2. Separate sampling rate from publish rate

A sensor can be sampled rapidly without publishing every raw sample.

| Signal | Example sampling | Recommended edge handling | Example publish |
| --- | ---: | --- | ---: |
| Vibration | 100 ms | RMS, peak, crest factor | 1–2 s |
| Flow/pressure | 500 ms | latest, min, max, average | 1–2 s |
| Machine status | 500 ms | publish immediately on change | event + heartbeat |
| Temperature | 2 s | latest value + deadband | 5–30 s |
| Raw waveform | high speed | capture only for diagnostics | on demand |

The gateway should transport aggregated features and events. It should not
continuously send high-frequency raw vibration samples over LTE.

## 3. Variables

For every message class `i`:

| Symbol | Meaning | Unit |
| --- | --- | --- |
| `P_i` | Serialized JSON payload | bytes/message |
| `T_i` | UTF-8 MQTT topic | bytes/message |
| `R_i` | Effective publish rate after deadband | messages/second |
| `O_i` | MQTT + TLS + TCP/IP planning overhead | bytes/message |
| `M` | Planning margin for reconnect/retransmission | fraction |
| `D` | Billing period | days |

For early planning, use `O_i = 100 bytes/message` and `M = 0.20`. Replace
these assumptions with measurements from the deployed modem and network.

## 4. Core formulas

For a single message class:

```text
Application bytes/s = P × R
Estimated 4G bytes/s = (P + T + O) × R
Estimated 4G bytes/day = (P + T + O) × R × 86,400
Estimated 4G bytes/month = (P + T + O) × R × 86,400 × D × (1 + M)
Messages/month = R × 86,400 × D
```

For multi-rate telemetry:

```text
Total 4G bytes/month =
  Σ[(P_i + T_i + O_i) × R_i] × 86,400 × D × (1 + M)
```

Calculate fast, slow, event, diagnostic, command, response, and heartbeat
classes separately, then add them.

## 5. Deadband and event-rate calculation

Deadband changes the effective rate. Do not use the sensor scan rate in the
LTE formula when values are suppressed.

```text
Effective rate = messages actually published ÷ observation seconds
Suppression ratio = 1 − (published messages ÷ sampled values)
```

Example: temperature is sampled every 2 seconds for one hour (1,800 samples),
but deadband and heartbeat produce 120 messages:

```text
Effective rate = 120 ÷ 3,600 = 0.0333 messages/s
Suppression ratio = 1 − (120 ÷ 1,800) = 93.3%
```

Alarm and event traffic should be estimated with a documented expected rate
and a separate worst-case burst rate. Important events must not be suppressed
by telemetry deadband.

## 6. Worked example: one aggregated message per second

Assumptions:

- JSON payload: `800 bytes`
- MQTT topic: `70 bytes`
- Planning overhead: `100 bytes/message`
- Publish rate: `1 message/s`
- Period: `30 days`
- Margin: `20%`

```text
Base traffic = (800 + 70 + 100) × 1 × 86,400 × 30
             = 2,514,240,000 bytes
             = 2.514 GB/month (decimal)

Planned traffic = 2.514 × 1.20
                = 3.017 GB/month per gateway
```

One message per second can carry many tags. With a compact schema, a practical
starting point is approximately 20–30 numeric/status tags in an aggregated
payload near 1 KB. Always measure the real JSON rather than relying on this
tag-count guideline.

## 7. Multi-rate example

| Class | Payload | Topic | Rate | Base 4G estimate |
| --- | ---: | ---: | ---: | ---: |
| Fast telemetry | 650 B | 75 B | 0.67 msg/s | 552.8 B/s |
| Slow telemetry | 450 B | 75 B | 0.20 msg/s | 125.0 B/s |
| Heartbeat | 300 B | 70 B | 0.0167 msg/s | 7.8 B/s |
| Event average | 400 B | 65 B | 0.001 msg/s | 0.6 B/s |

With `100 B/message` overhead, the total is approximately `686 B/s` before
the planning margin, or about `2.13 GB/30 days` including a 20% margin.

Also test the burst case. Average traffic may be acceptable while a short
event burst still fills a small RAM queue.

## 8. TCP/LAN calculation

For persistent TCP with newline-delimited JSON:

```text
TCP application bytes/s ≈ (P + delimiter + ACK payload) × R
```

Ethernet/Wi-Fi, TCP/IP, retransmission, and TCP acknowledgement frames add
network overhead. Opening a new TCP connection for every payload adds more
handshake traffic, latency, socket churn, and RAM allocation than a persistent
connection.

The response `{"status":"OK"}` confirms only that the gateway accepted the
frame. It does not prove that AWS IoT Core or DynamoDB received it.

## 9. Queue and throughput sizing

Measure these rates independently:

```text
Ingress rate = TCP frames accepted per second
Egress rate = MQTT messages acknowledged per second
Queue growth = ingress-to-MQTT rate − MQTT acknowledged rate
```

For a temporary outage:

```text
Required queue messages ≥ effective publish rate × outage seconds
Required queue RAM ≈ queue messages × (payload + topic + object overhead)
```

An ESP32 RAM queue should remain bounded. For longer outages, use SD-card
store-and-forward rather than increasing the RAM queue without limit.

## 10. What to monitor during a test

- TCP attempted, ACK, rejected, timeout, and latency
- JSON payload bytes and messages per data class
- MQTT queued, published, coalesced, dropped, failed, and reconnects
- LTE signal, registration, mobile IP, and internet-test latency
- Start/minimum/end free memory and restart count
- AWS IoT Rule errors and DynamoDB throttling
- DynamoDB item count compared with MQTT published count
- Actual SIM data usage compared with the estimate

## 11. Acceptance principle

A test is not successful only because TCP ACK is 100%. A complete result
requires all layers to be evaluated:

```text
TCP accepted
  → MQTT queued
  → MQTT PUBACK/published
  → AWS IoT Rule success
  → DynamoDB item stored
```

Record losses and latency at each boundary so the bottleneck can be located.

## 12. PowerShell calculator

Run the included calculator from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tests\calculate_traffic.ps1 `
  -PayloadBytes 800 `
  -TopicBytes 70 `
  -MessagesPerSecond 1 `
  -Days 30 `
  -OverheadBytes 100 `
  -MarginPercent 20
```

Use one calculation per message class and add the resulting totals for a
multi-rate workload.
