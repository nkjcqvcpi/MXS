"""Bounded optional processing pool with ordered result delivery."""

import concurrent.futures
import queue
import threading
from collections.abc import Callable
from typing import Literal

Backend = Literal["thread", "process", "inline"]


class ProcessingPipeline[T, R]:
    def __init__(
        self,
        function: Callable[[T], R],
        *,
        max_workers: int | None = None,
        backend: Backend = "thread",
        queue_size: int = 64,
        ordered: bool = True,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self.function = function
        self.ordered = ordered
        self._slots = threading.BoundedSemaphore(queue_size)
        self._results: queue.PriorityQueue[tuple[int, R | BaseException]] = queue.PriorityQueue(
            queue_size
        )
        self._sequence = 0
        self._next = 0
        self._pending: dict[int, R | BaseException] = {}
        if backend == "inline":
            self._executor = None
        elif backend == "thread":
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        elif backend == "process":
            self._executor = concurrent.futures.ProcessPoolExecutor(max_workers=max_workers)
        else:
            raise ValueError(f"unknown backend {backend!r}")

    def submit(self, item: T, timeout: float | None = None) -> int:
        if not self._slots.acquire(timeout=timeout):
            raise TimeoutError("processing input queue is full")
        sequence = self._sequence
        self._sequence += 1
        if self._executor is None:
            try:
                result: R | BaseException = self.function(item)
            except BaseException as error:
                result = error
            self._complete(sequence, result)
        else:
            future = self._executor.submit(self.function, item)
            future.add_done_callback(lambda done, seq=sequence: self._future_done(seq, done))
        return sequence

    def _future_done(self, sequence: int, future: concurrent.futures.Future[R]) -> None:
        try:
            result: R | BaseException = future.result()
        except BaseException as error:
            result = error
        self._complete(sequence, result)

    def _complete(self, sequence: int, result: R | BaseException) -> None:
        self._results.put((sequence, result))

    def read(self, timeout: float | None = None) -> R:
        while True:
            if self.ordered and self._next in self._pending:
                result = self._pending.pop(self._next)
                self._next += 1
                self._slots.release()
                return self._unwrap(result)
            sequence, result = self._results.get(timeout=timeout)
            if not self.ordered or sequence == self._next:
                self._next = max(self._next, sequence + 1)
                self._slots.release()
                return self._unwrap(result)
            self._pending[sequence] = result

    @staticmethod
    def _unwrap(result: R | BaseException) -> R:
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self, *, wait: bool = True) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def __enter__(self):
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
