import pytest

from x4cir import X4M200, X4Config


@pytest.mark.hardware
def test_stop_manual_and_initialization() -> None:
    with X4M200() as radar:
        radar.configure(X4Config())
        assert radar.statistics().ack_count >= 13
