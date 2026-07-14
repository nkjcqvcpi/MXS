"""Cancellation-safe asyncio facade over the shared worker session."""

import asyncio
import concurrent.futures
import contextlib
import threading
from collections.abc import AsyncIterator

from .discovery import discover_port
from .models import CirFrame, SessionStatistics, X4Config
from .router import QueuePolicy
from .session import DeviceSession
from .transport import SerialFactory


class _AsyncInterface:
    """Cancellation-safe async view of a serialized synchronous interface."""

    def __init__(self, target: object) -> None:
        self._target = target

    def __getattr__(self, name: str):
        method = getattr(self._target, name)

        async def call(*args: object, **kwargs: object):
            task = asyncio.create_task(asyncio.to_thread(method, *args, **kwargs))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # The wire transaction cannot be cancelled safely. Drain it before
                # allowing another serialized command to start.
                with contextlib.suppress(BaseException):
                    await asyncio.shield(task)
                raise

        return call


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
        self._bridge_thread: threading.Thread | None = None
        self._bridge_stop = threading.Event()
        self._async_frames: asyncio.Queue[CirFrame | BaseException] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.module = _AsyncInterface(self._session_interface("module"))
        self.profile = _AsyncInterface(self._session_interface("profile"))
        self.outputs = _AsyncInterface(self._session_interface("outputs"))
        self.xep = _AsyncInterface(self._session_interface("xep"))
        self.gpio = _AsyncInterface(self._session_interface("gpio"))
        self.noisemap = _AsyncInterface(self._session_interface("noisemap"))
        self.parameters = _AsyncInterface(self._session_interface("parameters"))
        self.filesystem = _AsyncInterface(self._session_interface("filesystem"))

    def _session_interface(self, name: str) -> object:
        from .interfaces import (
            FilesystemInterface,
            GpioInterface,
            ModuleInterface,
            NoisemapInterface,
            OutputsInterface,
            ParametersInterface,
            ProfileInterface,
            XepInterface,
        )

        interface_type = {
            "module": ModuleInterface,
            "profile": ProfileInterface,
            "outputs": OutputsInterface,
            "xep": XepInterface,
            "gpio": GpioInterface,
            "noisemap": NoisemapInterface,
            "parameters": ParametersInterface,
            "filesystem": FilesystemInterface,
        }[name]
        return interface_type(self._session)

    @property
    def messages(self):
        return self._session.router.messages

    async def open(self) -> None:
        self._bridge_stop = threading.Event()
        self._loop = asyncio.get_running_loop()
        self._async_frames = asyncio.Queue(self._session.frame_queue_size)
        await asyncio.to_thread(self._session.open)
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
        self._bridge_stop.set()
        await asyncio.to_thread(self._session.close)
        if self._bridge_thread is not None:
            await asyncio.to_thread(self._bridge_thread.join, 3.0)
            if self._bridge_thread.is_alive():
                raise RuntimeError("async bridge failed to terminate")
        self._bridge_thread = None
        self._async_frames = None
        self._loop = None

    def _bridge_frames(self) -> None:
        loop = self._loop
        target = self._async_frames
        if loop is None or target is None:
            return
        while True:
            item = self._session.frames.queue.get()
            delivery = asyncio.run_coroutine_threadsafe(target.put(item), loop)
            while True:
                try:
                    delivery.result(0.05)
                    break
                except concurrent.futures.TimeoutError:
                    if self._bridge_stop.is_set():
                        delivery.cancel()
                        return
                except concurrent.futures.CancelledError, RuntimeError:
                    return
            if isinstance(item, BaseException):
                return

    async def __aenter__(self) -> AsyncX4M200:
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.close()
