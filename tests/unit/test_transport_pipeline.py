import time

import pytest

from mxs.diagnostics import StatisticsTracker
from mxs.errors import (
    FrameBackpressureError,
    RecordingBackpressureError,
    SerialOpenError,
    WorkerTerminatedError,
)
from mxs.router import CommandManager, MessageRouter
from mxs.transport import DecoderWorker, RawCallbackWorker, SerialWorker, WireChunk
from tests.conftest import FakeSerial


def make_router() -> MessageRouter:
    statistics = StatisticsTracker()
    return MessageRouter(
        statistics,
        CommandManager(statistics, lambda: "OPEN"),
        lambda: (0.0, 1.0),
        lambda: False,
    )


def test_decoder_worker_routes_stream_and_retains_errors() -> None:
    router = make_router()
    frames = router.subscribe(2, "error")
    worker = DecoderWorker(router, router.statistics)
    worker.start()
    worker.submit(b"\xa0\x12\0\0\0\0\x01\0\0\0\x02\0\0\0\0\0\x80?\0\0\0@")
    worker.submit(b"\xa0\x12")
    frame = frames.queue.get(timeout=1)
    assert not isinstance(frame, BaseException)
    worker.close()
    assert router.statistics.snapshot().malformed_packets == 1


def test_decoder_and_raw_callback_backpressure() -> None:
    router = make_router()
    decoder = DecoderWorker(router, router.statistics, stream_capacity=1)
    decoder.submit(b"\x50")
    with pytest.raises(FrameBackpressureError):
        decoder.submit(b"\x50")
    received: list[WireChunk] = []
    raw = RawCallbackWorker(received.append, router.statistics, lambda _error: None, capacity=1)
    raw.submit(WireChunk(1, "rx", b"one"))
    with pytest.raises(RecordingBackpressureError):
        raw.submit(WireChunk(2, "rx", b"two"))
    raw.start()
    deadline = time.monotonic() + 1
    while not received and time.monotonic() < deadline:
        time.sleep(0.001)
    with pytest.raises(RecordingBackpressureError):
        raw.close()
    assert received == [WireChunk(1, "rx", b"one")]


def test_real_serial_constructor_and_exclusive_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = make_router()
    calls = 0

    def serial_constructor(**kwargs: object) -> FakeSerial:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TypeError("exclusive unsupported")
        baudrate = kwargs["baudrate"]
        assert isinstance(baudrate, int)
        return FakeSerial(baudrate, initial_stream=False)

    monkeypatch.setattr("mxs.transport.serial.Serial", serial_constructor)
    worker = SerialWorker("fake", 115200, router, router.statistics)
    opened = worker._open_serial()  # pyright: ignore[reportPrivateUsage]
    assert opened.baudrate == 115200
    assert calls == 2


def test_transport_request_timeouts_and_open_failure() -> None:
    router = make_router()
    idle = SerialWorker("fake", 115200, router, router.statistics)
    with pytest.raises(WorkerTerminatedError, match="write"):
        idle.send(b"packet", timeout=0.001)
    with pytest.raises(WorkerTerminatedError, match="baud"):
        idle.set_baudrate(921600, timeout=0.001)

    def fail_open(_port: str, _baudrate: int) -> FakeSerial:
        raise OSError("open failed")

    failed = SerialWorker("fake", 115200, router, router.statistics, serial_factory=fail_open)
    with pytest.raises(SerialOpenError, match="open failed"):
        failed.start()
    failed.close()
