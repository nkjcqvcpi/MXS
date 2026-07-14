import threading

import pytest

from tests.conftest import FakeSerialFactory
from x4cir import X4M200, X4Config
from x4cir.constants import DeviceState
from x4cir.errors import CommandRejectedError, DeviceDisconnectedError, InvalidDeviceStateError


def test_fake_serial_full_lifecycle_and_partial_io() -> None:
    factory = FakeSerialFactory(partial_read=3, partial_write=2)
    radar = X4M200(port="fake", baudrate="auto", serial_factory=factory)
    radar.open()
    radar.configure(X4Config())
    radar.start()
    frame = radar.read_frame(timeout=1.0)
    assert frame.frame_counter == 42
    assert frame.samples.tolist() == [1.0, 2.0, 3.0, 4.0]
    radar.stop()
    radar.close()
    radar.close()
    assert not any(thread.name.startswith("x4cir-fake") for thread in threading.enumerate())


def test_invalid_state_transitions() -> None:
    radar = X4M200(port="fake", serial_factory=FakeSerialFactory())
    with pytest.raises(InvalidDeviceStateError):
        radar.configure(X4Config())
    with pytest.raises(InvalidDeviceStateError):
        radar.read_frame()


def test_high_baud_transition() -> None:
    factory = FakeSerialFactory()
    radar = X4M200(port="fake", baudrate=115200, serial_factory=factory)
    radar.open()
    radar.switch_to_high_baudrate()
    assert radar.detected_baudrate == 921600
    assert factory.instances[0].baudrate == 921600
    radar.close()


def test_firmware_error_and_disconnect_propagate() -> None:
    factory = FakeSerialFactory()
    radar = X4M200(port="fake", serial_factory=factory)
    radar.open()
    factory.instances[0].reject_next = True
    with pytest.raises(CommandRejectedError):
        radar.configure(X4Config())
    radar.close()

    factory = FakeSerialFactory()
    radar = X4M200(port="fake", serial_factory=factory)
    radar.open()
    radar.configure(X4Config())
    radar.start()
    radar.read_frame(timeout=1.0)
    factory.instances[0].disconnected = True
    with pytest.raises(DeviceDisconnectedError):
        radar.read_frame(timeout=1.0)
    assert radar.state is DeviceState.ERROR
    radar.close()
