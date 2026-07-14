import threading
import time

import numpy as np
import pytest

from mxs.diagnostics import StatisticsTracker
from mxs.errors import (
    CommandRejectedError,
    CommandTimeoutError,
    FrameBackpressureError,
    ReplyMismatchError,
    SessionDesynchronizedError,
)
from mxs.expectations import reply
from mxs.models import Ack, DataFloatMessage, ErrorResponse, IntReply
from mxs.router import CommandManager, MessageRouter


def make_router(downconversion: bool = False) -> tuple[MessageRouter, StatisticsTracker]:
    statistics = StatisticsTracker()
    manager = CommandManager(statistics, lambda: "STREAMING")
    return MessageRouter(
        statistics, manager, lambda: (-0.5, 5.0), lambda: downconversion
    ), statistics


def message(counter: int) -> DataFloatMessage:
    return DataFloatMessage(0, counter, np.asarray([1, 2, 3, 4], dtype=np.float32))


def test_latest_frame_drop_is_reported() -> None:
    router, statistics = make_router()
    subscription = router.subscribe(1, "drop_oldest")
    router.route(message(1), b"")
    router.route(message(2), b"")
    frame = subscription.queue.get_nowait()
    assert not isinstance(frame, BaseException)
    assert frame.frame_counter == 2
    assert frame.sequence_gap == 1
    assert statistics.snapshot().consumer_drops == 1


def test_lossless_overflow_raises_and_fails_consumer() -> None:
    router, _ = make_router()
    subscription = router.subscribe(1, "error")
    router.route(message(1), b"")
    with pytest.raises(FrameBackpressureError):
        router.route(message(2), b"")
    assert isinstance(subscription.queue.get_nowait(), FrameBackpressureError)


def test_iq_conversion_and_counter_gap() -> None:
    router, statistics = make_router(True)
    subscription = router.subscribe(4, "error")
    router.route(message(10), b"")
    router.route(message(13), b"")
    first = subscription.queue.get_nowait()
    second = subscription.queue.get_nowait()
    assert not isinstance(first, BaseException)
    assert not isinstance(second, BaseException)
    assert first.samples.dtype == np.complex64
    assert second.sequence_gap == 2
    assert statistics.snapshot().frame_counter_gaps == 2


def test_commands_are_serialized_and_firmware_error_is_preserved() -> None:
    statistics = StatisticsTracker()
    manager = CommandManager(statistics, lambda: "MANUAL")
    active = 0
    maximum = 0
    lock = threading.Lock()

    def sender(_packet: bytes, _timeout: float) -> None:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.005)
        manager.route(Ack(), b"\x10")
        with lock:
            active -= 1

    results: list[object] = []
    threads = [
        threading.Thread(target=lambda: results.append(manager.execute("TEST", b"x", sender)))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert maximum == 1
    assert len(results) == 4

    def reject(_packet: bytes, _timeout: float) -> None:
        manager.route(ErrorResponse(0x21), b"\x20\x21")

    with pytest.raises(CommandRejectedError) as caught:
        manager.execute("REJECT", b"packet", reject)
    assert caught.value.firmware_error_code == 0x21
    assert caught.value.device_state == "MANUAL"


def test_command_expectations_timeout_and_reset() -> None:
    statistics = StatisticsTracker()
    desynchronized: list[BaseException] = []
    manager = CommandManager(statistics, lambda: "OPEN", desynchronized.append)

    def no_response(_packet: bytes, _timeout: float) -> None:
        pass

    with pytest.raises(CommandTimeoutError):
        manager.execute("TIMEOUT", b"x", no_response, timeout=0.001)
    assert desynchronized
    with pytest.raises(SessionDesynchronizedError):
        manager.execute("LATE", b"x", no_response)
    manager.reset()

    def mismatch(_packet: bytes, _timeout: float) -> None:
        manager.route(IntReply(2, 0, 1, 4, np.asarray([1], np.int32)), b"reply")

    with pytest.raises(ReplyMismatchError):
        manager.execute("GET", b"x", mismatch, expectation=reply(IntReply, 1, element_count=1))


def test_remaining_frame_queue_policies_and_router_close() -> None:
    router, _ = make_router()
    newest = router.subscribe(1, "drop_newest")
    router.route(message(1), b"")
    router.route(message(2), b"")
    first = newest.queue.get_nowait()
    assert not isinstance(first, BaseException) and first.frame_counter == 1
    router.subscribe(1, "block_with_timeout")
    router.route(message(3), b"")
    with pytest.raises(FrameBackpressureError):
        router.route(message(4), b"")
    router.close()
