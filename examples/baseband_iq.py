from mxs import X4M200, X4Config

with X4M200() as device:
    device.configure(X4Config(downconversion=True))
    device.start()
    print(device.read_frame(timeout=2).samples)
