# Migrating from MXS 0.2.5 to 0.2.6

MXS 0.2.6 preserves the public acquisition API but tightens reset, opening, and reply-validation behavior. `ModuleInterface.reset()` and `ProfileInterface.restore_profile(0)` now share one reset path: receive the ACK, close passively, wait 600 ms, retry opening under a bounded deadline, probe 115200 and 921600, require a ready PING and profile ID `0`, then set and verify STOP.

Baud-candidate acceptance now holds the serial submission barrier while it flushes prior decoder work, checks serial, decoder, callback, recorder, and candidate health, and changes `OPENING` to `OPEN`. User callbacks remain queued until that transition completes. A callback may call a device API after release without deadlocking against the session operation lock.

Reply expectations no longer accept identifiers inferred from request fields. Filesystem, sensor-mode, profile, GPIO-control, output-control, noisemap-control, and application replies use the producer's observed `0`; GPIO value uses `0x21`; system information uses `0x58`; X4 replies use their parameter IDs. Tests capture each real reply before changing only its content-ID field to verify rejection.

Optional getters are isolated by session. On Annapurna 1.6.6, the parameter-file request produced an ACK where a typed reply was required; SPI-register, PIF-register, XIF-register, and SPI block-read getters returned `0`, `8`, `0`, and `b'\x00'`, respectively.

`uv.lock` is intentionally local and ignored. Use `uv sync` for validation and `uv pip freeze` to record the resolved environment. A clean checkout may select newer versions allowed by the declared dependency constraints.
