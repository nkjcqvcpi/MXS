# Hardware Debugging

Check ownership before opening the debug device:

```bash
ls -l /dev/tty.usbmodem2101
lsof /dev/tty.usbmodem2101 || true
```

Start with passive observation:

```bash
uv run x4cir sniff --port /dev/tty.usbmodem2101 --baud auto --seconds 5 --hex
uv run x4cir probe --port /dev/tty.usbmodem2101 --baud auto
```

If communication fails after a baud transition, close every process holding
the device and probe again with automatic detection. If streaming fails, send
STOP, enter MANUAL mode, and configure from a new session. USB disconnects are
reported to readers and require a new session after reconnection.

Hardware and soak tests are explicit:

```bash
X4CIR_HARDWARE=1 uv run pytest -m hardware
X4CIR_HARDWARE=1 X4CIR_SOAK_SECONDS=1800 uv run pytest -m soak
```

