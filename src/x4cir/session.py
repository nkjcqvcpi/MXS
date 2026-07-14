"""Shared device session and explicit X4M200 state machine."""

import logging
import queue
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
from .models import Ack, CirFrame, SessionStatistics, X4Config
from .router import CommandManager, FrameSubscription, MessageRouter, QueuePolicy
from .transport import SerialFactory, SerialWorker

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
        serial_factory: SerialFactory | None = None,
        raw_chunk_callback: Callable[[bytes], None] | None = None,
    ) -> None:
        if baudrate != "auto" and baudrate not in (115200, 921600):
            raise ValueError("baudrate must be 'auto', 115200, or 921600")
        self.port = port
        self.requested_baudrate = baudrate
        self.detected_baudrate: int | None = None
        self.command_timeout = command_timeout
        self.serial_factory = serial_factory
        self.raw_chunk_callback = raw_chunk_callback
        self.state = DeviceState.CLOSED
        self.config: X4Config | None = None
        self.statistics_tracker = StatisticsTracker()
        self.command_manager = CommandManager(self.statistics_tracker, lambda: self.state.name)
        self.router = MessageRouter(
            self.statistics_tracker,
            self.command_manager,
            lambda: self.config.frame_area if self.config else (0.0, 0.0),
            lambda: self.config.downconversion if self.config else False,
        )
        self.router.fatal_callback = self._fatal_error
        self.frames: FrameSubscription = self.router.subscribe(frame_queue_size, overflow_policy)
        self.worker: SerialWorker | None = None

    def open(self) -> None:
        self._require(DeviceState.CLOSED)
        candidates = (
            (115200, 921600)
            if self.requested_baudrate == "auto"
            else (int(self.requested_baudrate),)
        )
        failures: list[str] = []
        for baudrate in candidates:
            baseline = self.router.valid_packet_count
            worker = SerialWorker(
                self.port,
                baudrate,
                self.router,
                self.statistics_tracker,
                serial_factory=self.serial_factory,
                raw_chunk_callback=self.raw_chunk_callback,
            )
            try:
                worker.start()
                self.worker = worker
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
                self.detected_baudrate = baudrate
                self._transition(DeviceState.OPEN)
                LOGGER.info("detected %d baud", baudrate)
                return
            except BaseException as error:
                failures.append(f"{baudrate}: {error}")
                with suppress(BaseException):
                    worker.close()
                self.worker = None
        raise BaudDetectionError("; ".join(failures))

    def configure(self, config: X4Config) -> None:
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
        self.router.last_counter = None
        self._transition(DeviceState.CONFIGURED)
        LOGGER.info("configured X4M200: %s", config)

    def start(self, first_frame_timeout: float = 2.0) -> None:
        self._require(DeviceState.CONFIGURED)
        if self.config is None:
            raise InvalidDeviceStateError("no X4 configuration is available")
        self._command("START FPS", build_set_fps(self.config.fps))
        self._transition(DeviceState.STREAMING)
        deadline = time.monotonic() + first_frame_timeout
        while self.frames.queue.empty():
            if time.monotonic() >= deadline:
                self.stop()
                raise WorkerTerminatedError("no CIR frame arrived after starting")
            time.sleep(0.005)
        LOGGER.info("capture started at %.3f FPS", self.config.fps)

    def stop(self) -> None:
        if self.state in (DeviceState.CLOSED, DeviceState.CLOSING):
            return
        if self.worker is not None and self.worker.alive:
            if self.state is DeviceState.STREAMING:
                self._best_effort("FPS 0", build_set_fps(0))
            self._best_effort("STOP", build_set_sensor_mode(SensorMode.STOP))
        if self.state is not DeviceState.ERROR:
            self._transition(DeviceState.STOPPED)
        LOGGER.info("capture stopped")

    def switch_to_high_baudrate(self) -> None:
        """Perform the source-verified 115200 to 921600 transition."""
        # Reference: ./Legacy-SW/MCPWrapper/mcp_wrapper_1.3.1/examples/generic/src/main.cpp
        self._require(DeviceState.OPEN, DeviceState.STOPPED)
        if self.worker is None:
            raise InvalidDeviceStateError("serial worker is unavailable")
        self._command("STOP", build_set_sensor_mode(SensorMode.STOP))
        self._command("SET BAUD 921600", build_set_baudrate(921600))
        self.worker.set_baudrate(921600)
        time.sleep(0.05)
        self._command("STOP AT 921600", build_set_sensor_mode(SensorMode.STOP))
        self.detected_baudrate = 921600

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
        if self.state is DeviceState.CLOSED:
            return
        self._transition(DeviceState.CLOSING)
        if self.worker is not None:
            if self.worker.alive:
                self._best_effort("FPS 0", build_set_fps(0))
                self._best_effort("STOP", build_set_sensor_mode(SensorMode.STOP))
            self.worker.close()
        self.router.close()
        self._transition(DeviceState.CLOSED)

    def close_passive(self) -> None:
        """Close without transmitting; used only by sniffing and probing."""
        if self.state is DeviceState.CLOSED:
            return
        self._transition(DeviceState.CLOSING)
        if self.worker is not None:
            self.worker.close()
        self.router.close()
        self._transition(DeviceState.CLOSED)

    def statistics(self) -> SessionStatistics:
        return self.statistics_tracker.snapshot()

    def _command(self, name: str, packet: bytes) -> Ack:
        if self.worker is None or not self.worker.alive:
            raise WorkerTerminatedError("serial worker is not running")
        response = self.command_manager.execute(
            name, packet, self.worker.send, self.command_timeout
        )
        if not isinstance(response, Ack):  # pragma: no cover - type invariant
            raise WorkerTerminatedError(f"{name} did not receive ACK")
        return response

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
