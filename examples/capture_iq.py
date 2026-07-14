from pathlib import Path

from x4cir import X4M200, X4Config
from x4cir.recording import save_npz

config = X4Config(downconversion=True)
with X4M200() as radar:
    radar.configure(config)
    radar.start()
    frames = [radar.read_frame(timeout=2.0) for _ in range(100)]
    baudrate = radar.detected_baudrate
if baudrate is None:
    raise RuntimeError("baudrate unavailable")
save_npz(Path("iq.npz"), frames, config, port="/dev/tty.usbmodem2101", baudrate=baudrate)
