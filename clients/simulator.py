"""Replaceable industrial pump telemetry source."""

import urandom


_energy_kwh = 1000.0


def _random_float(minimum, maximum, decimals):
    # getrandbits avoids floating-point assumptions in urandom implementations.
    fraction = urandom.getrandbits(24) / 16777215.0
    return round(minimum + (maximum - minimum) * fraction, decimals)


def read_telemetry():
    """Return only measurements, independent of transport and message metadata."""
    global _energy_kwh
    temperature = _random_float(28.0, 45.0, 1)
    vibration = _random_float(0.10, 1.20, 2)
    current = _random_float(1.5, 6.0, 2)
    voltage = _random_float(220.0, 240.0, 1)
    humidity = _random_float(35.0, 70.0, 1)

    # Approximate energy increment for a three-phase industrial load sample.
    _energy_kwh += _random_float(0.02, 0.15, 3)

    return {
        "temperature_c": temperature,
        "vibration_rms_mm_s": vibration,
        "current_a": current,
        "voltage_v": voltage,
        "humidity_pct": humidity,
        "energy_kwh": round(_energy_kwh, 3),
        "running": True,
    }


def status_for(telemetry):
    if telemetry["temperature_c"] > 42.0 or telemetry["vibration_rms_mm_s"] > 1.0:
        return "WARNING"
    return "RUNNING"

