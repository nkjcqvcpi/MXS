import os
import resource
import time

import pytest

from x4cir import X4M200, X4Config


@pytest.mark.hardware
@pytest.mark.soak
@pytest.mark.timeout(1900)
def test_thirty_minute_soak() -> None:
    duration = float(os.getenv("X4CIR_SOAK_SECONDS", "1800"))
    started = time.monotonic()
    initial_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    received = 0
    with X4M200(frame_queue_size=256) as radar:
        radar.configure(X4Config())
        radar.start()
        while time.monotonic() - started < duration:
            radar.read_frame(timeout=2.0)
            received += 1
        stats = radar.statistics()
    final_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert received > duration * 10
    assert stats.crc_errors == 0
    assert stats.frame_counter_gaps == 0
    assert stats.consumer_drops == 0
    assert stats.queue_high_water_mark < 64
    assert final_memory - initial_memory < 128 * 1024
