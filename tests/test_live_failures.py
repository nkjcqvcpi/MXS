"""Short failure-path tests driven by real serial traffic."""

import inspect
import threading
from contextlib import suppress
from typing import Never

import pytest
import serial

from mxs import X4M200, X4Config
from mxs.constants import DeviceState, SensorMode
from mxs.errors import BaudDetectionError, InvalidDeviceStateError, WorkerTerminatedError
from mxs.interfaces.core import Interface
from mxs.session import DeviceSession
from mxs.transport import SerialWorker, WireChunk


@pytest.mark.hardware
@pytest.mark.stateful
def test_real_rx_callback_failure_promotes_session_error(device_port: str) -> None:
    called = threading.Event()
    failure = RuntimeError("real RX callback failure")

    def fail_on_rx(_chunk: bytes) -> None:
        called.set()
        raise failure

    session = DeviceSession(device_port, 115200, raw_chunk_callback=fail_on_rx)
    try:
        with pytest.raises(RuntimeError, match="real RX callback failure"):
            session.open()
        assert called.wait(2.0)
        assert session.state is DeviceState.CLOSED
        assert session.worker is None
    finally:
        with suppress(BaseException):
            session.close()


@pytest.mark.hardware
@pytest.mark.stateful
def test_opening_wire_recorder_failure_is_fatal(device_port: str) -> None:
    def fail_on_wire(_chunk: WireChunk) -> None:
        raise RuntimeError("opening wire recorder failure")

    session = DeviceSession(device_port, 115200, wire_chunk_callback=fail_on_wire)
    with pytest.raises(RuntimeError, match="opening wire recorder failure"):
        session.open()
    assert session.state is DeviceState.CLOSED
    assert session.worker is None


@pytest.mark.hardware
@pytest.mark.stateful
def test_opening_decoder_failure_is_fatal(
    device_port: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mxs.transport

    def fail_decode(_payload: bytes) -> Never:
        raise RuntimeError("opening decoder failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(mxs.transport, "decode_message", fail_decode)
        session = DeviceSession(device_port, 115200)
        with pytest.raises(RuntimeError, match="opening decoder failure"):
            session.open()
    assert session.state is DeviceState.CLOSED
    assert session.worker is None


@pytest.mark.hardware
@pytest.mark.stateful
def test_opening_serial_failure_is_fatal(device_port: str, monkeypatch: pytest.MonkeyPatch) -> None:
    original = SerialWorker._drain_requests  # pyright: ignore[reportPrivateUsage]
    raised = False

    def fail_after_real_open(self: SerialWorker, port: object) -> None:
        nonlocal raised
        if not raised:
            raised = True
            raise serial.SerialException("opening serial failure")
        original(self, port)  # type: ignore[arg-type]

    with monkeypatch.context() as scoped:
        scoped.setattr(SerialWorker, "_drain_requests", fail_after_real_open)
        session = DeviceSession(device_port, 115200)
        with pytest.raises(Exception, match="opening serial failure"):
            session.open()
    assert raised
    assert session.state is DeviceState.CLOSED
    assert session.worker is None


@pytest.mark.hardware
@pytest.mark.stateful
def test_terminated_serial_worker_cannot_become_open(device_port: str) -> None:
    session = DeviceSession(device_port, 115200)

    def terminate_on_real_rx(_chunk: bytes) -> None:
        assert session.worker is not None
        session.worker._stop.set()  # pyright: ignore[reportPrivateUsage]

    session.raw_chunk_callback = terminate_on_real_rx
    with pytest.raises(BaudDetectionError, match="termination requested unexpectedly"):
        session.open()
    assert session.state is DeviceState.CLOSED
    assert session.worker is None


@pytest.mark.hardware
@pytest.mark.stateful
@pytest.mark.timeout(30)
def test_blocked_opening_callback_retains_worker_until_cleanup(device_port: str) -> None:
    entered = threading.Event()
    release = threading.Event()

    def block_on_rx(_chunk: bytes) -> None:
        entered.set()
        assert release.wait(10.0)

    session = DeviceSession(device_port, 115200, raw_chunk_callback=block_on_rx)
    with pytest.raises(WorkerTerminatedError):
        session.open()
    assert entered.is_set()
    assert session.state is DeviceState.ERROR
    assert session.worker is not None and session.worker.owned_workers_alive
    release.set()
    session.close()
    assert session.state is DeviceState.CLOSED and session.worker is None


@pytest.mark.hardware
@pytest.mark.stateful
def test_baud_candidate_returns_cleanup_error_after_live_workers_stop(
    device_port: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = DeviceSession(device_port, 115200)
    session.open()
    worker = session.worker
    assert worker is not None
    original_close = worker.close
    failure = RuntimeError("cleanup failed after termination")

    def fail_after_close(timeout: float = 3.0) -> None:
        original_close(timeout)
        raise failure

    monkeypatch.setattr(worker, "close", fail_after_close)
    assert session._close_candidate(worker) is failure  # pyright: ignore[reportPrivateUsage]
    assert session.state is DeviceState.CLOSED and session.worker is None


def test_closed_session_invariants_and_operation_lock_structure(device_port: str) -> None:
    device = X4M200(port=device_port)
    with pytest.raises(InvalidDeviceStateError):
        device.configure(X4Config())
    with pytest.raises(InvalidDeviceStateError):
        device.read_frame()
    with pytest.raises(InvalidDeviceStateError):
        device.recover()
    with pytest.raises(ValueError):
        X4M200(port=device_port, baudrate=9600)
    source = inspect.getsource(Interface._execute)  # pyright: ignore[reportPrivateUsage]
    assert "with self._session.operation_lock" in source


@pytest.mark.hardware
def test_filesystem_and_structured_commands_share_operation_lock(device_port: str) -> None:
    with X4M200(port=device_port) as device:
        assert device.filesystem._filesystem_lock is device._session.operation_lock  # pyright: ignore[reportPrivateUsage]
        entered = threading.Event()
        finished = threading.Event()

        def query() -> None:
            entered.set()
            device.profile.get_sensor_mode()
            finished.set()

        with device._session.operation_lock:  # pyright: ignore[reportPrivateUsage]
            thread = threading.Thread(target=query)
            thread.start()
            assert entered.wait(1.0)
            assert not finished.wait(0.05)
        thread.join(2.0)
        assert finished.is_set()
        assert device.profile.get_sensor_mode() is SensorMode.STOP
