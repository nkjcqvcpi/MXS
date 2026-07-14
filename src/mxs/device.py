"""Synchronous public X4M200 API."""

from collections.abc import Callable, Iterator

from .capabilities import CapabilityProbeFailure, DeviceCapabilities
from .constants import DeviceState, SystemInfoCode
from .discovery import discover_port
from .errors import CommandRejectedError, CommandTimeoutError, ProtocolError
from .interfaces import (
    FilesystemInterface,
    GpioInterface,
    ModuleInterface,
    NoisemapInterface,
    OutputsInterface,
    ParametersInterface,
    ProfileInterface,
    UnsafeInterface,
    XepInterface,
)
from .models import CirFrame, SessionStatistics, X4Config
from .router import QueuePolicy
from .session import DeviceSession
from .transport import SerialFactory, WireChunk


class X4M200:
    def __init__(
        self,
        port: str | None = None,
        baudrate: str | int = "auto",
        *,
        frame_queue_size: int = 256,
        overflow_policy: QueuePolicy = "error",
        command_timeout: float = 2.0,
        serial_factory: SerialFactory | None = None,
        raw_chunk_callback: Callable[[bytes], None] | None = None,
        wire_chunk_callback: Callable[[WireChunk], None] | None = None,
    ) -> None:
        self._session = DeviceSession(
            port or discover_port(),
            baudrate,
            frame_queue_size=frame_queue_size,
            overflow_policy=overflow_policy,
            command_timeout=command_timeout,
            serial_factory=serial_factory,
            raw_chunk_callback=raw_chunk_callback,
            wire_chunk_callback=wire_chunk_callback,
        )
        self.module = ModuleInterface(self._session)
        self.profile = ProfileInterface(self._session)
        self.outputs = OutputsInterface(self._session)
        self.xep = XepInterface(self._session)
        self.gpio = GpioInterface(self._session)
        self.noisemap = NoisemapInterface(self._session)
        self.parameters = ParametersInterface(self._session)
        self.filesystem = FilesystemInterface(self._session)
        self.unsafe = UnsafeInterface(self._session)

    @property
    def detected_baudrate(self) -> int | None:
        return self._session.detected_baudrate

    @property
    def state(self) -> DeviceState:
        return self._session.state

    @property
    def messages(self):
        return self._session.router.messages

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

    def recording_failed(self, error: BaseException) -> None:
        self._session.recording_failed(error)

    def close(self) -> None:
        self._session.close()

    def recover(self) -> None:
        self._session.recover()

    def probe_capabilities(self) -> DeviceCapabilities:
        values: dict[str, str | None] = {}
        failures: list[CapabilityProbeFailure] = []
        fields = {
            "item_number": SystemInfoCode.ITEM_NUMBER,
            "order_code": SystemInfoCode.ORDER_CODE,
            "firmware_id": SystemInfoCode.FIRMWARE_ID,
            "firmware_version": SystemInfoCode.VERSION,
            "build": SystemInfoCode.BUILD,
            "serial_number": SystemInfoCode.SERIAL_NUMBER,
            "version_list": SystemInfoCode.VERSION_LIST,
        }
        for field, code in fields.items():
            try:
                values[field] = self.module.get_system_info(code)
            except (CommandRejectedError, CommandTimeoutError, ProtocolError, ValueError) as error:
                values[field] = None
                category = (
                    "firmware_rejection"
                    if isinstance(error, CommandRejectedError)
                    else "timeout"
                    if isinstance(error, CommandTimeoutError)
                    else "malformed_reply"
                )
                failures.append(CapabilityProbeFailure(field, category, str(error)))
                if isinstance(error, CommandTimeoutError):
                    failures.append(
                        CapabilityProbeFailure(
                            "remaining_probes",
                            "not_tested",
                            "session desynchronized after timeout",
                        )
                    )
                    break
        for field in fields:
            values.setdefault(field, None)
        profile_id = None
        sensor_mode = None
        if self.state is not DeviceState.DESYNCHRONIZED:
            try:
                profile_id = self.profile.get_profileid()
            except (CommandRejectedError, CommandTimeoutError, ProtocolError, ValueError) as error:
                failures.append(
                    CapabilityProbeFailure("profile_id", type(error).__name__, str(error))
                )
            try:
                sensor_mode = int(self.profile.get_sensor_mode())
            except (CommandRejectedError, CommandTimeoutError, ProtocolError, ValueError) as error:
                failures.append(
                    CapabilityProbeFailure("sensor_mode", type(error).__name__, str(error))
                )
        return DeviceCapabilities(
            item_number=values.get("item_number"),
            order_code=values.get("order_code"),
            firmware_id=values.get("firmware_id"),
            firmware_version=values.get("firmware_version"),
            build=values.get("build"),
            serial_number=values.get("serial_number"),
            version_list=values.get("version_list"),
            profile_id=profile_id,
            sensor_mode=sensor_mode,
            probe_failures=tuple(failures),
        )

    def __getattr__(self, name: str):
        for interface_name in (
            "module",
            "profile",
            "outputs",
            "xep",
            "gpio",
            "noisemap",
            "parameters",
            "filesystem",
        ):
            interface = self.__dict__.get(interface_name)
            if interface is not None and hasattr(interface, name):
                return getattr(interface, name)
        raise AttributeError(name)

    def __enter__(self) -> X4M200:
        self.open()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
