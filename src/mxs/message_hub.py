"""Bounded typed message topics for synchronous and asynchronous consumers."""

import asyncio
import queue
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from typing import Literal

from .errors import MessageQueueOverflowError, WorkerTerminatedError

OverflowPolicy = Literal["error", "drop_oldest", "drop_newest", "block_with_timeout"]


class Subscription[T]:
    def __init__(
        self,
        capacity: int,
        overflow_policy: OverflowPolicy,
        *,
        block_timeout: float = 0.1,
    ) -> None:
        if capacity <= 0:
            raise ValueError("subscription capacity must be positive")
        self._queue: queue.Queue[T | BaseException] = queue.Queue(capacity)
        self.overflow_policy = overflow_policy
        self.block_timeout = block_timeout
        self.dropped = 0
        self.closed = False
        self._async_waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[T]]] = []
        self._lock = threading.Lock()

    def publish(self, message: T) -> None:
        if self.closed:
            return
        waiter: tuple[asyncio.AbstractEventLoop, asyncio.Future[T]] | None = None
        with self._lock:
            while self._async_waiters and waiter is None:
                candidate = self._async_waiters.pop(0)
                if not candidate[1].done():
                    waiter = candidate
        if waiter is not None:
            loop, future = waiter
            loop.call_soon_threadsafe(self._complete_waiter, future, message)
            return
        try:
            self._queue.put_nowait(message)
        except queue.Full:
            self._overflow(message)

    def _overflow(self, message: T) -> None:
        if self.overflow_policy == "error":
            error = MessageQueueOverflowError("typed message subscription overflow")
            self.fail(error)
            raise error
        if self.overflow_policy == "drop_newest":
            self.dropped += 1
            return
        if self.overflow_policy == "block_with_timeout":
            try:
                self._queue.put(message, timeout=self.block_timeout)
                return
            except queue.Full:
                error = MessageQueueOverflowError("typed message subscription block timed out")
                self.fail(error)
                raise error from None
        with suppress(queue.Empty):
            self._queue.get_nowait()
        self.dropped += 1
        self._queue.put_nowait(message)

    @staticmethod
    def _complete_waiter(future: asyncio.Future[T], message: T) -> None:
        if not future.done():
            future.set_result(message)

    def peek(self) -> T | None:
        with self._queue.mutex:
            if not self._queue.queue:
                return None
            item = self._queue.queue[0]
        if isinstance(item, BaseException):
            raise item
        return item

    def read(self, timeout: float | None = None) -> T:
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError("timed out waiting for a message") from error
        if isinstance(item, BaseException):
            raise item
        return item

    async def read_async(self, timeout: float | None = None) -> T:
        with suppress(queue.Empty):
            item = self._queue.get_nowait()
            if isinstance(item, BaseException):
                raise item
            return item
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        with self._lock:
            if self.closed:
                raise WorkerTerminatedError("message subscription is closed")
            self._async_waiters.append((loop, future))
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            with self._lock:
                self._async_waiters = [
                    pair for pair in self._async_waiters if pair[1] is not future
                ]

    def iter(self) -> Iterator[T]:
        while True:
            yield self.read()

    def __aiter__(self) -> AsyncIterator[T]:
        return self._aiter()

    async def _aiter(self) -> AsyncIterator[T]:
        while True:
            yield await self.read_async()

    def fail(self, error: BaseException) -> None:
        if self.closed:
            return
        self.closed = True
        while True:
            with suppress(queue.Empty):
                self._queue.get_nowait()
                continue
            break
        with suppress(queue.Full):
            self._queue.put_nowait(error)
        with self._lock:
            waiters = self._async_waiters
            self._async_waiters = []
        for loop, future in waiters:
            loop.call_soon_threadsafe(self._fail_waiter, future, error)

    @staticmethod
    def _fail_waiter(future: asyncio.Future[T], error: BaseException) -> None:
        if not future.done():
            future.set_exception(error)


class Topic[T](Subscription[T]):
    def __init__(self, capacity: int = 64, overflow_policy: OverflowPolicy = "drop_oldest") -> None:
        super().__init__(capacity, overflow_policy)
        self._subscriptions: list[Subscription[T]] = []
        self._subscriptions_lock = threading.Lock()

    def subscribe(
        self, capacity: int = 64, overflow_policy: OverflowPolicy = "error"
    ) -> Subscription[T]:
        subscription = Subscription[T](capacity, overflow_policy)
        with self._subscriptions_lock:
            self._subscriptions.append(subscription)
        return subscription

    def publish(self, message: T) -> None:
        super().publish(message)
        with self._subscriptions_lock:
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            subscription.publish(message)

    def fail(self, error: BaseException) -> None:
        super().fail(error)
        with self._subscriptions_lock:
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            subscription.fail(error)


class MessageHub:
    """Stable public topic names; unsupported firmware simply never publishes."""

    TOPICS = (
        "sleep",
        "respiration",
        "respiration_moving_list",
        "respiration_detection_list",
        "normalized_movement",
        "vital_signs",
        "baseband_iq",
        "baseband_ap",
        "pulse_doppler_float",
        "pulse_doppler_byte",
        "noisemap_float",
        "noisemap_byte",
        "raw_rf",
        "system",
        "unknown",
        "all",
    )
    sleep: Topic[object]
    respiration: Topic[object]
    respiration_moving_list: Topic[object]
    respiration_detection_list: Topic[object]
    normalized_movement: Topic[object]
    vital_signs: Topic[object]
    baseband_iq: Topic[object]
    baseband_ap: Topic[object]
    pulse_doppler_float: Topic[object]
    pulse_doppler_byte: Topic[object]
    noisemap_float: Topic[object]
    noisemap_byte: Topic[object]
    raw_rf: Topic[object]
    system: Topic[object]
    unknown: Topic[object]
    all: Topic[object]

    def __init__(self) -> None:
        self._topics: dict[str, Topic[object]] = {}
        for name in self.TOPICS:
            value = Topic[object]()
            setattr(self, name, value)
            self._topics[name] = value

    def publish(self, topic: str, message: object) -> None:
        target = self._topics.get(topic, self.unknown)
        target.publish(message)
        if target is not self.all:
            self.all.publish(message)

    def fail(self, error: BaseException) -> None:
        for name in self.TOPICS:
            self._topics[name].fail(error)
