from mxs import X4M200, X4Config

with X4M200() as device:
    device.configure(X4Config())
    print("FPS", device.xep.x4driver_get_fps())
    print("area", device.xep.x4driver_get_frame_area())
    print("bins", device.xep.x4driver_get_frame_bin_count())
