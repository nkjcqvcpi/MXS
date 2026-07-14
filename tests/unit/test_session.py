import threading

import pytest

from mxs import X4M200, X4Config
from mxs.constants import DeviceState
from mxs.errors import (
    CommandRejectedError,
    CommandTimeoutError,
    DeviceDisconnectedError,
    InvalidDeviceStateError,
    WorkerTerminatedError,
)
from mxs.session import DeviceSession
from mxs.transport import WireChunk
from tests.conftest import FakeSerialFactory


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
    assert not any(thread.name.startswith("mxs-fake") for thread in threading.enumerate())


def test_reopen_same_object_builds_fresh_workers_and_subscriptions() -> None:
    factory = FakeSerialFactory()
    radar = X4M200(port="fake", serial_factory=factory)
    radar.open()
    first_messages = radar.messages
    radar.close()
    radar.open()
    assert radar.messages is not first_messages
    radar.close()


def test_invalid_state_transitions() -> None:
    radar = X4M200(port="fake", serial_factory=FakeSerialFactory())
    with pytest.raises(InvalidDeviceStateError):
        radar.configure(X4Config())
    with pytest.raises(InvalidDeviceStateError):
        radar.read_frame()
    with pytest.raises(InvalidDeviceStateError):
        radar.recover()
    with pytest.raises(ValueError):
        X4M200(port="fake", baudrate=9600)


def test_high_baud_transition() -> None:
    factory = FakeSerialFactory()
    radar = X4M200(port="fake", baudrate=115200, serial_factory=factory)
    radar.open()
    with pytest.raises(ValueError):
        radar.module.set_baudrate(9600)
    radar.module.set_baudrate(115200)
    radar.switch_to_high_baudrate()
    assert radar.detected_baudrate == 921600
    assert factory.instances[0].baudrate == 921600
    radar.module.set_baudrate(115200)
    assert radar.detected_baudrate == 115200
    assert factory.instances[0].baudrate == 115200
    radar.close()


def test_timeout_stop_recover_preserves_desynchronized_state() -> None:
    factory = FakeSerialFactory(initial_stream=False)
    radar = X4M200(port="fake", baudrate=115200, command_timeout=0.05, serial_factory=factory)
    radar.open()
    factory.instances[0].suppress_next_response = True
    with pytest.raises(CommandTimeoutError):
        radar.profile.get_sensor_mode()
    assert radar.state is DeviceState.DESYNCHRONIZED
    radar.stop()
    assert radar.state is DeviceState.DESYNCHRONIZED
    radar.recover()
    assert radar.state is DeviceState.STOPPED
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


def test_transport_records_rx_and_tx_at_io_boundary() -> None:
    chunks: list[WireChunk] = []
    radar = X4M200(
        port="fake", serial_factory=FakeSerialFactory(), wire_chunk_callback=chunks.append
    )
    radar.open()
    radar.configure(X4Config())
    radar.close()
    assert {chunk.direction for chunk in chunks} == {"rx", "tx"}
    assert all(chunk.timestamp_monotonic_ns > 0 and chunk.data for chunk in chunks)


def test_start_frame_timeout_read_timeout_and_passive_close() -> None:
    session = DeviceSession(
        "fake", 115200, serial_factory=FakeSerialFactory(emit_start_frame=False)
    )
    session.open()
    session.configure(X4Config())
    with pytest.raises(WorkerTerminatedError, match="no CIR frame"):
        session.start(first_frame_timeout=0.01)
    session.close()

    radar = X4M200(port="fake", serial_factory=FakeSerialFactory(data_before_ack=False))
    radar.open()
    radar.configure(X4Config())
    radar.start()
    radar.read_frame(1)
    with pytest.raises(TimeoutError):
        radar.read_frame(0.001)
    radar.close()

    passive = DeviceSession("fake", 115200, serial_factory=FakeSerialFactory())
    passive.open()
    passive.close_passive()
