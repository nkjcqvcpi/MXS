"""Short failure-path tests driven by real serial traffic."""

import inspect
import threading
import time
from contextlib import suppress
from typing import Never

import pytest
import serial

from mxs import X4M200, X4Config
from mxs.commands import build_ping
from mxs.constants import DeviceState, SensorMode
from mxs.errors import InvalidDeviceStateError
from mxs.interfaces.core import Interface
from mxs.session import DeviceSession
from mxs.transport import SerialWorker, WireChunk


@pytest.mark.hardware
def test_real_rx_callback_failure_promotes_session_error(device_port: str) -> None:
    called = threading.Event()
    failure = RuntimeError("real RX callback failure")
    states: list[DeviceState] = []
    session = DeviceSession(device_port, 115200)

    def fail_on_rx(_chunk: bytes) -> None:
        states.append(session.state)
        called.set()
        raise failure

    session.raw_chunk_callback = fail_on_rx
    try:
        session.open()
        assert called.wait(2.0)
        assert states == [DeviceState.OPEN]
        deadline = time.monotonic() + 1.0
        while session.state is DeviceState.OPEN and time.monotonic() < deadline:
            time.sleep(0.001)
        assert session.state is DeviceState.ERROR
    finally:
        with suppress(BaseException):
            session.close()


@pytest.mark.hardware
def test_opening_wire_recorder_failure_is_fatal(device_port: str) -> None:
    called = threading.Event()
    states: list[DeviceState] = []
    session = DeviceSession(device_port, 115200)

    def fail_on_wire(_chunk: WireChunk) -> None:
        states.append(session.state)
        called.set()
        raise RuntimeError("opening wire recorder failure")

    session.wire_chunk_callback = fail_on_wire
    try:
        session.open()
        assert called.wait(2.0)
        assert states == [DeviceState.OPEN]
        deadline = time.monotonic() + 1.0
        while session.state is DeviceState.OPEN and time.monotonic() < deadline:
            time.sleep(0.001)
        assert session.state is DeviceState.ERROR
    finally:
        with suppress(BaseException):
            session.close()


@pytest.mark.hardware
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
def test_opening_callback_can_reenter_device_api(device_port: str) -> None:
    entered = threading.Event()
    completed = threading.Event()
    failure: list[BaseException] = []
    observed: list[DeviceState] = []
    once = threading.Event()
    device: X4M200

    def reenter_on_rx(_chunk: bytes) -> None:
        if once.is_set():
            return
        once.set()
        observed.append(device.state)
        entered.set()
        try:
            assert device.module.ping().ready
        except BaseException as error:
            failure.append(error)
        finally:
            completed.set()

    device = X4M200(port=device_port, baudrate=115200, raw_chunk_callback=reenter_on_rx)
    try:
        device.open()
        assert entered.wait(1.0)
        assert completed.wait(2.0)
        assert observed == [DeviceState.OPEN]
        assert failure == []
    finally:
        device.close()


@pytest.mark.hardware
def test_new_rx_waits_behind_candidate_acceptance_barrier(
    device_port: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = DeviceSession._transition  # pyright: ignore[reportPrivateUsage]
    observed = threading.Event()

    def transition_with_live_rx(self: DeviceSession, state: DeviceState) -> None:
        original(self, state)
        if state is not DeviceState.OPEN or observed.is_set():
            return
        worker = self.worker
        assert worker is not None
        submitted = worker.decoder_worker._submitted  # pyright: ignore[reportPrivateUsage]
        received = self.statistics().bytes_received
        worker.send(build_ping())
        deadline = time.monotonic() + 1.0
        while self.statistics().bytes_received == received and time.monotonic() < deadline:
            time.sleep(0.001)
        assert self.statistics().bytes_received > received
        assert worker.decoder_worker._submitted == submitted  # pyright: ignore[reportPrivateUsage]
        observed.set()

    monkeypatch.setattr(DeviceSession, "_transition", transition_with_live_rx)
    with X4M200(port=device_port, baudrate=115200) as device:
        assert observed.wait(1.0)
        assert device.module.ping().ready


@pytest.mark.hardware
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
