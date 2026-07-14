import time
from pathlib import Path

from mxs.recording import WireRecorder
from mxs.session import DeviceSession

port = "/dev/tty.usbmodem2101"
with WireRecorder(Path("capture.mcpbin"), port, 115200) as recorder:
    session = DeviceSession(port, raw_chunk_callback=recorder.write_chunk)
    try:
        session.open()
        time.sleep(5)
    finally:
        session.close_passive()
