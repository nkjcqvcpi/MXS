# MXS 0.2.6 release readiness

## Scope and provenance

- Validation date: 2026-07-16.
- Local protocol sources: `Legacy-SW` at `2ef9cc586f6fa7694a81f3e784d23d738e1cd8df` and `Legacy-Documentation` at `8b382f74e0d72e93c43369bbe136cd23bbe38836`.
- Validation is restricted to `/dev/tty.usbmodem2101`. No destructive command, soak test, push, tag, or publication operation is permitted.
- `uv.lock` is intentionally local, ignored, and excluded from version control. Validation uses `uv sync`; exact resolved versions are recorded from `uv pip freeze`. A clean checkout may resolve newer compatible dependencies.

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

## Validation results

- Validation base commit: `adf65fb1190661b75eb7d0c979353d5a3f3cd38a`. The final release commit SHA is available from Git after the validated tree is committed.
- `uv run ruff format .`: passed; 55 files were already formatted.
- `uv run ruff check .`: passed.
- `uv run pyright`: passed with 0 errors, warnings, or informational diagnostics.
- `MXS_TEST_PORT=/dev/tty.usbmodem2101 uv run pytest -x --cov=mxs --cov-report=term-missing --cov-fail-under=90`: 51 passed in 174.92 seconds; 90.50% coverage.
- `uv run python scripts/check_api_parity.py`: passed; every public `X4M200.hpp` and `XEP.hpp` method is classified with exact evidence.
- `uv build`: produced `dist/mxs-0.2.6.tar.gz` (106003 bytes) and `dist/mxs-0.2.6-py3-none-any.whl` (72931 bytes).
- `git diff --check`: passed.
- Final hardware readback: order code `X4M200`, profile `0`, every normal output `0`, every supported debug output `0`, extended-respiration debug typed rejection unchanged, STOP, 115200 baud, PING ready, no `mxs-*` threads, and serial port unoccupied after close.

## Resolved validation environment

`rm -f uv.lock && uv sync` resolved the following local environment. `uv pip freeze > /tmp/mxs-0.2.6-freeze.txt` captured the same set; its SHA-256 is `e36078c58683394ca1578a9e6d92a197bc735b34ae7ba1c58f74b4225881a2a6`.

```text
coverage==7.15.2
hypothesis==6.156.6
iniconfig==2.3.0
-e file:///Users/houtonglei/Projects/X4M200
nodeenv==1.10.0
numpy==2.5.1
packaging==26.2
pluggy==1.6.0
pygments==2.20.0
pyright==1.1.411
pyserial==3.5
pytest==9.1.1
pytest-asyncio==1.4.0
pytest-cov==7.1.0
pytest-timeout==2.4.0
ruff==0.15.21
scipy==1.18.0
sortedcontainers==2.4.0
typing-extensions==4.16.0
```

## Hardware findings

- Reset uses the target's 500 ms delay with a 600 ms host wait. Both public reset paths reconnect, reprobe both supported baudrates, and require PING, profile `0`, and STOP.
- User callbacks are deferred until candidate acceptance changes the state to `OPEN`; live callback re-entry and RX arrival during the acceptance barrier complete without deadlock or lost health checks.
- Producer-specific content IDs were verified from local target code and live replies. No speculative alternate identifier remains.
- Every normal and readable debug output state is captured at preflight and verified at teardown. The extended-respiration debug namespace raises `UnsupportedFirmwareError` before transmission.
- An idempotent debug-output set command did not acknowledge on Annapurna 1.6.6 and temporarily re-enumerated USB during review. Release tests therefore read and restore baseline debug values but do not alter them when no restoration is required.
- Optional reads use separate sessions. The parameter-file getter produced a typed ACK mismatch; SPI, PIF, XIF, and SPI block reads returned `0`, `8`, `0`, and `b'\x00'`.
