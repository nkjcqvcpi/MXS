"""Dedicated pySerial worker. No other package code accesses Serial."""

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

import serial

from .diagnostics import StatisticsTracker
from .errors import (
    DeviceDisconnectedError,
    FrameBackpressureError,
    SerialOpenError,
    WorkerTerminatedError,
)
from .framing import McpStreamDecoder
from .messages import decode_message
from .router import MessageRouter

LOGGER = logging.getLogger(__name__)


class SerialLike(Protocol):
    baudrate: int

    def readinto(self, buffer: bytearray) -> int | None: ...
    def write(self, data: bytes | memoryview) -> int | None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


@dataclass(slots=True)
class WriteRequest:
    packet: bytes
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


@dataclass(slots=True)
class BaudRequest:
    baudrate: int
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


Request = WriteRequest | BaudRequest
SerialFactory = Callable[[str, int], SerialLike]


class SerialWorker:
    def __init__(
        self,
        port: str,
        baudrate: int,
        router: MessageRouter,
        statistics: StatisticsTracker,
        *,
        serial_factory: SerialFactory | None = None,
        raw_chunk_callback: Callable[[bytes], None] | None = None,
        tx_capacity: int = 64,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.router = router
        self.statistics = statistics
        self.serial_factory = serial_factory
        self.raw_chunk_callback = raw_chunk_callback
        self.decoder = McpStreamDecoder()
        self._requests: queue.Queue[Request] = queue.Queue(tx_capacity)
        self._stop = threading.Event()
        self._opened = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"x4cir-{port}", daemon=False)
        self._open_error: BaseException | None = None
        self._fatal_error: BaseException | None = None

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def start(self, timeout: float = 3.0) -> None:
        self._thread.start()
        if not self._opened.wait(timeout):
            raise SerialOpenError(f"serial worker did not open {self.port}")
        if self._open_error is not None:
            raise SerialOpenError(
                f"cannot open {self.port}: {self._open_error}"
            ) from self._open_error

    def send(self, packet: bytes, timeout: float = 2.0) -> None:
        request = WriteRequest(packet)
        self._requests.put(request, timeout=timeout)
        if not request.done.wait(timeout):
            raise WorkerTerminatedError("serial write did not complete")
        if request.error is not None:
            raise request.error

    def set_baudrate(self, baudrate: int, timeout: float = 2.0) -> None:
        request = BaudRequest(baudrate)
        self._requests.put(request, timeout=timeout)
        if not request.done.wait(timeout):
            raise WorkerTerminatedError("serial baud change did not complete")
        if request.error is not None:
            raise request.error
        self.baudrate = baudrate

    def close(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise WorkerTerminatedError("serial worker failed to terminate")

    def _open_serial(self) -> SerialLike:
        if self.serial_factory is not None:
            return self.serial_factory(self.port, self.baudrate)
        try:
            opened = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.02,
                write_timeout=1.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
                exclusive=True,
            )
            return cast("SerialLike", opened)
        except TypeError, ValueError:
            LOGGER.warning("exclusive serial open unsupported; retrying without it")
            opened = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.02,
                write_timeout=1.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            return cast("SerialLike", opened)

    def _run(self) -> None:
        port: SerialLike | None = None
        try:
            port = self._open_serial()
            LOGGER.info("opened %s at %d baud", self.port, self.baudrate)
        except BaseException as error:
            self._open_error = error
            self._opened.set()
            return
        self._opened.set()
        read_buffer = bytearray(64 * 1024)
        try:
            while not self._stop.is_set():
                self._drain_requests(port)
                received = port.readinto(read_buffer)
                if received:
                    chunk = bytes(memoryview(read_buffer)[:received])
                    self.statistics.add("bytes_received", received)
                    if self.raw_chunk_callback is not None:
                        self.raw_chunk_callback(chunk)
                    before_classic = self.decoder.statistics.classic_packets
                    before_noescape = self.decoder.statistics.noescape_packets
                    before_crc = self.decoder.statistics.crc_errors
                    before_malformed = self.decoder.statistics.malformed_packets
                    for payload in self.decoder.feed(chunk):
                        try:
                            self.router.route(decode_message(payload), payload)
                        except FrameBackpressureError:
                            raise
                        except BaseException as error:
                            self.statistics.add("malformed_packets")
                            LOGGER.debug("malformed MCP payload: %s", error)
                    self.statistics.add(
                        "classic_packets", self.decoder.statistics.classic_packets - before_classic
                    )
                    self.statistics.add(
                        "noescape_packets",
                        self.decoder.statistics.noescape_packets - before_noescape,
                    )
                    self.statistics.add(
                        "crc_errors", self.decoder.statistics.crc_errors - before_crc
                    )
                    self.statistics.add(
                        "malformed_packets",
                        self.decoder.statistics.malformed_packets - before_malformed,
                    )
            self._drain_requests(port)
        except FrameBackpressureError as error:
            self._fatal_error = error
            self.router.fail(error)
        except (serial.SerialException, OSError) as error:
            self._fatal_error = DeviceDisconnectedError(str(error))
            self.router.fail(self._fatal_error)
        except BaseException as error:
            self._fatal_error = WorkerTerminatedError(str(error))
            self.router.fail(self._fatal_error)
        finally:
            while True:
                try:
                    request = self._requests.get_nowait()
                except queue.Empty:
                    break
                request.error = self._fatal_error or WorkerTerminatedError("serial worker stopped")
                request.done.set()
            port.close()
            LOGGER.info("serial worker shut down")

    def _drain_requests(self, port: SerialLike) -> None:
        for _ in range(16):
            try:
                request = self._requests.get_nowait()
            except queue.Empty:
                return
            try:
                if isinstance(request, BaudRequest):
                    port.baudrate = request.baudrate
                else:
                    view = memoryview(request.packet)
                    offset = 0
                    while offset < len(view):
                        written = port.write(view[offset:])
                        if not written:
                            raise DeviceDisconnectedError("serial write returned zero bytes")
                        offset += written
                    port.flush()
                    self.statistics.add("bytes_transmitted", len(view))
                    LOGGER.debug("TX %s", request.packet.hex(" "))
            except BaseException as error:
                request.error = error
            finally:
                request.done.set()
