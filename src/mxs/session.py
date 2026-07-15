"""Shared device session and explicit X4M200 state machine."""

import logging
import queue
import threading
import time
from collections.abc import Callable
from contextlib import suppress

from .commands import (
    build_ping,
    build_set_baudrate,
    build_set_dac_max,
    build_set_dac_min,
    build_set_downconversion,
    build_set_fps,
    build_set_frame_area,
    build_set_frame_area_offset,
    build_set_iterations,
    build_set_pulses_per_step,
    build_set_sensor_mode,
    build_set_tx_center_frequency,
    build_set_tx_power,
    build_x4_init,
)
from .constants import DeviceState, SensorMode
from .diagnostics import StatisticsTracker
from .errors import BaudDetectionError, InvalidDeviceStateError, WorkerTerminatedError
from .expectations import ResponseExpectation
from .models import Ack, CirFrame, Pong, Reply, SessionStatistics, X4Config
from .router import CommandManager, FrameSubscription, MessageRouter, QueuePolicy
from .transport import SerialWorker, WireChunk

LOGGER = logging.getLogger(__name__)


class DeviceSession:
    def __init__(
        self,
        port: str,
        baudrate: str | int = "auto",
        *,
        frame_queue_size: int = 256,
        overflow_policy: QueuePolicy = "error",
        command_timeout: float = 2.0,
        raw_chunk_callback: Callable[[bytes], None] | None = None,
        wire_chunk_callback: Callable[[WireChunk], None] | None = None,
    ) -> None:
        if baudrate != "auto" and baudrate not in (115200, 921600):
            raise ValueError("baudrate must be 'auto', 115200, or 921600")
        self.port = port
        self.requested_baudrate = baudrate
        self.detected_baudrate: int | None = None
        self.command_timeout = command_timeout
        self.raw_chunk_callback = raw_chunk_callback
        self.wire_chunk_callback = wire_chunk_callback
        self.state = DeviceState.CLOSED
        self.config: X4Config | None = None
        self.statistics_tracker = StatisticsTracker()
        self._frame_queue_size: int = frame_queue_size
        self._overflow_policy: QueuePolicy = overflow_policy
        self._reprobe_all_baudrates = False
        self.operation_lock = threading.RLock()
        self.filesystem_lock = self.operation_lock
        self.output_state_cache: dict[int, int] = {}
        self.command_manager: CommandManager
        self.router: MessageRouter
        self.frames: FrameSubscription
        self._build_runtime()
        self.worker: SerialWorker | None = None

    @property
    def frame_queue_size(self) -> int:
        return self._frame_queue_size

    @property
    def overflow_policy(self) -> QueuePolicy:
        return self._overflow_policy

    def _build_runtime(self) -> None:
        """Build all per-open objects so a closed device can be reopened safely."""
        self.command_manager = CommandManager(
            self.statistics_tracker, lambda: self.state.name, self._desynchronize
        )
        self.router = MessageRouter(
            self.statistics_tracker,
            self.command_manager,
            lambda: self.config.frame_area if self.config else (0.0, 0.0),
            lambda: self.config.downconversion if self.config else False,
        )
        self.router.fatal_callback = self._fatal_error
        self.frames = self.router.subscribe(self._frame_queue_size, self._overflow_policy)

    def open(self) -> None:
        with self.operation_lock:
            self._open_locked()

    def _open_locked(self) -> None:
        self._require(DeviceState.CLOSED)
        self.invalidate_output_state()
        candidates = (
            (115200, 921600)
            if self.requested_baudrate == "auto" or self._reprobe_all_baudrates
            else (int(self.requested_baudrate),)
        )
        failures: list[str] = []
        for baudrate in candidates:
            with suppress(BaseException):
                self.router.close()
            self._build_runtime()
            worker = self._create_worker(baudrate)
            try:
                self._probe_candidate(worker)
                self.worker = worker
                self.detected_baudrate = baudrate
                self._transition(DeviceState.OPEN)
                self._reprobe_all_baudrates = False
                LOGGER.info("detected %d baud", baudrate)
                return
            except BaseException as error:
                failures.append(f"{baudrate}: {error}")
                cleanup_error = self._close_candidate(worker)
                if cleanup_error is not None:
                    raise cleanup_error from error
        raise BaudDetectionError("; ".join(failures))

    def _create_worker(self, baudrate: int) -> SerialWorker:
        return SerialWorker(
            self.port,
            baudrate,
            self.router,
            self.statistics_tracker,
            raw_chunk_callback=self.raw_chunk_callback,
            wire_chunk_callback=self.wire_chunk_callback,
        )

    def _probe_candidate(self, worker: SerialWorker) -> None:
        baseline = self.router.valid_packet_count
        worker.start()
        deadline = time.monotonic() + (0.7 if self.requested_baudrate == "auto" else 0.1)
        while time.monotonic() < deadline and self.router.valid_packet_count == baseline:
            time.sleep(0.01)
        if self.router.valid_packet_count == baseline:
            self.command_manager.execute(
                "PING",
                build_ping(),
                worker.send,
                self.command_timeout,
                expect_pong=True,
            )

    def _close_candidate(self, worker: SerialWorker) -> BaseException | None:
        cleanup_error: BaseException | None = None
        try:
            worker.close()
        except BaseException as error:
            cleanup_error = error
        with suppress(BaseException):
            self.router.close()
        if worker.owned_workers_alive:
            self.worker = worker
            self.state = DeviceState.ERROR
            return cleanup_error or WorkerTerminatedError(
                "failed baud candidate left an owned worker alive"
            )
        self.worker = None
        self.state = DeviceState.CLOSED
        return cleanup_error

    def configure(self, config: X4Config) -> None:
        with self.operation_lock:
            self._configure_locked(config)

    def _configure_locked(self, config: X4Config) -> None:
        # Reference: ./Legacy-SW/ModuleConnector/Latest_MC_examples/PYTHON/
        # xt_modules_plot_record_playback_radar_raw_data_message_2D.py (`configure_x4`).
        self._require(DeviceState.OPEN, DeviceState.STOPPED)
        self.config = config
        self._command("STOP", build_set_sensor_mode(SensorMode.STOP))
        self._transition(DeviceState.STOPPED)
        self._drain_frames(0.2)
        self._command("MANUAL", build_set_sensor_mode(SensorMode.MANUAL))
        self._transition(DeviceState.MANUAL)
        commands = (
            ("X4 INIT", build_x4_init()),
            ("FPS 0", build_set_fps(0)),
            ("DOWNCONVERSION", build_set_downconversion(config.downconversion)),
            ("DAC MIN", build_set_dac_min(config.dac_min)),
            ("DAC MAX", build_set_dac_max(config.dac_max)),
            ("ITERATIONS", build_set_iterations(config.iterations)),
            ("TX CENTER FREQUENCY", build_set_tx_center_frequency(config.tx_center_frequency)),
            ("TX POWER", build_set_tx_power(config.tx_power)),
            ("PULSES PER STEP", build_set_pulses_per_step(config.pulses_per_step)),
            ("FRAME AREA OFFSET", build_set_frame_area_offset(config.frame_area_offset)),
            ("FRAME AREA", build_set_frame_area(*config.frame_area)),
        )
        for name, packet in commands:
            self._command(name, packet)
        self._drain_frames(0.1)
        self.router.reset_frame_counters()
        self._transition(DeviceState.CONFIGURED)
        LOGGER.info("configured X4M200: %s", config)

    def start(self, first_frame_timeout: float = 2.0) -> None:
        with self.operation_lock:
            self._start_locked(first_frame_timeout)

    def _start_locked(self, first_frame_timeout: float) -> None:
        self._require(DeviceState.CONFIGURED)
        if self.config is None:
            raise InvalidDeviceStateError("no X4 configuration is available")
        self.router.reset_frame_counters()
        baseline_frames = self.statistics_tracker.snapshot().frames_received
        self._command("START FPS", build_set_fps(self.config.fps))
        self._transition(DeviceState.STREAMING)
        deadline = time.monotonic() + first_frame_timeout
        while self.statistics_tracker.snapshot().frames_received == baseline_frames:
            if time.monotonic() >= deadline:
                self.stop()
                raise WorkerTerminatedError("no CIR frame arrived after starting")
            time.sleep(0.005)
        LOGGER.info("capture started at %.3f FPS", self.config.fps)

    def stop(self) -> None:
        with self.operation_lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self.state in (DeviceState.CLOSED, DeviceState.CLOSING):
            return
        if self.worker is not None and self.worker.alive:
            if self.state is DeviceState.STREAMING:
                self._best_effort("FPS 0", build_set_fps(0))
            self._best_effort("STOP", build_set_sensor_mode(SensorMode.STOP))
        if self.state not in (DeviceState.ERROR, DeviceState.DESYNCHRONIZED):
            self._transition(DeviceState.STOPPED)
        LOGGER.info("capture stopped")

    def switch_to_high_baudrate(self) -> None:
        """Perform the source-verified 115200 to 921600 transition."""
        self.switch_baudrate(921600)

    def switch_baudrate(self, baudrate: int) -> None:
        """Change both ends using the direct command, then verify at the new rate."""
        with self.operation_lock:
            self._switch_baudrate_locked(baudrate)

    def _switch_baudrate_locked(self, baudrate: int) -> None:
        # Reference: ./Legacy-SW/MCPWrapper/mcp_wrapper_1.3.1/examples/generic/src/main.cpp
        if baudrate not in (115200, 921600):
            raise ValueError("supported baudrates are 115200 and 921600")
        self._require(DeviceState.OPEN, DeviceState.STOPPED)
        if self.worker is None:
            raise InvalidDeviceStateError("serial worker is unavailable")
        if baudrate == self.detected_baudrate:
            return
        self._command("STOP", build_set_sensor_mode(SensorMode.STOP))
        self._command(f"SET BAUD {baudrate}", build_set_baudrate(baudrate))
        self.worker.set_baudrate(baudrate)
        time.sleep(0.05)
        try:
            self.execute("VERIFY BAUD", build_ping(), ResponseExpectation(Pong))
        except BaseException:
            self.detected_baudrate = None
            self._reprobe_all_baudrates = True
            raise
        self.detected_baudrate = baudrate

    def read_frame(self, timeout: float | None = None) -> CirFrame:
        self._require(DeviceState.STREAMING)
        try:
            item = self.frames.queue.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError("timed out waiting for a CIR frame") from error
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        with self.operation_lock:
            self._close_locked(passive=False)

    def _close_locked(self, *, passive: bool) -> None:
        if self.state is DeviceState.CLOSED:
            return
        self._transition(DeviceState.CLOSING)
        worker = self.worker
        first_error: BaseException | None = None
        if worker is not None:
            if worker.alive and not passive:
                self._best_effort("FPS 0", build_set_fps(0))
                self._best_effort("STOP", build_set_sensor_mode(SensorMode.STOP))
            try:
                worker.close()
            except BaseException as error:
                first_error = error
        try:
            self.router.close()
        except BaseException as error:
            if first_error is None:
                first_error = error
        finally:
            self.invalidate_output_state()
        if worker is not None and worker.owned_workers_alive:
            self.worker = worker
            self._transition(DeviceState.ERROR)
            if first_error is None:
                first_error = WorkerTerminatedError("owned worker remains alive after close")
        else:
            self.worker = None
            self._transition(DeviceState.CLOSED)
        if first_error is not None:
            raise first_error

    def close_passive(self) -> None:
        """Close without transmitting; used only by sniffing and probing."""
        with self.operation_lock:
            self._close_locked(passive=True)

    def recover(self) -> None:
        """Discard a desynchronized transport and reopen in a known STOP state."""
        with self.operation_lock:
            self._recover_locked()

    def _recover_locked(self) -> None:
        if self.state is not DeviceState.DESYNCHRONIZED:
            raise InvalidDeviceStateError("recover() is only valid after a command timeout")
        if self.worker is not None:
            try:
                self.worker.close()
            except BaseException:
                if self.worker.owned_workers_alive:
                    self._transition(DeviceState.ERROR)
                    raise
        self.router.close()
        if self.worker is not None and self.worker.owned_workers_alive:
            self._transition(DeviceState.ERROR)
            raise WorkerTerminatedError("cannot recover while an owned worker remains alive")
        self.worker = None
        self._transition(DeviceState.CLOSED)
        self.open()
        self._command("RECOVER STOP", build_set_sensor_mode(SensorMode.STOP))
        self._transition(DeviceState.STOPPED)

    def invalidate_output_state(self) -> None:
        self.output_state_cache.clear()

    def statistics(self) -> SessionStatistics:
        return self.statistics_tracker.snapshot()

    def recording_failed(self, error: BaseException) -> None:
        """Promote an asynchronous recorder failure to a fatal session error."""
        self.router.fail(error)

    def _command(self, name: str, packet: bytes) -> Ack:
        if self.worker is None or not self.worker.alive:
            raise WorkerTerminatedError("serial worker is not running")
        response = self.command_manager.execute(
            name, packet, self.worker.send, self.command_timeout
        )
        if not isinstance(response, Ack):  # pragma: no cover - type invariant
            raise WorkerTerminatedError(f"{name} did not receive ACK")
        return response

    def execute(
        self, name: str, packet: bytes, expectation: ResponseExpectation
    ) -> Ack | Reply | Pong:
        if self.worker is None or not self.worker.alive:
            raise WorkerTerminatedError("serial worker is not running")
        return self.command_manager.execute(
            name,
            packet,
            self.worker.send,
            self.command_timeout,
            expectation=expectation,
        )

    def _best_effort(self, name: str, packet: bytes) -> None:
        try:
            self._command(name, packet)
        except BaseException as error:
            LOGGER.debug("best-effort %s failed: %s", name, error)

    def _drain_frames(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            with suppress(queue.Empty):
                self.frames.queue.get(timeout=0.01)
        while True:
            try:
                self.frames.queue.get_nowait()
            except queue.Empty:
                return

    def _require(self, *states: DeviceState) -> None:
        if self.state not in states:
            names = ", ".join(state.name for state in states)
            raise InvalidDeviceStateError(f"state {self.state.name}; expected {names}")

    def _transition(self, state: DeviceState) -> None:
        LOGGER.info("state %s -> %s", self.state.name, state.name)
        self.state = state

    def _fatal_error(self, error: BaseException) -> None:
        if self.state not in (DeviceState.CLOSING, DeviceState.CLOSED):
            LOGGER.error("device session failed: %s", error)
            self._transition(DeviceState.ERROR)

    def _desynchronize(self, error: BaseException) -> None:
        LOGGER.error("command timeout desynchronized device session: %s", error)
        if self.state not in (DeviceState.CLOSING, DeviceState.CLOSED):
            self._transition(DeviceState.DESYNCHRONIZED)
        if self.worker is not None and self.worker.alive:
            with suppress(BaseException):
                self.worker.close()
