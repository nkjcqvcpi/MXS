"""Concurrency regressions exercised only after live X4M200 traffic capture."""

import asyncio
import time

import pytest

from mxs import X4M200, X4Config
from mxs.constants import ResponseType
from mxs.diagnostics import StatisticsTracker
from mxs.errors import (
    FrameBackpressureError,
    MessageQueueOverflowError,
    RecordingBackpressureError,
    WorkerTerminatedError,
)
from mxs.framing import McpStreamDecoder
from mxs.message_hub import MessageHub, Subscription, Topic
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


@pytest.mark.hardware
@pytest.mark.stateful
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
        device.read_frame(timeout=2.0)
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
    deadline = time.monotonic() + 1
    while callback.error is None and time.monotonic() < deadline:
        time.sleep(0.001)
    with pytest.raises(RuntimeError, match="callback failed"):
        callback.close()
    assert failures == [failure] and not callback.alive


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
