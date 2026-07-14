"""Message routing, command completion, and bounded frame delivery."""

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from typing import Literal, TypeVar, cast

import numpy as np
from numpy.typing import NDArray

from .constants import (
    CONTENT_ID_NOISEMAP_BYTE,
    CONTENT_ID_NOISEMAP_FLOAT,
    CONTENT_ID_PULSE_DOPPLER_BYTE,
    CONTENT_ID_PULSE_DOPPLER_FLOAT,
)
from .diagnostics import StatisticsTracker
from .errors import (
    CommandRejectedError,
    CommandTimeoutError,
    FrameBackpressureError,
    ReplyMismatchError,
    SessionDesynchronizedError,
    WorkerTerminatedError,
)
from .expectations import ACK, PONG, ResponseExpectation
from .message_hub import MessageHub
from .messages import data_float_to_iq
from .models import (
    Ack,
    BasebandAmplitudePhaseMessage,
    BasebandIqMessage,
    CirFrame,
    DataFloatMessage,
    ErrorResponse,
    MatrixMessage,
    Message,
    NormalizedMovementList,
    Pong,
    Reply,
    RespirationDetectionList,
    RespirationMovingList,
    RespirationStatus,
    SleepStatus,
    UnknownMessage,
    VitalSigns,
)

LOGGER = logging.getLogger(__name__)
QueuePolicy = Literal["error", "drop_oldest", "drop_newest", "block_with_timeout"]
T = TypeVar("T")


class FrameSubscription:
    def __init__(
        self,
        capacity: int,
        policy: QueuePolicy,
        statistics: StatisticsTracker,
        block_timeout: float = 0.1,
    ) -> None:
        if capacity <= 0:
            raise ValueError("frame queue capacity must be positive")
        self.queue: queue.Queue[CirFrame | BaseException] = queue.Queue(capacity)
        self.policy = policy
        self.statistics = statistics
        self.block_timeout = block_timeout
        self.closed = False
        self._pending_drops = 0

    def publish(self, frame: CirFrame) -> None:
        if self.closed:
            return
        if self._pending_drops:
            frame = replace(frame, sequence_gap=frame.sequence_gap + self._pending_drops)
            self._pending_drops = 0
        try:
            self.queue.put_nowait(frame)
        except queue.Full:
            self.statistics.add("queue_overflows")
            if self.policy == "error":
                error = FrameBackpressureError("lossless frame queue overflow")
                self.closed = True
                self._replace_with_error(error)
                raise error from None
            if self.policy == "drop_newest":
                self._pending_drops += 1
                self.statistics.add("consumer_drops")
                return
            if self.policy == "block_with_timeout":
                try:
                    self.queue.put(frame, timeout=self.block_timeout)
                    return
                except queue.Full:
                    error = FrameBackpressureError("frame queue remained full after timeout")
                    self.closed = True
                    self._replace_with_error(error)
                    raise error from None
            with suppress(queue.Empty):
                self.queue.get_nowait()
            self._pending_drops += 1
            self.statistics.add("consumer_drops")
            frame = replace(frame, sequence_gap=frame.sequence_gap + self._pending_drops)
            self._pending_drops = 0
            self.queue.put_nowait(frame)
        self.statistics.maximum("queue_high_water_mark", self.queue.qsize())

    def fail(self, error: BaseException) -> None:
        if not self.closed:
            self.closed = True
            self._replace_with_error(error)

    def _replace_with_error(self, error: BaseException) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.queue.put_nowait(error)


