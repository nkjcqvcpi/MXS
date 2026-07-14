"""Cancellation-safe asyncio facade over the shared worker session."""

import asyncio
import contextlib
import threading
from collections.abc import AsyncIterator

from .discovery import discover_port
from .errors import FrameBackpressureError
from .models import CirFrame, SessionStatistics, X4Config
from .router import QueuePolicy
from .session import DeviceSession
from .transport import SerialFactory


class AsyncX4M200:
    def __init__(
        self,
        port: str | None = None,
        baudrate: str | int = "auto",
        *,
        frame_queue_size: int = 256,
        overflow_policy: QueuePolicy = "error",
        command_timeout: float = 2.0,
        serial_factory: SerialFactory | None = None,
    ) -> None:
        self._session = DeviceSession(
            port or discover_port(),
            baudrate,
            frame_queue_size=frame_queue_size,
            overflow_policy=overflow_policy,
            command_timeout=command_timeout,
            serial_factory=serial_factory,
        )
        self._bridge_subscription = None
        self._bridge_thread: threading.Thread | None = None
        self._async_frames: asyncio.Queue[CirFrame | BaseException] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def open(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._async_frames = asyncio.Queue(self._session.frame_queue_size)
        await asyncio.to_thread(self._session.open)
        self._bridge_subscription = self._session.router.subscribe(
            self._session.frame_queue_size, self._session.overflow_policy
        )
        self._bridge_thread = threading.Thread(
            target=self._bridge_frames, name="mxs-async-bridge", daemon=False
        )
        self._bridge_thread.start()

    async def configure(self, config: X4Config) -> None:
        await asyncio.to_thread(self._session.configure, config)

    async def start(self) -> None:
        await asyncio.to_thread(self._session.start)

    async def stop(self) -> None:
        await asyncio.to_thread(self._session.stop)

    async def read_frame(self, timeout: float | None = None) -> CirFrame:
        if self._async_frames is None:
            raise RuntimeError("async device is not open")
        try:
            item = await asyncio.wait_for(self._async_frames.get(), timeout)
        except TimeoutError as error:
            raise TimeoutError("timed out waiting for a CIR frame") from error
        if isinstance(item, BaseException):
            raise item
        return item

    async def frames(self) -> AsyncIterator[CirFrame]:
        while True:
            yield await self.read_frame()

    async def statistics(self) -> SessionStatistics:
        return await asyncio.to_thread(self._session.statistics)

    async def close(self) -> None:
        await asyncio.to_thread(self._session.close)
        if self._bridge_thread is not None:
            await asyncio.to_thread(self._bridge_thread.join, 3.0)
            if self._bridge_thread.is_alive():
                raise RuntimeError("async bridge failed to terminate")
        self._bridge_thread = None
        self._bridge_subscription = None

    def _bridge_frames(self) -> None:
        subscription = self._bridge_subscription
        loop = self._loop
        if subscription is None or loop is None:
            return
        while True:
            item = subscription.queue.get()
            loop.call_soon_threadsafe(self._deliver_frame, item)
            if isinstance(item, BaseException):
                return

    def _deliver_frame(self, item: CirFrame | BaseException) -> None:
        target = self._async_frames
        if target is None:
            return
        try:
            target.put_nowait(item)
        except asyncio.QueueFull:
            while not target.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    target.get_nowait()
            target.put_nowait(FrameBackpressureError("async frame queue overflow"))

    async def __aenter__(self) -> AsyncX4M200:
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.close()
