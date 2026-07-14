import asyncio

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
