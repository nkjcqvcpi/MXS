# Migrating from 0.1 to 0.2

Use `mxs` for imports and command-line execution. The `X4M200`, `AsyncX4M200`, `X4Config`, `CirFrame`, acquisition lifecycle, RF `float32` layout, and IQ `complex64` layout are unchanged.

`X4M200()` no longer hardcodes a macOS device path. It discovers one unambiguous candidate or raises `DeviceNotFoundError` or `AmbiguousDeviceError`.

Reply parsing is intentionally stricter. Long replies interpret their length field as an element count and validate datatype size, content ID, info, count, and optional trailing size. Malformed replies that 0.1 accepted now raise `MalformedMessageError` or `ReplyMismatchError`.

An ACK-only command timeout closes and desynchronizes the session. Subsequent commands raise `SessionDesynchronizedError` until `recover()` is called. This prevents a delayed ACK from satisfying another command.
