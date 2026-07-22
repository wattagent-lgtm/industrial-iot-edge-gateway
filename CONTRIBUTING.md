# Contributing

Thank you for improving the Industrial IoT Edge Gateway.

## Before submitting a change

1. Create a focused branch from `main`.
2. Never commit Wi-Fi credentials, APNs with credentials, AWS certificates,
   private keys, device identifiers, or production IP addresses.
3. Keep the TCP server compatible with port 5005 and the
   `{"status":"OK"}` acknowledgement.
4. Prefer bounded allocations and MicroPython-compatible modules.
5. Run the repository checks locally where practical.

## Pull requests

Describe the problem, implementation, hardware used, test duration, message
rate, ACK result, memory range, and any observed restarts. Attach sanitized
logs only.

## Reporting defects

Use the bug report template. Include firmware version, board, modem variant,
network path, reproduction steps, and sanitized serial output.
