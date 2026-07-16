"""Concurrency regressions exercised only after live X4M200 traffic capture."""

import asyncio
import queue
import threading
import time

import pytest

from mxs import X4M200, CirFrame, X4Config
from mxs.constants import ResponseType
from mxs.diagnostics import StatisticsTracker
from mxs.errors import (
    CommandTimeoutError,
    FrameBackpressureError,
    MessageQueueOverflowError,
    RecordingBackpressureError,
    SessionDesynchronizedError,
    WorkerTerminatedError,
)
from mxs.framing import McpStreamDecoder
from mxs.message_hub import MessageHub, Subscription, Topic
from mxs.router import CommandManager, FrameSubscription, MessageRouter
from mxs.transport import DecoderWorker, RawCallbackWorker, WireChunk


def test_message_hub_overflow_policies_and_failure(device_port: str) -> None:
    del device_port
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
    with pytest.raises(WorkerTerminatedError, match="closed"):
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
    hub.system.publish(3)

    blocking = Subscription[int](1, "block_with_timeout", block_timeout=1.0)
    blocking.publish(1)
    publisher = threading.Thread(target=lambda: blocking.publish(2))
    publisher.start()
    time.sleep(0.01)
    assert blocking.read() == 1
    publisher.join(1.0)
    assert not publisher.is_alive() and blocking.read() == 2

    cannot_block = Subscription[int](1, "block_with_timeout")
    cannot_block.publish(1)
    with (
        cannot_block._lock,  # pyright: ignore[reportPrivateUsage]
        pytest.raises(MessageQueueOverflowError, match="cannot block"),
    ):
        cannot_block._enqueue_locked(2, allow_block=False)  # pyright: ignore[reportPrivateUsage]

    bounded: queue.Queue[int] = queue.Queue(1)
    bounded.put_nowait(1)
    MessageRouter._bounded_put(bounded, 2)  # pyright: ignore[reportPrivateUsage]
    assert bounded.get_nowait() == 2

    desynchronized: list[BaseException] = []
    manager = CommandManager(StatisticsTracker(), lambda: "OPEN", desynchronized.append)
    with pytest.raises(CommandTimeoutError):
        manager.execute("timeout", b"", lambda _packet, _timeout: None, timeout=0.001)
    assert len(desynchronized) == 1
    with pytest.raises(SessionDesynchronizedError):
        manager.execute("desynchronized", b"", lambda _packet, _timeout: None)
    manager.reset()
    failure = RuntimeError("sender failed")

    def fail_pending(_packet: bytes, _timeout: float) -> None:
        manager.fail(failure)

    with pytest.raises(RuntimeError, match="sender failed"):
        manager.execute("failure", b"", fail_pending)


