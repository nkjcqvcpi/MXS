# Migration from MXS 0.2.2 to 0.2.3

MXS 0.2.3 makes unsupported firmware behavior explicit. Extended respiration output, periodic noisemap storage, undocumented XEP normalization, phase-noise, decimation, number-format and legacy-output controls, and X4Driver I2C access now raise `UnsupportedFirmwareError` before any serial transmission. Callers that previously treated these methods as speculative probes should catch that exception or consult `DeviceCapabilities`.

The `serial_factory` constructor parameter has been removed from `X4M200`, `AsyncX4M200`, `DeviceSession`, and `SerialWorker`. It was a test injection surface rather than a supported device abstraction. Integrations must pass a real serial device path.

Shutdown now reports `CLOSED` only after the serial, decoder, callback, and async bridge workers terminate. If an owned transport worker remains alive, the session enters `ERROR`, retains its worker reference for diagnosis, and rejects reopen. This is stricter than 0.2.2, which could hide an orphan behind a closed state.

Unsafe operations now hold one operation lock across the environment gate, live sensor-mode query, and destructive command. Profile loading, sensor-mode changes, configure, start, stop, recover, and baud transitions use the same lock. Applications should not rely on concurrent state-changing calls being interleaved.

Output control no longer trusts process-local history. MXS queries all members of a mutually exclusive group, sends the requested change, and resynchronizes only after its ACK. Profile load, reset, close, and reopen clear cached output state.

The pytest contract is intentionally hardware-only. Every collected test depends on the session-scoped fixture for `/dev/tty.usbmodem2101`; missing, occupied, unidentified, or unresponsive hardware is an error. Fake serial devices, synthetic replies, property-only packet tests, checked-in golden traffic, coverage thresholds, and the 1,800-second soak were removed.
