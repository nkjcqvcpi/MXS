# MXS 0.2.3 release readiness

## Scope and provenance

- Validation date: 2026-07-15.
- Repository HEAD during validation: `396dd6c9252f17bcaf6ba9584e4651ef6129b057`.
- The 0.2.3 implementation is an uncommitted working-tree change, so no distinct final commit SHA exists yet.
- Local protocol sources: `Legacy-SW` at `2ef9cc586f6fa7694a81f3e784d23d738e1cd8df` and `Legacy-Documentation` at `8b382f74e0d72e93c43369bbe136cd23bbe38836`.
- No submodule file was modified. No destructive command, long soak, push, tag, or publish operation was run.

## Tested hardware

| Field | Result |
|---|---|
| Port | `/dev/tty.usbmodem2101`, character device and unoccupied at preflight |
| Item number | `000167-007` |
| Order code | `X4M200` |
| Firmware ID | `Annapurna` |
| Version | `1.6.6` |
| Build | `1.6.6+0.sha.039b0b3c581a0087885a2a1ed627d00a6d1df05e` |
| Serial number | `100000128815` |
| Version list | `Annapurna:1.6.6;XEP:3.4.6;X4C51:2.0.0:DSPlibs-target:1.6.7` |

## Gate results

| Gate | Exact result |
|---|---|
| Dependency synchronization | Pass, `uv sync`, 16 resolved packages in that validation environment |
| Source Ruff format/check and strict Pyright | Pass, 47 files unchanged, no lint errors, 0 type errors |
| API parity generation and audit | Pass, all public `X4M200.hpp` and `XEP.hpp` methods classified |
| Real-device pytest | Pass, 10 tests in 71.74 seconds |
| Identity and protocol | Pass, automatic 115200 detection, PING, seven required system fields, STOP sensor mode, and profile ID |
| Baudrate | Pass, explicit 115200 and 921600 opens plus verified transitions in both directions; restored to 115200 |
| Raw acquisition | Pass, 100 RF `float32` and 100 IQ `complex64` frames at 17 FPS; consistent shapes, ordered counters, zero gaps, zero CRC errors, clean STOP |
| Async acquisition | Pass, 512 IQ frames at 17 FPS; ordered counters, zero gaps, CRC errors, drops, or queue overflows; no remaining MXS thread |
| Messages and outputs | Pass, real sleep, respiration, and baseband-IQ messages from respiration profile 2; IQ/AP exclusivity queried from the device |
| Recording | Pass, five seconds; RX and TX records, ordered nonzero monotonic timestamps, clean-close marker, successful replay, RX-only raw callback |
| Reopen | Pass, five open, PING, close cycles with no remaining MXS thread |
| Unsupported APIs | Pass, all listed calls raised `UnsupportedFirmwareError` with unchanged transmitted-byte counts |
| Safety | Pass, disabled gates and STREAMING state rejection stopped every tested unsafe operation before destructive transmission |
| Source and wheel build | Pass, `mxs-0.2.3.tar.gz` (91 KiB) and `mxs-0.2.3-py3-none-any.whl` (69 KiB) |
| Distribution contents | Pass, neither read-only Legacy submodule is present in the source archive |

All executable release gates pass. The only intentionally unresolved release-administration item is the final commit SHA: the working tree must be committed before such a SHA exists. No commit, push, tag, or publication was performed.