@pytest.mark.hardware
def test_decoder_and_callback_failures_use_live_packets(device_port: str) -> None:
    raw_chunks: list[bytes] = []
    wire_chunks: list[WireChunk] = []
    with X4M200(
        port=device_port,
        raw_chunk_callback=raw_chunks.append,
        wire_chunk_callback=wire_chunks.append,
    ) as device:
        assert device.module.ping().ready
        device.configure(X4Config())
        device.start()
        live_frame = device.read_frame(timeout=2.0)
        device.stop()
        decoder = McpStreamDecoder()
        payloads = [payload for chunk in raw_chunks for payload in decoder.feed(chunk)]
        control_types = {
            ResponseType.ACK,
            ResponseType.ERROR,
            ResponseType.REPLY,
            ResponseType.PONG,
            ResponseType.SYSTEM,
        }
        control = next(payload for payload in payloads if payload[0] in control_types)
        stream = next(payload for payload in payloads if payload[0] == ResponseType.DATA)

        statistics = StatisticsTracker()
        router = device._session.router  # pyright: ignore[reportPrivateUsage]
        control_worker = DecoderWorker(
            router,
            statistics,
            control_capacity=1,
            stream_capacity=1,
        )
        control_worker.submit(control)
        with pytest.raises(FrameBackpressureError, match="control"):
            control_worker.submit(bytes(control))

        stream_worker = DecoderWorker(
            router,
            statistics,
            control_capacity=1,
            stream_capacity=1,
        )
        stream_worker.submit(stream)
        with pytest.raises(FrameBackpressureError, match="stream"):
            stream_worker.submit(bytes(stream))

    rx_chunk = next(chunk for chunk in wire_chunks if chunk.direction == "rx")
    failures: list[BaseException] = []
    callback = RawCallbackWorker(lambda _chunk: None, statistics, failures.append, capacity=1)
    callback.submit(rx_chunk)
    with pytest.raises(RecordingBackpressureError):
        callback.submit(rx_chunk)
    assert failures and isinstance(failures[0], RecordingBackpressureError)

    failure = RuntimeError("callback failed")

    def fail_callback(_chunk: WireChunk) -> None:
        raise failure

    failures.clear()
    callback = RawCallbackWorker(fail_callback, statistics, failures.append)
    callback.start()
    callback.submit(rx_chunk)
    callback.enable_delivery()
    deadline = time.monotonic() + 1
    while callback.error is None and time.monotonic() < deadline:
        time.sleep(0.001)
    with pytest.raises(RuntimeError, match="callback failed"):
        callback.close()
    assert failures == [failure] and not callback.alive

    with pytest.raises(ValueError, match="positive"):
        FrameSubscription(0, "error", statistics)
    closed = FrameSubscription(1, "error", statistics)
    closed.fail(WorkerTerminatedError("closed"))
    closed.publish(live_frame)

    newest = FrameSubscription(1, "drop_newest", statistics)
    newest.publish(live_frame)
    newest.publish(live_frame)
    newest_frame = newest.queue.get_nowait()
    assert isinstance(newest_frame, CirFrame)
    assert newest_frame.sequence_gap == live_frame.sequence_gap
    newest.publish(live_frame)
    newest_frame = newest.queue.get_nowait()
    assert isinstance(newest_frame, CirFrame)
    assert newest_frame.sequence_gap == live_frame.sequence_gap + 1

    oldest = FrameSubscription(1, "drop_oldest", statistics)
    oldest.publish(live_frame)
    oldest.publish(live_frame)
    oldest_frame = oldest.queue.get_nowait()
    assert isinstance(oldest_frame, CirFrame)
    assert oldest_frame.sequence_gap == live_frame.sequence_gap + 1

    blocked = FrameSubscription(1, "block_with_timeout", statistics, block_timeout=0.001)
    blocked.publish(live_frame)
    with pytest.raises(FrameBackpressureError, match="remained full"):
        blocked.publish(live_frame)

    errors = FrameSubscription(1, "error", statistics)
    errors.publish(live_frame)
    with pytest.raises(FrameBackpressureError, match="lossless"):
        errors.publish(live_frame)


@pytest.mark.asyncio
async def test_async_waiter_delivery_timeout_cancellation_and_close(device_port: str) -> None:
    del device_port
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

    failed = Subscription[int](1, "error")
    waiting = asyncio.create_task(failed.read_async())
    await asyncio.sleep(0)
    failed.fail(WorkerTerminatedError("async failed"))
    with pytest.raises(WorkerTerminatedError, match="async failed"):
        await waiting
    with pytest.raises(WorkerTerminatedError, match="async failed"):
        await failed.read_async()
    with pytest.raises(WorkerTerminatedError, match="closed"):
        await failed.read_async()

    iterated = Subscription[int](1, "error")
    iterator = iterated.__aiter__()
    iterated.publish(23)
    assert await anext(iterator) == 23

    loop = asyncio.get_running_loop()
    chained = Subscription[int](1, "error")
    completed = loop.create_future()
    completed.cancel()
    successor = loop.create_future()
    chained._async_waiters.append((loop, successor))  # pyright: ignore[reportPrivateUsage]
    chained._complete_waiter(completed, 29)  # pyright: ignore[reportPrivateUsage]
    assert await successor == 29

    nonblocking = Subscription[int](1, "block_with_timeout")
    nonblocking.publish(1)
    completed = loop.create_future()
    completed.cancel()
    nonblocking._complete_waiter(completed, 2)  # pyright: ignore[reportPrivateUsage]
    assert nonblocking.closed