class CommandManager:
    """Serialize commands whose ACKs carry no correlation identifier."""

    def __init__(
        self,
        statistics: StatisticsTracker,
        state_name: Callable[[], str],
        desynchronize: Callable[[BaseException], None] | None = None,
    ) -> None:
        self._statistics = statistics
        self._state_name = state_name
        self._lock = threading.Lock()
        self._condition = threading.Condition()
        self._response: Ack | ErrorResponse | Reply | Pong | BaseException | None = None
        self._pending = False
        self._recent: deque[bytes] = deque(maxlen=8)
        self._expectation: ResponseExpectation | None = None
        self._desynchronized = False
        self._desynchronize = desynchronize

    def route(self, message: Message, raw_payload: bytes) -> bool:
        if not isinstance(message, (Ack, ErrorResponse, Reply, Pong)):
            return False
        self._recent.append(raw_payload[:16])
        with self._condition:
            if not self._pending:
                return False
            if isinstance(message, (Ack, Reply, Pong)) and self._expectation is not None:
                try:
                    self._expectation.validate(message)
                except ReplyMismatchError as error:
                    self._response = error
                    self._condition.notify_all()
                    return True
            self._response = message
            self._condition.notify_all()
        return True

    def fail(self, error: BaseException) -> None:
        with self._condition:
            if self._pending:
                self._response = error
                self._condition.notify_all()

    def execute(
        self,
        name: str,
        packet: bytes,
        sender: Callable[[bytes, float], None],
        timeout: float = 2.0,
        expect_pong: bool = False,
        expectation: ResponseExpectation | None = None,
    ) -> Ack | Reply | Pong:
        if self._desynchronized:
            raise SessionDesynchronizedError("session requires recover() after command timeout")
        expectation = expectation or (PONG if expect_pong else ACK)
        started = time.monotonic()
        with self._lock:
            with self._condition:
                if self._pending:
                    raise RuntimeError("command manager invariant violated")
                self._pending = True
                self._response = None
                self._expectation = expectation
            self._statistics.add("commands_sent")
            try:
                sender(packet, timeout)
                with self._condition:
                    ready = self._condition.wait_for(
                        lambda: self._response is not None,
                        timeout=max(0.0, timeout - (time.monotonic() - started)),
                    )
                    response = self._response
                elapsed = time.monotonic() - started
                self._statistics.maximum("maximum_command_latency_seconds", elapsed)
                if not ready or response is None:
                    self._statistics.add("command_timeouts")
                    error = CommandTimeoutError(f"{name} timed out after {elapsed:.3f}s")
                    self._desynchronized = True
                    desync_error = SessionDesynchronizedError(str(error))
                    if self._desynchronize is not None:
                        self._desynchronize(desync_error)
                    raise error
                response = cast(Ack | ErrorResponse | Reply | Pong | BaseException, response)
                if isinstance(response, BaseException):
                    raise response
                if isinstance(response, ErrorResponse):
                    self._statistics.add("firmware_errors")
                    raise CommandRejectedError(
                        name,
                        packet,
                        response.error_code,
                        elapsed,
                        tuple(self._recent),
                        self._state_name(),
                    )
                expectation.validate(response)
                if isinstance(response, Ack):
                    self._statistics.add("ack_count")
                LOGGER.debug("%s completed in %.3f s", name, elapsed)
                return response
            finally:
                with self._condition:
                    self._pending = False
                    self._response = None
                    self._expectation = None

    def reset(self) -> None:
        with self._condition:
            if self._pending:
                raise RuntimeError("cannot reset command manager with a command in flight")
            self._desynchronized = False
            self._response = None
            self._expectation = None


