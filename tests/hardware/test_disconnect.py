import os

import pytest

from x4cir import X4M200, X4Config
from x4cir.errors import DeviceDisconnectedError


@pytest.mark.hardware
def test_physical_disconnect_propagates() -> None:
    if os.getenv("X4CIR_DISCONNECT") != "1":
        pytest.skip("set X4CIR_DISCONNECT=1 and disconnect the module during this test")
    radar = X4M200()
    try:
        radar.open()
        radar.configure(X4Config())
        radar.start()
        with pytest.raises(DeviceDisconnectedError):
            while True:
                radar.read_frame(timeout=5.0)
    finally:
        radar.close()
