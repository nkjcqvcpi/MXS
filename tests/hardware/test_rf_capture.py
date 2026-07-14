import numpy as np
import pytest

from x4cir import X4M200, X4Config


@pytest.mark.hardware
def test_rf_capture() -> None:
    with X4M200() as radar:
        radar.configure(X4Config(downconversion=False))
        radar.start()
        frames = [radar.read_frame(timeout=2.0) for _ in range(100)]
    assert all(frame.samples.dtype == np.float32 for frame in frames)
    assert len({frame.samples.size for frame in frames}) == 1
    assert all(np.isfinite(frame.samples).any() for frame in frames)
    assert any(np.any(frame.samples != 0) for frame in frames)
    assert sum(frame.sequence_gap for frame in frames) == 0
