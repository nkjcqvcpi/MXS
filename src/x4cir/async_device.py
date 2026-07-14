"""Cancellation-safe asyncio facade over the shared worker session."""

import asyncio
import time
from collections.abc import AsyncIterator

from .models import CirFrame, SessionStatistics, X4Config
from .router import QueuePolicy
from .session import DeviceSession
from .transport import SerialFactory


class AsyncX4M200:
    def __init__(
        self,
        port: str = "/dev/tty.usbmodem2101",
        baudrate: str | int = "auto",
        *,
        frame_queue_size: int = 256,
        overflow_policy: QueuePolicy = "error",
        command_timeout: float = 2.0,
        serial_factory: SerialFactory | None = None,
    ) -> None:
        self._session = DeviceSession(
            port,
            baudrate,
            frame_queue_size=frame_queue_size,
            overflow_policy=overflow_policy,
            command_timeout=command_timeout,
            serial_factory=serial_factory,
        )

    async def open(self) -> None:
        await asyncio.to_thread(self._session.open)

    async def configure(self, config: X4Config) -> None:
        await asyncio.to_thread(self._session.configure, config)

    async def start(self) -> None:
        await asyncio.to_thread(self._session.start)

    async def stop(self) -> None:
        await asyncio.to_thread(self._session.stop)

    async def read_frame(self, timeout: float | None = None) -> CirFrame:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            slice_timeout = (
                0.1 if deadline is None else min(0.1, max(0.0, deadline - time.monotonic()))
            )
            if deadline is not None and slice_timeout <= 0:
                raise TimeoutError("timed out waiting for a CIR frame")
            try:
                return await asyncio.to_thread(self._session.read_frame, slice_timeout)
            except TimeoutError:
                if deadline is not None and time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(0)

    async def frames(self) -> AsyncIterator[CirFrame]:
        while True:
            yield await self.read_frame()

    async def statistics(self) -> SessionStatistics:
        return await asyncio.to_thread(self._session.statistics)

    async def close(self) -> None:
        await asyncio.to_thread(self._session.close)

    async def __aenter__(self) -> AsyncX4M200:
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.close()
