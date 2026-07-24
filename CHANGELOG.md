# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

- Dedicated TCP/JSON/MQTT/TLS/4G traffic calculation guide.
- PowerShell traffic and SIM data-plan sizing calculator.
- Evidence-based operating envelope, provisional rating, and qualification
  targets derived from one-minute through two-hour laboratory tests.
- Hardware-aware ESP32 + A7670E operating specification.
- Repeatable ten-minute workload baseline with pass/review/fail limits.
- Lab Passed, Pilot Ready, and Production Candidate qualification levels.

### Changed

- Updated the public configuration template with the lower-socket-pressure
  profile used for reliability testing.
- Replaced the earlier idealized README result with the latest transparent
  30-minute WebREPL-disabled result.

## [1.0.0] - 2026-07-22

### Added

- Stable TCP/JSON ingestion on port 5005 with immediate acknowledgement.
- Bounded asynchronous MQTT publishing over A7670 LTE to AWS IoT Core.
- Priority and latest-value coalescing behavior during MQTT overload.
- Multi-rate fast, slow, event, and diagnostic telemetry classes.
- Device management, REST APIs, local industrial dashboard, and logs.
- Wi-Fi, HTTP, LTE, MQTT, memory, and crash-recovery supervision.
- PC workload, concept-comparison, and reliability test scripts.
- DynamoDB data-flow documentation and sanitized configuration templates.

### Security

- Excluded certificates, private keys, credentials, runtime logs, and local
  deployment configuration from the public repository.
