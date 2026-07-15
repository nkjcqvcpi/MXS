# Hardware Debugging

Check ownership before opening the debug device:

```bash
ls -l /dev/tty.usbmodem2101
lsof /dev/tty.usbmodem2101 || true
```

Start with passive observation:

```bash
uv run mxs sniff --port /dev/tty.usbmodem2101 --baud auto --seconds 5 --hex
uv run mxs probe --port /dev/tty.usbmodem2101 --baud auto
```

If communication fails after a baud transition, close every process holding
the device and probe again with automatic detection. If streaming fails, send
STOP, enter MANUAL mode, and configure from a new session. USB disconnects are
reported to every pending reader. The same object may be closed and reopened
after the device re-enumerates. After any command timeout, call `recover()`; do not
send another command on the old transport.

Pytest always requires the fixed real device. It has no offline or soak selection:

```bash
PORT=/dev/tty.usbmodem2101
test -c "$PORT"
! lsof "$PORT" | grep -q .
MXS_TEST_PORT="$PORT" uv run pytest -x
```

Missing, busy, unidentified, or unresponsive hardware aborts the run. The unsafe tests verify only disabled gates and state rejection; they never send destructive commands.
