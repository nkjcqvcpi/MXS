"""Synchronous public X4M200 API."""

from collections.abc import Iterator

from .constants import DeviceState
from .models import CirFrame, SessionStatistics, X4Config
from .router import QueuePolicy
from .session import DeviceSession
from .transport import SerialFactory


class X4M200:
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

    @property
    def detected_baudrate(self) -> int | None:
        return self._session.detected_baudrate

    @property
    def state(self) -> DeviceState:
        return self._session.state

    def open(self) -> None:
        self._session.open()

    def configure(self, config: X4Config) -> None:
        self._session.configure(config)

    def start(self) -> None:
        self._session.start()

    def stop(self) -> None:
        self._session.stop()

    def switch_to_high_baudrate(self) -> None:
        self._session.switch_to_high_baudrate()

    def read_frame(self, timeout: float | None = None) -> CirFrame:
        return self._session.read_frame(timeout)

    def frames(self) -> Iterator[CirFrame]:
        while True:
            yield self.read_frame()

    def statistics(self) -> SessionStatistics:
        return self._session.statistics()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> X4M200:
        self.open()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
