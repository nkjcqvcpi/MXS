# MXS 0.2.5 release readiness

## Scope and provenance

- Validation date: 2026-07-16.
- Local protocol sources: `Legacy-SW` at `2ef9cc586f6fa7694a81f3e784d23d738e1cd8df` and `Legacy-Documentation` at `8b382f74e0d72e93c43369bbe136cd23bbe38836`.
- Validation is restricted to `/dev/tty.usbmodem2101`. No destructive command, soak test, push, tag, or publication operation ran.
- `uv.lock` is intentionally ignored and excluded from the release commit.

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

## Exact validation results

| Gate | Command and result |
|---|---|
| Dependency synchronization | `uv sync`: pass, 20 packages resolved and MXS 0.2.5 installed in that validation environment |
| Formatting | `uv run ruff format .`: pass, 55 files unchanged |
| Lint | `uv run ruff check .`: pass, no errors |
| Types | `uv run pyright`: pass, 0 errors, 0 warnings, 0 information messages |
| Real-device pytest | `MXS_TEST_PORT=/dev/tty.usbmodem2101 uv run pytest -x --cov=mxs --cov-report=term-missing --cov-fail-under=90`: 51 passed in 223.12 seconds |
| Aggregate coverage | Pass, 90.05% |
| API parity | `uv run python scripts/check_api_parity.py`: pass, every public header method has explicit evidence and a directly referenced API path |
| Distribution | `uv build`: pass, `mxs-0.2.5.tar.gz` (101148 bytes) and `mxs-0.2.5-py3-none-any.whl` (72044 bytes) |
| Source archive | Pass, neither read-only Legacy submodule occurs in either distribution artifact |

The first coverage attempt passed all 50 then-current tests but reached only 87.14%, so no release action followed. Source-backed mutations of packets captured from the live device replaced the lost decoder coverage; the final 51-test command above is the successful release gate.

## Hardware acceptance and restoration

- Identity, capabilities, automatic baud detection, explicit 115200 and 921600 transitions, 100 RF frames, 100 IQ frames, 512 asynchronous IQ frames, supported application messages, five-second recording, and five reopen cycles passed.
- Opening-time raw callback, wire recorder, decoder, serial, terminated-worker, blocked-callback, and candidate-cleanup failures were detected before `OPEN` could overwrite them.
- All three normal output pairs enforced pre-transmission exclusion and post-ACK verification. Every debug pair was called directly and returned either supported behavior or the typed Annapurna firmware rejection.
- Unsupported positional and keyword forms raised `UnsupportedFirmwareError` without changing transmitted-byte counts. Destructive methods stopped at their disabled guards and were never executed.
- Protocol framing, decoding, malformed input, and alternate content-ID tests used packets captured from this device during the test session. Discovery used the actual pySerial port list.
- Final restoration verified profile ID `0`, all eight supported outputs disabled, 115200 baud, `STOP`, PING ready, and no thread whose name starts with `mxs-`.
