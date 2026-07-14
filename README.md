# MXS

MXS is a modern, unofficial, pure-Python SDK for the Novelda XeThru X4M200. It implements MCP framing, typed replies, raw RF and IQ acquisition, application messages, XEP/X4Driver configuration, bounded message delivery, recording, and optional NumPy/SciPy processing. MXS does not load ModuleConnector, SWIG, CFFI, `ctypes`, Rosetta, or a compiled Novelda library. NumPy and SciPy use their normal optimized distributions.

## Install

Python 3.14 or newer is required.

```bash
uv sync --locked
uv run mxs ports
```

MXS supports macOS and other platforms on which pySerial can open the module. `X4M200(port=None)` selects one unambiguous XeThru candidate. Pass a device path when more than one candidate is present.

## Acquisition

The 0.1 lifecycle and data contracts remain stable. Raw RF arrays are `float32`; downconverted IQ arrays are `complex64`, with I samples followed by Q samples on the wire.

```python
from mxs import X4Config, X4M200

with X4M200(port="/dev/tty.usbmodem2101") as radar:
    radar.configure(X4Config(downconversion=True, fps=17.0))
    radar.start()
    frame = radar.read_frame(timeout=2.0)
    print(frame.samples.dtype, frame.samples.shape)
```

The serial thread owns pySerial and performs only reads, writes, framing, classification, and bounded enqueue. A prioritized decoder handles control messages before ordered stream payloads. Recording, async delivery, user consumption, and SciPy processing run outside both workers.

## Structured SDK

The synchronous device exposes `module`, `profile`, `outputs`, `messages`, `xep`, `gpio`, `noisemap`, `parameters`, `filesystem`, and `unsafe`. Common methods are also forwarded from `X4M200` for migration convenience.

```python
with X4M200(port=port) as radar:
    print(radar.module.get_system_info(3))
    print(radar.profile.get_sensor_mode())
    print(radar.xep.x4driver_get_frame_area())
    message = radar.messages.sleep.read(timeout=2.0)
```

Each message topic supports `peek()`, `read()`, `iter()`, `subscribe()`, `read_async()`, and async iteration. Queue policies are `error`, `drop_oldest`, `drop_newest`, and `block_with_timeout`; drops are explicit and counted.

## Async API

`AsyncX4M200` preserves the 0.1 API. Frame delivery uses `loop.call_soon_threadsafe` and a bounded event-loop queue, not timed polling.

```python
from mxs import AsyncX4M200

async with AsyncX4M200(port=port) as radar:
    await radar.configure(X4Config())
    await radar.start()
    frame = await radar.read_frame(timeout=2.0)
```

## Recording and processing

`.mcpbin` recording uses a bounded writer queue, monotonic timestamps, RX/TX direction fields, metadata, a clean-close marker, and truncated-file recovery. Parsed-message recording stores versioned JSONL metadata and independent `.npy` arrays; `mxs record-messages` and `mxs replay-messages` expose that format. Chunked CIR recording writes independently readable NumPy files. `mxs.recording.legacy` reads the self-delimiting baseband IQ and amplitude/phase formats documented by XTAN-05; it rejects legacy formats whose record envelope is not sufficiently specified.

Host processing is opt-in. `mxs.processing` provides IQ/amplitude/phase conversion, phase unwrap, range axes, normalization, filtering, spectra, resampling, peaks, analytic signals, and an ordered bounded thread/process pipeline. Acquisition never applies filters automatically.

## Safety and firmware

Unsafe namespaces require operation-specific environment gates. Factory reset, bootloader entry, filesystem mutation/formatting, raw register writes, frame injection, and manufacturing tests are disabled by default. See [hardware safety](docs/hardware-safety.md) before enabling any gate.

An ACK timeout marks the session desynchronized, closes the transport, and rejects further commands. Call `recover()` to reopen and restore STOP state. A disconnect wakes pending consumers; close and reopen the same object to rebuild workers and subscriptions.

Firmware-dependent behavior is conservative. Unknown support is never reported as supported, and functions with no local producer or a negative probe raise `UnsupportedFirmwareError`. The tested firmware matrix is in [firmware capabilities](docs/firmware-capabilities.md).

## Development

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest -m "not hardware and not soak and not unsafe" --cov=mxs
uv build
```

Protocol provenance is recorded in [source map](docs/source-map.md), [protocol notes](docs/protocol-notes.md), and [upstream sources](docs/upstream-sources.md). Migration details are in [0.1 to 0.2 migration](docs/migration-0.1-to-0.2.md).
