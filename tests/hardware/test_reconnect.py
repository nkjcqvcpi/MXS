import threading

import pytest

from x4cir import X4M200, X4Config


@pytest.mark.hardware
@pytest.mark.timeout(300)
def test_ten_repeated_lifecycles() -> None:
    for _ in range(10):
        with X4M200() as radar:
            radar.configure(X4Config())
            radar.start()
            for _ in range(20):
                radar.read_frame(timeout=2.0)
            radar.stop()
    assert not any(thread.name.startswith("x4cir-") for thread in threading.enumerate())
