# Validated Operating Envelope and Current Limitations

This document separates software-configured limits, observed laboratory
performance, and a conservative provisional operating rating. The values are
not product certification results.

## Platform

| Item | Implementation |
|---|---|
| Controller | ESP32 running MicroPython |
| Cellular modem | SIMCom A7670E LTE Cat-1 |
| Southbound transport | Wi-Fi TCP/JSON on port 5005 |
| Northbound transport | MQTT/TLS over LTE to AWS IoT Core |
| Local management | HTTP dashboard and REST API on port 80 |
| Local acknowledgement | `{"status":"OK"}` after bounded JSON validation |

## Software-configured limits

| Limit | Value |
|---|---:|
| Maximum TCP JSON frame | 4,096 bytes |
| TCP read block | 1,024 bytes |
| TCP client idle timeout | 5 seconds |
| Frame completion timeout | 150 ms |
| Maximum concurrent HTTP requests | 6 |
| MQTT RAM queue | 20 entries |
| Tracked device records | 50 |
| In-memory log entries | 500 |

These values are implementation bounds, not proof that every combination can
operate simultaneously at maximum load.

## Laboratory observations

The workload used multi-rate fast, slow, event, and diagnostic payloads with
latest-value MQTT coalescing.

| Test | Aggregate input | TCP ACK success | Availability | Resets |
|---|---:|---:|---:|---:|
| 1 minute | about 1.06 msg/s | 100% | 100% | 0 |
| 5 minutes | about 1.15 msg/s | 100% | 100% | 0 |
| 30 minutes, WebREPL enabled | about 1.14 msg/s | 98.59% | 95.0% | 2 |
| 2 hours | about 1.17 msg/s | 98.41% | 96.74% | 3 |
| 30 minutes, WebREPL disabled | about 1.13 msg/s | 99.75% | 100% sampled | 1 |

The best 30-minute run with WebREPL disabled acknowledged 2,030 of 2,035
messages. MQTT reported zero queue drops and zero publish failures, but the
gateway automatically recovered from one fatal network I/O exception. The
30-second reliability sampler did not miss a sample because recovery completed
inside the sample interval.

Crash evidence consistently showed `OSError: [Errno 5] EIO` in
`uasyncio.wait_io_event` with approximately 43-50 KB of free heap. This does
not resemble progressive heap exhaustion. WebREPL increased socket pressure
and worsened the observed result, but disabling it did not eliminate the
underlying event-loop/network I/O fault.

## Provisional operating rating

Until an 8-24 hour soak test completes with zero unexpected resets, use this
conservative rating:

| Parameter | Provisional rating |
|---|---:|
| Sustained aggregate TCP input | 0.5 msg/s |
| Short laboratory burst | 1 msg/s for up to 5 minutes |
| Recommended average JSON payload | 1 KB or less |
| Maximum accepted JSON frame | 4 KB |
| Recommended TCP clients | 1-5 |
| Recommended active devices initially | 10 or fewer |
| Dashboard users during operation | 1 |
| WebREPL during production operation | Disabled |

The 50-device table capacity is a software allocation limit. It is not a
validated concurrent-device rating.

## Recommended balanced telemetry profile

Sampling and publishing are separate activities. High-rate signals should be
aggregated at the client before transmission.

| Signal | Local sampling | Network publish policy |
|---|---:|---|
| Vibration | 100 ms | RMS/peak summary every 1-2 seconds |
| Flow | 500 ms | Every 1-2 seconds with deadband |
| Machine status | 500 ms | Immediately on change |
| Temperature | 2 seconds | Every 5 seconds with deadband |
| Diagnostic health | Local | Every 60 seconds |
| Alarm/event | Immediate | Immediate, priority queue |

Recommended gateway settings:

```python
WEBREPL_ENABLED = False
TCP_CLIENT_IDLE_TIMEOUT_MS = 5000
HTTP_HEALTH_INTERVAL_SECONDS = 60
MODEM_INTERNET_TEST_INTERVAL_SECONDS = 1800
MQTT_QUEUE_CAPACITY = 20
MQTT_KEEPALIVE_SECONDS = 60
```

## Traffic estimate

The measured multi-rate workload consumed approximately 1.34 MB per
30 minutes including estimated transport overhead:

```text
approximately 2.7 MB/hour
approximately 65 MB/day at continuous equivalent load
```

Actual SIM usage depends on reconnects, TLS handshakes, MQTT topic length,
payload size, keepalive behavior, retransmissions, and carrier accounting.

## Known limitations

1. A fatal ESP32 `uasyncio`/network `EIO` can still trigger automatic recovery.
2. The MQTT queue is held in RAM and is lost during a hardware reset.
3. Persistent SD-card store-and-forward is not implemented yet.
4. TCP ingestion has no client authentication or transport encryption.
5. The local HTTP dashboard has no HTTPS or user authentication.
6. WebREPL should remain disabled outside a controlled maintenance window.
7. CPU utilization is not exposed reliably by the current MicroPython port.
8. The implementation has not yet completed a zero-reset 24-hour qualification.

## Qualification target

Before advertising continuous 1 msg/s production capability, require:

| Metric | Acceptance target |
|---|---:|
| Soak duration | 24 hours or more |
| TCP ACK success | 99.9% or better |
| Sampled availability | 99.9% or better |
| Unexpected reset | 0 |
| MQTT queue drops | 0 |
| Minimum free heap | 30 KB or more |
| Maximum TCP ACK latency | Below 2 seconds |

The current implementation should therefore be described as a
**pre-production industrial IoT gateway prototype with automatic recovery**,
not as a certified commercial gateway.
