import pytest

from x4cir.session import DeviceSession


@pytest.mark.hardware
def test_passive_probe_sleep_stream() -> None:
    session = DeviceSession("/dev/tty.usbmodem2101", "auto")
    try:
        session.open()
        assert session.detected_baudrate in (115200, 921600)
        assert session.router.valid_packet_count > 0
        assert session.statistics().crc_errors == 0
    finally:
        session.close_passive()
