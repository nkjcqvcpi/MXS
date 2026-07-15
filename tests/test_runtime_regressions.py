"""Concurrency and bounded-runtime regressions after real-device preflight."""

import asyncio
import threading
import time

import numpy as np
import pytest

from mxs.constants import CONTENT_ID_NOISEMAP_FLOAT
from mxs.diagnostics import StatisticsTracker
from mxs.errors import (
    CommandRejectedError,
    CommandTimeoutError,
    FrameBackpressureError,
    MessageQueueOverflowError,
    RecordingBackpressureError,
    ReplyMismatchError,
    SessionDesynchronizedError,
    WorkerTerminatedError,
)
from mxs.expectations import reply
from mxs.message_hub import MessageHub, Subscription, Topic
from mxs.models import (
    Ack,
    BasebandAmplitudePhaseMessage,
    DataFloatMessage,
    ErrorResponse,
    IntReply,
    MatrixMessage,
    RespirationStatus,
    SleepStatus,
    SystemMessage,
)
from mxs.router import CommandManager, MessageRouter
from mxs.transport import DecoderWorker, RawCallbackWorker, WireChunk


def _router(downconversion: bool = False) -> tuple[MessageRouter, StatisticsTracker]:
    statistics = StatisticsTracker()
    manager = CommandManager(statistics, lambda: "STREAMING")
    return MessageRouter(
        statistics, manager, lambda: (-0.5, 5.0), lambda: downconversion
    ), statistics


def _message(counter: int) -> DataFloatMessage:
    return DataFloatMessage(0, counter, np.asarray([1, 2, 3, 4], np.float32))


def test_frame_router_policies_counters_and_topics() -> None:
    router, statistics = _router(True)
    oldest = router.subscribe(1, "drop_oldest")
    router.route(_message(1), b"")
    router.route(_message(3), b"")
    frame = oldest.queue.get_nowait()
    assert not isinstance(frame, BaseException)
    assert frame.samples.dtype == np.complex64 and frame.sequence_gap == 2
    assert statistics.snapshot().consumer_drops == 1

    router, _ = _router()
    lossless = router.subscribe(1, "error")
    router.route(_message(1), b"")
    with pytest.raises(FrameBackpressureError):
        router.route(_message(2), b"")
    assert isinstance(lossless.queue.get_nowait(), FrameBackpressureError)

    router, statistics = _router()
    newest = router.subscribe(1, "drop_newest")
    router.route(_message(1), b"")
    router.route(_message(2), b"")
    kept = newest.queue.get_nowait()
    assert not isinstance(kept, BaseException) and kept.frame_counter == 1
    router.route(_message(3), b"")
    after_drop = newest.queue.get_nowait()
    assert not isinstance(after_drop, BaseException) and after_drop.sequence_gap >= 1
    assert statistics.snapshot().consumer_drops == 1

    router, _ = _router()
    blocked = router.subscribe(1, "block_with_timeout")
    blocked.block_timeout = 0.001
    router.route(_message(1), b"")
    with pytest.raises(FrameBackpressureError):
        router.route(_message(2), b"")

    with pytest.raises(ValueError):
        router.subscribe(0)

    router, statistics = _router()
    subscription = router.subscribe(2, "error")
    router.route(_message(10), b"")
    router.route(SleepStatus(500, 4, 0.0, 0.0, 0, 0.0, 0.0), b"")
    router.route(_message(11), b"")
    assert statistics.snapshot().frame_counter_gaps == 0
    assert subscription.queue.qsize() == 2
    sleep = router.messages.sleep.read()
    assert isinstance(sleep, SleepStatus) and sleep.frame_counter == 500


def test_router_routes_application_and_system_messages() -> None:
    router, _ = _router()
    values = np.asarray([1.0], np.float32)
    routed = (
        (BasebandAmplitudePhaseMessage(1, 1, 1, 0.1, 1.0, 7.0, 0.0, values, values), "baseband_ap"),
        (RespirationStatus(1, 2, 3, 4.0, 5.0, 6), "respiration"),
        (
            MatrixMessage(
                CONTENT_ID_NOISEMAP_FLOAT, 1, 2, 3, 4, 1, 5, 1.0, 1.0, 0.0, 1.0, 2.0, values
            ),
            "noisemap_float",
        ),
    )
    for value, topic in routed:
        router.route(value, b"")
        assert getattr(router.messages, topic).read() is value
        assert router.messages.all.read() is value
    system = SystemMessage(1, b"x")
    router.route(system, b"")
    assert router.messages.system.read() is system

    error = WorkerTerminatedError("failed")
    failed = router.subscribe()
    router.fail(error)
    with pytest.raises(WorkerTerminatedError, match="failed"):
        value = failed.queue.get_nowait()
        if isinstance(value, BaseException):
            raise value
    router.close()
    router.reset_frame_counters()
    assert router.last_counter is None and not router.last_counter_by_stream


