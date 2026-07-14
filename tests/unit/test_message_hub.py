import asyncio
import threading
import time

import pytest

from mxs.errors import MessageQueueOverflowError, WorkerTerminatedError
from mxs.message_hub import MessageHub, Subscription, Topic


def test_subscription_policies_and_iteration() -> None:
    oldest = Subscription[int](1, "drop_oldest")
    oldest.publish(1)
    oldest.publish(2)
    assert oldest.read() == 2
    assert oldest.dropped == 1
    newest = Subscription[int](1, "drop_newest")
    newest.publish(1)
    newest.publish(2)
    assert newest.read() == 1
    assert newest.dropped == 1
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


def test_blocking_subscription_unblocks_when_reader_makes_space() -> None:
    subscription = Subscription[int](1, "block_with_timeout", block_timeout=0.2)
    subscription.publish(1)
    received: list[int] = []

    def delayed_read() -> None:
        time.sleep(0.01)
        received.append(subscription.read())

    reader = threading.Thread(target=delayed_read)
    reader.start()
    subscription.publish(2)
    reader.join()
    assert received == [1]
    assert subscription.read() == 2
    subscription.fail(RuntimeError("closed"))
    subscription.fail(RuntimeError("ignored"))
    with pytest.raises(RuntimeError, match="closed"):
        subscription.peek()
    subscription.publish(3)


@pytest.mark.asyncio
async def test_async_iteration_and_closed_read() -> None:
    subscription = Subscription[int](1, "error")
    subscription.publish(9)
    assert await anext(subscription.__aiter__()) == 9
    subscription.fail(WorkerTerminatedError("done"))
    with pytest.raises(WorkerTerminatedError):
        await subscription.read_async()


@pytest.mark.asyncio
async def test_topic_async_signal_subscribe_close_and_cancel() -> None:
    topic = Topic[int]()
    child = topic.subscribe(2, "error")
    pending = asyncio.create_task(topic.read_async(timeout=1))
    await asyncio.sleep(0)
    topic.publish(4)
    assert await pending == 4
    assert child.peek() == 4
    assert child.read() == 4
    timeout = asyncio.create_task(child.read_async(0.001))
    with pytest.raises(TimeoutError):
        await timeout
    topic.fail(WorkerTerminatedError("closed"))
    with pytest.raises(WorkerTerminatedError):
        await topic.read_async()


def test_message_hub_routes_all_and_unknown() -> None:
    hub = MessageHub()
    hub.publish("sleep", 1)
    assert hub.sleep.read() == 1
    assert hub.all.read() == 1
    hub.publish("not-a-topic", 2)
    assert hub.unknown.read() == 2
    hub.fail(RuntimeError("failed"))
    with pytest.raises(RuntimeError):
        hub.system.read()


@pytest.mark.asyncio
async def test_cancelled_selected_waiter_preserves_message() -> None:
    subscription = Subscription[int](2, "error")
    pending = asyncio.create_task(subscription.read_async())
    await asyncio.sleep(0)
    subscription.publish(17)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.sleep(0)
    assert await subscription.read_async(1) == 17


@pytest.mark.asyncio
async def test_cancelled_waiter_never_blocks_loop_when_blocking_queue_is_full() -> None:
    subscription = Subscription[int](1, "block_with_timeout", block_timeout=1.0)
    pending = asyncio.create_task(subscription.read_async())
    await asyncio.sleep(0)
    subscription.publish(1)
    pending.cancel()
    subscription.publish(2)
    ticked = asyncio.Event()
    asyncio.get_running_loop().call_soon(ticked.set)
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.wait_for(ticked.wait(), 0.1)
    await asyncio.sleep(0)
    with pytest.raises(MessageQueueOverflowError):
        subscription.read()


@pytest.mark.asyncio
async def test_publish_read_stress_10000() -> None:
    subscription = Subscription[int](10_000, "error")
    publisher = threading.Thread(
        target=lambda: [subscription.publish(value) for value in range(10_000)]
    )
    publisher.start()
    received = [await subscription.read_async(2) for _ in range(10_000)]
    publisher.join()
    assert received == list(range(10_000))
