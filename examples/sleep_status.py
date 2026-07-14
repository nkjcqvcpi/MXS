from mxs import X4M200

with X4M200() as device:
    print(device.messages.sleep.read(timeout=5))
