# MXS 0.2.4 release readiness

## Scope and provenance

- Validation date: 2026-07-15.
- Tested implementation commit: `3759460ab8de5b42a4b885a179db3b8909bb8b43`.
- Local protocol sources: `Legacy-SW` at `2ef9cc586f6fa7694a81f3e784d23d738e1cd8df` and `Legacy-Documentation` at `8b382f74e0d72e93c43369bbe136cd23bbe38836`.
- No submodule file was modified. No destructive command, long soak, push, tag, or publication operation ran.

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
| Dependency synchronization | `uv sync`: pass, 20 packages resolved and 19 checked in that validation environment |
| Formatting | `uv run ruff format .`: pass, 55 files unchanged |
| Lint | `uv run ruff check .`: pass, no errors |
| Types | `uv run pyright`: pass, 0 errors, 0 warnings, 0 information messages |
| Real-device pytest | `MXS_TEST_PORT=/dev/tty.usbmodem2101 uv run pytest -x --cov=mxs --cov-report=term-missing --cov-fail-under=90`: 62 passed in 149.32 seconds |
| Aggregate coverage | Pass, 90.11% |
| API parity | `uv run python scripts/check_api_parity.py`: pass, all public `X4M200.hpp` and `XEP.hpp` methods classified with existing pytest nodes |
| Distribution | `uv build`: pass, `mxs-0.2.4.tar.gz` (114648 bytes) and `mxs-0.2.4-py3-none-any.whl` (70571 bytes) |
| Source archive | Pass, neither read-only Legacy submodule occurs in the source archive |

## Hardware acceptance

- Identity, system information, automatic baud detection, explicit 115200 and 921600 opens, and transitions in both directions passed.
- Acquisition passed for 100 RF frames, 100 IQ frames, and 512 asynchronous IQ frames with ordered counters, zero CRC errors, and no queue overflow.
- Live sleep, respiration, baseband-IQ, output-control, GPIO, noisemap-control, parameter-read, filesystem-read, and safe X4Driver surfaces passed or returned the documented typed firmware rejection.
- All three exclusive output pairs rejected a conflicting enable before its transmission and resynchronized their live state.
- Five-second wire recording, truncation recovery, five reopen cycles, real callback failure, blocked-callback shutdown retention, and baud-candidate cleanup propagation passed.
- Every unsupported method raised `UnsupportedFirmwareError` without changing the transmitted-byte count. Every destructive method stopped at its disabled guard.
- Final verification observed 115200 baud, `STOP`, a valid X4M200 reply, and no thread whose name begins with `mxs-`.

The implementation commit satisfies all executable release gates. The tracked superproject worktree was clean after validation; pre-existing untracked content inside the two read-only submodules remained untouched.
