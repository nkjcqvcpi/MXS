import time

import pytest

from mxs.diagnostics import StatisticsTracker
from mxs.errors import FrameBackpressureError
from mxs.router import CommandManager, MessageRouter
from mxs.transport import DecoderWorker, RawCallbackWorker


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
    received: list[bytes] = []
    raw = RawCallbackWorker(received.append, router.statistics, capacity=1)
    raw.submit(b"one")
    with pytest.raises(FrameBackpressureError):
        raw.submit(b"two")
    raw.start()
    deadline = time.monotonic() + 1
    while not received and time.monotonic() < deadline:
        time.sleep(0.001)
    raw.close()
    assert received == [b"one"]