def test_command_manager_serialization_rejection_timeout_and_mismatch() -> None:
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
        time.sleep(0.002)
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
    assert maximum == 1 and len(results) == 4

    def reject(_packet: bytes, _timeout: float) -> None:
        manager.route(ErrorResponse(0x21), b"\x20\x21")

    with pytest.raises(CommandRejectedError):
        manager.execute("REJECT", b"packet", reject)

    manager = CommandManager(statistics, lambda: "OPEN")
    with pytest.raises(CommandTimeoutError):
        manager.execute("TIMEOUT", b"x", lambda _p, _t: None, timeout=0.001)
    with pytest.raises(SessionDesynchronizedError):
        manager.execute("LATE", b"x", lambda _p, _t: None)
    manager.reset()

    def mismatch(_packet: bytes, _timeout: float) -> None:
        manager.route(IntReply(2, 0, 1, 4, np.asarray([1], np.int32)), b"reply")

    with pytest.raises(ReplyMismatchError):
        manager.execute("GET", b"x", mismatch, expectation=reply(IntReply, 1, element_count=1))


def test_message_hub_overflow_policies_and_failure() -> None:
    oldest = Subscription[int](1, "drop_oldest")
    oldest.publish(1)
    oldest.publish(2)
    assert oldest.read() == 2 and oldest.dropped == 1
    newest = Subscription[int](1, "drop_newest")
    newest.publish(1)
    newest.publish(2)
    assert newest.read() == 1 and newest.dropped == 1
    blocked = Subscription[int](1, "block_with_timeout", block_timeout=0.001)
    blocked.publish(1)
    with pytest.raises(MessageQueueOverflowError):
        blocked.publish(2)
    errors = Subscription[int](1, "error")
    errors.publish(1)
    with pytest.raises(MessageQueueOverflowError):
        errors.publish(2)
    with pytest.raises(MessageQueueOverflowError):
        errors.read()
    with pytest.raises(ValueError):
        Subscription[int](0, "error")
    with pytest.raises(TimeoutError):
        Subscription[int](1, "error").read(0.001)
    empty = Subscription[int](1, "error")
    assert empty.peek() is None
    empty.publish(9)
    assert empty.peek() == 9 and next(empty.iter()) == 9
    empty.fail(WorkerTerminatedError("closed"))
    empty.fail(WorkerTerminatedError("ignored"))
    with pytest.raises(WorkerTerminatedError, match="closed"):
        empty.peek()
    hub = MessageHub()
    hub.publish("sleep", 1)
    assert hub.sleep.read() == 1 and hub.all.read() == 1
    hub.publish("not-a-topic", 2)
    assert hub.unknown.read() == 2
    hub.fail(RuntimeError("failed"))
    with pytest.raises(RuntimeError):
        hub.system.read()


def test_decoder_and_callback_worker_backpressure_and_failures() -> None:
    router, statistics = _router()
    decoder = DecoderWorker(router, statistics, control_capacity=1, stream_capacity=1)
    decoder.submit(bytes((0x10,)))
    with pytest.raises(FrameBackpressureError, match="control"):
        decoder.submit(bytes((0x10,)))

    decoder = DecoderWorker(router, statistics, control_capacity=1, stream_capacity=1)
    decoder.submit(b"stream")
    with pytest.raises(FrameBackpressureError, match="stream"):
        decoder.submit(b"stream")

    failures: list[BaseException] = []
    callback = RawCallbackWorker(lambda _chunk: None, statistics, failures.append, capacity=1)
    callback.submit(WireChunk(1, "rx", b"one"))
    with pytest.raises(RecordingBackpressureError):
        callback.submit(WireChunk(2, "rx", b"two"))
    assert failures and isinstance(failures[0], RecordingBackpressureError)
    with pytest.raises(RecordingBackpressureError):
        callback.submit(WireChunk(3, "rx", b"three"))

    failure = RuntimeError("callback failed")

    def fail_callback(_chunk: WireChunk) -> None:
        raise failure

    failures.clear()
    callback = RawCallbackWorker(fail_callback, statistics, failures.append)
    callback.start()
    callback.submit(WireChunk(4, "rx", b"live-shaped"))
    deadline = time.monotonic() + 1
    while callback.error is None and time.monotonic() < deadline:
        time.sleep(0.001)
    with pytest.raises(RuntimeError, match="callback failed"):
        callback.close()
    assert failures == [failure] and not callback.alive


@pytest.mark.asyncio
async def test_async_waiter_delivery_timeout_cancellation_and_close() -> None:
    topic = Topic[int]()
    child = topic.subscribe(2, "error")
    pending = asyncio.create_task(topic.read_async(timeout=1))
    await asyncio.sleep(0)
    topic.publish(4)
    assert await pending == 4 and child.read() == 4
    with pytest.raises(TimeoutError):
        await child.read_async(0.001)

    subscription = Subscription[int](2, "error")
    cancelled = asyncio.create_task(subscription.read_async())
    await asyncio.sleep(0)
    subscription.publish(17)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    await asyncio.sleep(0)
    assert await subscription.read_async(1) == 17
    topic.fail(WorkerTerminatedError("closed"))
    with pytest.raises(WorkerTerminatedError):
        await topic.read_async()

    iterated = Subscription[int](1, "error")
    iterated.publish(23)
    assert await anext(aiter(iterated)) == 23

    failed = Subscription[int](1, "error")
    waiting = asyncio.create_task(failed.read_async())
    await asyncio.sleep(0)
    failed.fail(WorkerTerminatedError("async failed"))
    with pytest.raises(WorkerTerminatedError, match="async failed"):
        await waiting
