# x4cir

`x4cir` acquires raw RF and downconverted baseband IQ CIR frames from an X4M200
using a native Apple Silicon, pure-Python MCP implementation. It has no
ModuleConnector, SWIG, CFFI, `ctypes`, Rosetta, or compiled Novelda dependency.

## Install

```bash
uv sync
```

## Inspect and capture

```bash
uv run x4cir ports
uv run x4cir sniff --port /dev/tty.usbmodem2101 --baud auto --seconds 5 --hex
uv run x4cir probe --port /dev/tty.usbmodem2101 --baud auto
uv run x4cir capture --port /dev/tty.usbmodem2101 --mode rf --frames 100 --output /tmp/rf.npz
uv run x4cir capture --port /dev/tty.usbmodem2101 --mode iq --frames 100 --output /tmp/iq.npz
uv run x4cir stream --port /dev/tty.usbmodem2101 --mode iq --stats
uv run x4cir record-wire --port /dev/tty.usbmodem2101 --duration 10 --output /tmp/session.mcpbin
```

The explicit lifecycle is `open`, `configure`, `start`, consume frames, `stop`,
and `close`. `configure()` leaves FPS at zero. `start()` applies the configured
FPS and waits for the first frame.

```python
from x4cir import X4Config, X4M200

with X4M200(port="/dev/tty.usbmodem2101", baudrate="auto") as radar:
    radar.configure(X4Config(downconversion=True, fps=17.0))
    radar.start()
    frame = radar.read_frame(timeout=2.0)
    print(frame.samples.dtype, frame.samples.shape)
```

The async facade shares the same worker and protocol implementation:

```python
async with AsyncX4M200(port=port) as radar:
    await radar.configure(X4Config())
    await radar.start()
    frame = await radar.read_frame(timeout=2.0)
```

## Replay and recovery

`x4cir.recording.replay_wire()` yields raw chunks from `.mcpbin` captures for
offline parser tests. If a command times out or a device disconnects, close the
session, confirm that no process owns the serial device, and create a new
session. See `docs/hardware-debugging.md` for the bring-up sequence.

Protocol provenance and source discrepancies are documented in
`docs/source-map.md` and `docs/protocol-notes.md`.

