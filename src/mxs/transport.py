"""Dedicated pySerial worker. No other package code accesses Serial."""

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

import serial

from .constants import ResponseType
from .diagnostics import StatisticsTracker
from .errors import (
    DeviceDisconnectedError,
    FrameBackpressureError,
    RecordingBackpressureError,
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


@dataclass(frozen=True, slots=True)
class WireChunk:
    timestamp_monotonic_ns: int
    direction: Literal["rx", "tx"]
    data: bytes


class DecoderWorker:
    """Prioritized control decoding and ordered stream decoding off the serial thread."""

    def __init__(
        self,
        router: MessageRouter,
        statistics: StatisticsTracker,
        *,
        control_capacity: int = 64,
        stream_capacity: int = 512,
    ) -> None:
        self.router = router
        self.statistics = statistics
        self.control: queue.Queue[bytes] = queue.Queue(control_capacity)
        self.stream: queue.Queue[bytes] = queue.Queue(stream_capacity)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mxs-decoder", daemon=False)
        self._condition = threading.Condition()
        self._submitted = 0
        self._completed = 0
        self._error: BaseException | None = None

    def start(self) -> None:
        self._thread.start()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def submit(self, payload: bytes) -> None:
        self.raise_if_failed()
        control_types = {
            ResponseType.ACK,
            ResponseType.ERROR,
            ResponseType.REPLY,
            ResponseType.PONG,
            ResponseType.SYSTEM,
        }
        target = self.control if payload and payload[0] in control_types else self.stream
        try:
            target.put_nowait(payload)
            with self._condition:
                self._submitted += 1
            self.statistics.maximum(
                "decoder_control_high_water_mark"
                if target is self.control
                else "decoder_stream_high_water_mark",
                max(1, target.qsize()),
            )
        except queue.Full as error:
            raise FrameBackpressureError(
                "control decoder queue overflow"
                if target is self.control
                else "stream decoder queue overflow"
            ) from error

    def close(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise WorkerTerminatedError("message decoder failed to terminate")
        self.raise_if_failed()

    def flush_callbacks(self, timeout: float) -> None:
        with self._condition:
            target = self._submitted
            if not self._condition.wait_for(
                lambda: self._completed >= target or self._error is not None,
                timeout,
            ):
                raise WorkerTerminatedError("message decoder did not flush pending work")
        self.raise_if_failed()

    def raise_if_failed(self) -> None:
        with self._condition:
            error = self._error
        if error is not None:
            raise error
        if (
            self._thread.ident is not None
            and not self._thread.is_alive()
            and not self._stop.is_set()
        ):
            raise WorkerTerminatedError("message decoder terminated unexpectedly")

    def _run(self) -> None:
        try:
            while not self._stop.is_set() or not self.control.empty() or not self.stream.empty():
                payload: bytes | None = None
                try:
                    payload = self.control.get_nowait()
                except queue.Empty:
                    try:
                        payload = self.stream.get(timeout=0.02)
                    except queue.Empty:
                        continue
                try:
                    self.router.route(decode_message(payload), payload)
                except FrameBackpressureError:
                    raise
                except ValueError as error:
                    self.statistics.add("malformed_packets")
                    LOGGER.debug("malformed MCP payload: %s", error)
                finally:
                    with self._condition:
                        self._completed += 1
                        self._condition.notify_all()
        except BaseException as error:
            with self._condition:
                self._error = error
                self._condition.notify_all()
            self.router.fail(error)


class RawCallbackWorker:
    """Compatibility adapter that isolates a raw recording callback from serial I/O."""

    def __init__(
        self,
        callback: Callable[[WireChunk], None],
        statistics: StatisticsTracker,
        fatal_callback: Callable[[BaseException], None],
        capacity: int = 256,
    ) -> None:
        self.callback = callback
        self.statistics = statistics
        self.fatal_callback = fatal_callback
        self.queue: queue.Queue[WireChunk] = queue.Queue(capacity)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mxs-raw-writer", daemon=False)
        self.error: BaseException | None = None
        self._condition = threading.Condition()
        self._submitted = 0
        self._completed = 0
        # Queue user callbacks during baud-candidate probing. Acceptance releases
        # delivery only after the session has atomically transitioned to OPEN.
        self._delivery_enabled = threading.Event()

    def start(self) -> None:
        self._thread.start()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def submit(self, chunk: WireChunk) -> None:
        self.raise_if_failed()
        try:
            self.queue.put_nowait(chunk)
            with self._condition:
                self._submitted += 1
            self.statistics.maximum("raw_callback_high_water_mark", max(1, self.queue.qsize()))
        except queue.Full as error:
            recording_error = RecordingBackpressureError("raw recording queue overflow")
            with self._condition:
                self.error = recording_error
                self._condition.notify_all()
            self.fatal_callback(recording_error)
            raise recording_error from error

    def close(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise WorkerTerminatedError("raw recording worker failed to terminate")
        self.raise_if_failed()

    def enable_delivery(self) -> None:
        self._delivery_enabled.set()

    def flush_callbacks(self, timeout: float) -> None:
        with self._condition:
            target = self._submitted
            if not self._condition.wait_for(
                lambda: self._completed >= target or self.error is not None,
                timeout,
            ):
                raise WorkerTerminatedError("raw callback worker did not flush pending work")
        self.raise_if_failed()

    def raise_if_failed(self) -> None:
        with self._condition:
            error = self.error
        if error is not None:
            raise error
        if (
            self._thread.ident is not None
            and not self._thread.is_alive()
            and not self._stop.is_set()
        ):
            raise WorkerTerminatedError("raw callback worker terminated unexpectedly")

    def _run(self) -> None:
        try:
            while not self._stop.is_set() or not self.queue.empty():
                try:
                    chunk = self.queue.get(timeout=0.02)
                except queue.Empty:
                    continue
                while not self._delivery_enabled.wait(0.02):
                    if self._stop.is_set():
                        return
                try:
                    self.callback(chunk)
                finally:
                    with self._condition:
                        self._completed += 1
                        self._condition.notify_all()
        except BaseException as error:
            with self._condition:
                self.error = error
                self._condition.notify_all()
            self.fatal_callback(error)


class SerialWorker:
    def __init__(
        self,
        port: str,
        baudrate: int,
        router: MessageRouter,
        statistics: StatisticsTracker,
        *,
        raw_chunk_callback: Callable[[bytes], None] | None = None,
        wire_chunk_callback: Callable[[WireChunk], None] | None = None,
        tx_capacity: int = 64,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.router = router
        self.statistics = statistics
        self.raw_chunk_callback = raw_chunk_callback
        self.wire_chunk_callback = wire_chunk_callback
        self.decoder = McpStreamDecoder()
        self.decoder_worker = DecoderWorker(router, statistics)

        def dispatch_raw(chunk: WireChunk) -> None:
            if chunk.direction == "rx" and self.raw_chunk_callback is not None:
                self.raw_chunk_callback(chunk.data)
            if self.wire_chunk_callback is not None:
                self.wire_chunk_callback(chunk)

        self.raw_worker = (
            RawCallbackWorker(dispatch_raw, statistics, router.fail)
            if raw_chunk_callback is not None or wire_chunk_callback is not None
            else None
        )
        self._requests: queue.Queue[Request] = queue.Queue(tx_capacity)
        self._stop = threading.Event()
        self._opened = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"mxs-{port}", daemon=False)
        self._open_error: BaseException | None = None
        self._fatal_error: BaseException | None = None
        self._failure_lock = threading.Lock()
        self._callback_submission_lock = threading.Lock()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def owned_workers_alive(self) -> bool:
        return (
            self.alive
            or self.decoder_worker.alive
            or (self.raw_worker is not None and self.raw_worker.alive)
        )

    def start(self, timeout: float = 3.0) -> None:
        self.decoder_worker.start()
        if self.raw_worker is not None:
            self.raw_worker.start()
        self._thread.start()
        if not self._opened.wait(timeout):
            raise SerialOpenError(f"serial worker did not open {self.port}")
        if self._open_error is not None:
            raise SerialOpenError(
                f"cannot open {self.port}: {self._open_error}"
            ) from self._open_error
        self.raise_if_failed()

    def flush_callbacks(self, timeout: float) -> None:
        with self._callback_submission_lock:
            started = time.monotonic()
            self.decoder_worker.flush_callbacks(timeout)
            if self.raw_worker is not None:
                remaining = max(0.0, timeout - (time.monotonic() - started))
                self.raw_worker.flush_callbacks(remaining)
            self.raise_if_failed()

    def accept_candidate(self, timeout: float, accept: Callable[[], None]) -> None:
        """Atomically flush and accept a baud candidate behind the RX barrier."""
        with self._callback_submission_lock:
            self.decoder_worker.flush_callbacks(timeout)
            self.raise_if_failed()
            accept()
            if self.raw_worker is not None:
                self.raw_worker.enable_delivery()

    def raise_if_failed(self) -> None:
        with self._failure_lock:
            error = self._fatal_error
        if error is not None:
            raise error
        self.decoder_worker.raise_if_failed()
        if self.raw_worker is not None:
            self.raw_worker.raise_if_failed()
        if self._opened.is_set() and self._stop.is_set():
            raise WorkerTerminatedError("serial worker termination requested unexpectedly")
        if self._opened.is_set() and not self.alive and not self._stop.is_set():
            raise WorkerTerminatedError("serial worker terminated unexpectedly")

    def _record_failure(self, error: BaseException) -> None:
        with self._failure_lock:
            if self._fatal_error is None:
                self._fatal_error = error
            recorded = self._fatal_error
        self.router.fail(recorded)

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
        first_error: BaseException | None = None
        self._stop.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            first_error = WorkerTerminatedError("serial worker failed to terminate")
        try:
            self.decoder_worker.close(timeout)
        except BaseException as error:
            if first_error is None:
                first_error = error
        if self.raw_worker is not None:
            try:
                self.raw_worker.close(timeout)
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def _open_serial(self) -> SerialLike:
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
                    timestamp = time.monotonic_ns()
                    self.statistics.add("bytes_received", received)
                    with self._callback_submission_lock:
                        if self.raw_worker is not None:
                            self.raw_worker.submit(WireChunk(timestamp, "rx", chunk))
                        before_classic = self.decoder.statistics.classic_packets
                        before_noescape = self.decoder.statistics.noescape_packets
                        before_crc = self.decoder.statistics.crc_errors
                        before_malformed = self.decoder.statistics.malformed_packets
                        for payload in self.decoder.feed(chunk):
                            self.decoder_worker.submit(payload)
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
            self._record_failure(error)
        except (serial.SerialException, OSError) as error:
            self._record_failure(DeviceDisconnectedError(str(error)))
        except BaseException as error:
            self._record_failure(WorkerTerminatedError(str(error)))
        finally:
            while True:
                try:
                    request = self._requests.get_nowait()
                except queue.Empty:
                    break
                with self._failure_lock:
                    fatal_error = self._fatal_error
                request.error = fatal_error or WorkerTerminatedError("serial worker stopped")
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
                    if self.raw_worker is not None:
                        with self._callback_submission_lock:
                            self.raw_worker.submit(
                                WireChunk(time.monotonic_ns(), "tx", request.packet)
                            )
                    self.statistics.add("bytes_transmitted", len(view))
                    LOGGER.debug("TX %s", request.packet.hex(" "))
            except BaseException as error:
                request.error = error
            finally:
                request.done.set()