class MessageRouter:
    def __init__(
        self,
        statistics: StatisticsTracker,
        command_manager: CommandManager,
        frame_area: Callable[[], tuple[float, float]],
        downconversion: Callable[[], bool],
    ) -> None:
        self.statistics = statistics
        self.command_manager = command_manager
        self._frame_area = frame_area
        self._downconversion = downconversion
        self.subscriptions: list[FrameSubscription] = []
        self.events: queue.Queue[Message] = queue.Queue(256)
        self.unknown: queue.Queue[UnknownMessage] = queue.Queue(64)
        self.last_counter: int | None = None
        self.last_counter_by_stream: dict[tuple[type[object], int], int] = {}
        self.valid_packet_count = 0
        self.content_ids: set[int] = set()
        self.message_types: set[str] = set()
        self._lock = threading.Lock()
        self.fatal_callback: Callable[[BaseException], None] | None = None
        self.messages = MessageHub()

    def subscribe(self, capacity: int = 256, policy: QueuePolicy = "error") -> FrameSubscription:
        subscription = FrameSubscription(capacity, policy, self.statistics)
        with self._lock:
            self.subscriptions.append(subscription)
        return subscription

    def route(self, message: Message, raw_payload: bytes) -> None:
        self.valid_packet_count += 1
        self.message_types.add(type(message).__name__)
        if self.command_manager.route(message, raw_payload):
            return
        if isinstance(message, (Ack, ErrorResponse, Reply, Pong)):
            LOGGER.debug("discarding uncorrelated control response %s", type(message).__name__)
            return
        application_counter = getattr(message, "frame_counter", None)
        if isinstance(application_counter, int) and not isinstance(
            message, (DataFloatMessage, BasebandIqMessage)
        ):
            content_id = getattr(message, "content_id", 0)
            self.last_counter_by_stream[(type(message), int(content_id))] = application_counter
        if isinstance(message, DataFloatMessage):
            self.content_ids.add(message.content_id)
            mode: Literal["rf", "iq"] = "iq" if self._downconversion() else "rf"
            samples = data_float_to_iq(message) if mode == "iq" else message.samples
            self._publish_frame(message.frame_counter, message.content_id, mode, samples)
            self.messages.publish("raw_iq" if mode == "iq" else "raw_rf", message)
        elif isinstance(message, BasebandIqMessage):
            self.content_ids.add(message.content_id)
            self._publish_frame(message.frame_counter, message.content_id, "iq", message.samples)
            self.messages.publish("baseband_iq", message)
        elif isinstance(message, BasebandAmplitudePhaseMessage):
            self.messages.publish("baseband_ap", message)
        elif isinstance(message, RespirationStatus):
            self.messages.publish("respiration", message)
        elif isinstance(message, RespirationMovingList):
            self.messages.publish("respiration_moving_list", message)
        elif isinstance(message, RespirationDetectionList):
            self.messages.publish("respiration_detection_list", message)
        elif isinstance(message, NormalizedMovementList):
            self.messages.publish("normalized_movement", message)
        elif isinstance(message, VitalSigns):
            self.messages.publish("vital_signs", message)
        elif isinstance(message, MatrixMessage):
            topic = {
                CONTENT_ID_PULSE_DOPPLER_FLOAT: "pulse_doppler_float",
                CONTENT_ID_PULSE_DOPPLER_BYTE: "pulse_doppler_byte",
                CONTENT_ID_NOISEMAP_FLOAT: "noisemap_float",
                CONTENT_ID_NOISEMAP_BYTE: "noisemap_byte",
            }[message.content_id]
            self.messages.publish(topic, message)
        elif isinstance(message, UnknownMessage):
            self.statistics.add("unknown_packets")
            self._bounded_put(self.unknown, message)
            self.messages.publish("unknown", message)
        else:
            if isinstance(message, SleepStatus):
                self.content_ids.add(0x2375A16C)
                self.messages.publish("sleep", message)
            else:
                self.messages.publish(
                    "system" if type(message).__name__ == "SystemMessage" else "all", message
                )
            self._bounded_put(self.events, message)

    def _publish_frame(
        self,
        counter: int,
        content_id: int,
        mode: Literal["rf", "iq"],
        samples: NDArray[np.float32] | NDArray[np.complex64],
    ) -> None:
        key = (DataFloatMessage if content_id == 0 else BasebandIqMessage, content_id)
        previous = self.last_counter_by_stream.get(key)
        gap = 0 if previous is None else max(0, (counter - previous - 1) & 0xFFFFFFFF)
        if gap > 0x7FFFFFFF:
            gap = 0
        self.last_counter = counter
        self.last_counter_by_stream[key] = counter
        self.statistics.add("frames_received")
        self.statistics.add("frame_counter_gaps", gap)
        frame = CirFrame(
            counter,
            time.monotonic_ns(),
            content_id,
            mode,
            samples,
            self._frame_area(),
            gap,
        )
        with self._lock:
            subscriptions = tuple(self.subscriptions)
        for subscription in subscriptions:
            subscription.publish(frame)

    @staticmethod
    def _bounded_put(target: queue.Queue[T], message: T) -> None:
        try:
            target.put_nowait(message)
        except queue.Full:
            with suppress(queue.Empty):
                target.get_nowait()
            target.put_nowait(message)

    def fail(self, error: BaseException) -> None:
        if self.fatal_callback is not None:
            self.fatal_callback(error)
        self.command_manager.fail(error)
        with self._lock:
            subscriptions = tuple(self.subscriptions)
        for subscription in subscriptions:
            subscription.fail(error)
        self.messages.fail(error)

    def close(self) -> None:
        error = WorkerTerminatedError("device session closed")
        self.command_manager.fail(error)
        with self._lock:
            subscriptions = tuple(self.subscriptions)
        for subscription in subscriptions:
            subscription.fail(error)
        self.messages.fail(error)

    def reset_frame_counters(self) -> None:
        self.last_counter = None
        self.last_counter_by_stream.clear()
