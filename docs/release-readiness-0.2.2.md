# MXS 0.2.2 release readiness

## Review scope

- Workspace commit reviewed: `83e0d93a670bdc7f9619512cef60005bfb45bb96`.
- Legacy-SW commit: `2ef9cc586f6fa7694a81f3e784d23d738e1cd8df`.
- Legacy-Documentation commit: `8b382f74e0d72e93c43369bbe136cd23bbe38836`.
- Source, lock-file, and fallback versions are `0.2.2`.
- No destructive hardware operation and no long soak test was run.

## Offline gates

| Gate | Result |
|---|---|
| `uv sync --locked` | Pass |
| Ruff format | Pass, 75 files unchanged on the final run |
| Ruff check | Pass |
| Strict Pyright | Pass, zero errors and warnings |
| Offline tests | Pass, 105 passed and 7 hardware tests deselected |
| Coverage | Pass, 92.35% aggregate |
| Source and wheel build | Pass, `mxs-0.2.2.tar.gz` and `mxs-0.2.2-py3-none-any.whl` |

The regression suite covers isolated baud candidates, exception-safe shutdown, failed-recorder close behavior, RX-only compatibility callbacks, firmware-mode unsafe guards, atomic filesystem transactions, and cancelled blocking-policy waiters.

## Hardware gates

Hardware validation used `/dev/tty.usbmodem2101` on 2026-07-14. `lsof` reported no owner.

| Gate | Result |
|---|---|
| Automatic detection | Pass, detected 115200 |
| Explicit opens | Pass at 115200 and 921600 |
| Baud transitions | Pass in both directions, with PING after each transition |
| RF acquisition | Pass, 100 ordered `float32` frames, shape 846, zero gaps and CRC errors |
| IQ acquisition | Pass, 100 ordered `complex64` frames, shape 107, zero gaps and CRC errors |
| Async acquisition | Pass, 512 ordered frames, zero gaps and CRC errors, no remaining MXS threads |
| Recording | Pass, 10 seconds, 227 RX and 19 TX records, ordered nonzero timestamps, clean marker, successful replay, RX-only legacy callback |
| Reopen | Pass, five open/PING/close cycles plus configure/capture/close/reopen/PING |

The maximum frame queue high-water mark was 1 in RF, IQ, and async validation. The recording queue high-water mark was 1.

## System information

| Field | Result |
|---|---|
| Item number | `000167-007` |
| Order code | `X4M200` |
| Firmware ID | `Annapurna` |
| Version | `1.6.6` |
| Build | `1.6.6+0.sha.039b0b3c581a0087885a2a1ed627d00a6d1df05e` |
| Serial number | `100000128815` |
| Version list `0x07` | `Annapurna:1.6.6;XEP:3.4.6;X4C51:2.0.0:DSPlibs-target:1.6.7` |
| Sensor mode before tests | STOP (`0x13`) |
| Profile ID before tests | Unknown/unloaded (`0x00000000`) |

## Remaining blocker

Extended-respiration decoding is not implemented. The local sources declare `XTS_ID_RESP_STATUS_EXT` as `0x2375A16B`, but the complete workspace contains no target producer, host parser, data structure, fixture, or example that defines its payload. The connected firmware returned content ID zero when that output control was queried, so hardware did not provide authoritative layout evidence.

Implementing a field layout from the identifier or by aliasing normal respiration would violate the plan's instruction not to guess. The same provenance limitation applies to periodic noisemap storage, several XEP controls, and X4Driver I2C access, which remain explicit unsupported features.

MXS 0.2.2 is not release-ready under the stated gate because the extended-respiration requirement remains unresolved. The other listed offline and short-hardware gates pass.
