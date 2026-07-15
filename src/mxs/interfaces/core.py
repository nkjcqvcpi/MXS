"""Source-derived X4M200 and XEP command interfaces."""

import os
import struct
from collections.abc import Generator
from contextlib import contextmanager, suppress
from typing import ClassVar, Never

import numpy as np

from ..commands import (
    build_app_action,
    build_app_get,
    build_app_set,
    build_debug_level,
    build_factory_reset,
    build_filesystem,
    build_get_iopin_control,
    build_get_iopin_value,
    build_get_output_control,
    build_get_sensor_mode,
    build_inject_frame,
    build_load_profile,
    build_module_reset,
    build_noisemap,
    build_parameter_file,
    build_ping,
    build_prepare_inject_frame,
    build_set_dac_max,
    build_set_dac_min,
    build_set_detection_zone,
    build_set_downconversion,
    build_set_enable,
    build_set_fps,
    build_set_frame_area,
    build_set_frame_area_offset,
    build_set_iopin_control,
    build_set_iopin_value,
    build_set_iterations,
    build_set_led_control,
    build_set_output_control,
    build_set_prf_div,
    build_set_pulses_per_step,
    build_set_sensor_mode,
    build_set_tx_center_frequency,
    build_set_tx_power,
    build_start_bootloader,
    build_system_info,
    build_system_test,
    build_x4_get,
    build_x4_read,
    build_x4_set_register,
    build_x4_write,
)
from ..constants import (
    CONTENT_ID_DETECTION_ZONE,
    CONTENT_ID_DETECTION_ZONE_LIMITS,
    CONTENT_ID_LED_CONTROL,
    CONTENT_ID_RESPIRATION_EXTENDED,
    CONTENT_ID_SENSITIVITY,
    CONTENT_ID_TX_CENTER_FREQUENCY,
    DeviceState,
    IoPinFeature,
    IoPinSetup,
    SensorMode,
    SystemInfoCode,
    X4Parameter,
)
from ..errors import InvalidDeviceStateError, UnsafeOperationDisabledError, UnsupportedFirmwareError
from ..expectations import ACK, PONG, ResponseExpectation, reply
from ..models import (
    ByteReply,
    DetectionZone,
    DetectionZoneLimits,
    DeviceFile,
    FileIdentifier,
    FileMetadata,
    FloatReply,
    FrameArea,
    IntReply,
    Pong,
    Reply,
    StringReply,
)
from ..session import DeviceSession


class Interface:
    def __init__(self, session: DeviceSession) -> None:
        self._session = session

    def _execute(self, name: str, packet: bytes, expectation: ResponseExpectation):
        return self._session.execute(name, packet, expectation)

    def _ack(self, name: str, packet: bytes) -> None:
        self._execute(name, packet, ACK)

    def _reply(self, name: str, packet: bytes, expectation: ResponseExpectation) -> Reply:
        result = self._execute(name, packet, expectation)
        if not isinstance(result, Reply):
            raise AssertionError("response expectation admitted a non-reply")
        return result

    def _require_unsafe(
        self,
        gate: str,
        *,
        allowed_states: set[DeviceState],
        confirmation: bool | None = None,
        allow_manual: bool = False,
    ) -> None:
        state = getattr(self._session, "state", DeviceState.OPEN)
        if os.environ.get(gate) != "1":
            raise UnsafeOperationDisabledError(
                f"{gate}=1 is required; current state is {state.name}"
            )
        if state is DeviceState.STREAMING:
            raise InvalidDeviceStateError(f"{gate} operation is forbidden while state is STREAMING")
        if state not in allowed_states:
            expected = ", ".join(sorted(state.name for state in allowed_states))
            raise InvalidDeviceStateError(
                f"{gate} operation requires state {expected}; current state is {state.name}"
            )
        worker = getattr(self._session, "worker", None)
        if hasattr(self._session, "worker") and (worker is None or not worker.alive):
            raise InvalidDeviceStateError(f"{gate} operation requires a healthy serial session")
        if confirmation is False:
            raise ValueError(f"explicit confirmation is required for {gate}")
        result = self._reply(
            "unsafe_get_sensor_mode",
            build_get_sensor_mode(),
            reply(ByteReply, 0, element_count=1),
        )
        assert isinstance(result, ByteReply)
        sensor_mode = SensorMode(result.values[0])
        allowed_modes = {SensorMode.STOP}
        if allow_manual:
            allowed_modes.add(SensorMode.MANUAL)
        if sensor_mode not in allowed_modes:
            expected = "STOP or MANUAL" if allow_manual else "STOP"
            raise InvalidDeviceStateError(
                f"{gate} operation requires sensor mode {expected}; "
                f"actual sensor mode is {sensor_mode.name}"
            )

    @contextmanager
    def _unsafe_transaction(
        self,
        gate: str,
        *,
        allowed_states: set[DeviceState],
        confirmation: bool | None = None,
        allow_manual: bool = False,
    ) -> Generator[None]:
        with self._session.operation_lock:
            self._require_unsafe(
                gate,
                allowed_states=allowed_states,
                confirmation=confirmation,
                allow_manual=allow_manual,
            )
            yield


class ModuleInterface(Interface):
    def set_debug_level(self, level: int) -> None:
        self._ack("set_debug_level", build_debug_level(level))

    def set_baudrate(self, baudrate: int) -> None:
        switch = getattr(self._session, "switch_baudrate", None)
        if switch is not None:
            switch(baudrate)
        elif baudrate == 921600:
            self._session.switch_to_high_baudrate()
        else:
            raise ValueError("supported baudrates are 115200 and 921600")

    def ping(self) -> Pong:
        result = self._execute("ping", build_ping(), PONG)
        if not isinstance(result, Pong):
            raise AssertionError("PONG expectation admitted another response")
        return result

    def get_system_info(self, info_code: SystemInfoCode | int) -> str:
        code = int(info_code)
        result = self._reply(
            "get_system_info",
            build_system_info(code),
            reply(StringReply, 0x58, info=code),
        )
        assert isinstance(result, StringReply)
        return result.value

    def module_reset(self) -> None:
        with self._session.operation_lock:
            self._ack("module_reset", build_module_reset())
            self._session.invalidate_output_state()

    def reset(self) -> None:
        with self._session.operation_lock:
            self.module_reset()
            self._session.close_passive()
            self._session.open()


class ProfileInterface(Interface):
    def load_profile(self, profile_id: int) -> None:
        with self._session.operation_lock:
            self._ack("load_profile", build_load_profile(profile_id))
            self._session.invalidate_output_state()

    def set_sensor_mode(self, mode: SensorMode | int, param: int = 0) -> None:
        with self._session.operation_lock:
            self._ack("set_sensor_mode", build_set_sensor_mode(SensorMode(mode), param))

    def get_sensor_mode(self) -> SensorMode:
        result = self._reply(
            "get_sensor_mode", build_get_sensor_mode(), reply(ByteReply, 0, element_count=1)
        )
        assert isinstance(result, ByteReply)
        return SensorMode(result.values[0])

    def get_profileid(self) -> int:
        result = self._reply(
            "get_profileid", build_filesystem(0x74), reply(IntReply, 0, element_count=1)
        )
        assert isinstance(result, IntReply)
        return int(result.values[0])

    def set_sensitivity(self, sensitivity: int) -> None:
        if not 0 <= sensitivity <= 9:
            raise ValueError("sensitivity must be between 0 and 9")
        self._ack(
            "set_sensitivity",
            build_app_set(CONTENT_ID_SENSITIVITY, struct.pack("<I", sensitivity)),
        )

    def get_sensitivity(self) -> int:
        result = self._reply(
            "get_sensitivity",
            build_app_get(CONTENT_ID_SENSITIVITY),
            reply(IntReply, CONTENT_ID_SENSITIVITY, element_count=1),
        )
        assert isinstance(result, IntReply)
        return int(result.values[0])

    def set_tx_center_frequency(self, band: int) -> None:
        if band not in (3, 4):
            raise ValueError("center-frequency band must be 3 or 4")
        self._ack(
            "set_tx_center_frequency",
            build_app_set(CONTENT_ID_TX_CENTER_FREQUENCY, struct.pack("<I", band)),
        )

    def get_tx_center_frequency(self) -> int:
        result = self._reply(
            "get_tx_center_frequency",
            build_app_get(CONTENT_ID_TX_CENTER_FREQUENCY),
            reply(IntReply, CONTENT_ID_TX_CENTER_FREQUENCY, element_count=1),
        )
        assert isinstance(result, IntReply)
        return int(result.values[0])

    def set_detection_zone(self, start: float, end: float) -> None:
        self._ack("set_detection_zone", build_set_detection_zone(start, end))

    def get_detection_zone(self) -> DetectionZone:
        result = self._reply(
            "get_detection_zone",
            build_app_get(CONTENT_ID_DETECTION_ZONE),
            reply(FloatReply, CONTENT_ID_DETECTION_ZONE, element_count=2),
        )
        assert isinstance(result, FloatReply)
        return DetectionZone(float(result.values[0]), float(result.values[1]))

    def get_detection_zone_limits(self) -> DetectionZoneLimits:
        result = self._reply(
            "get_detection_zone_limits",
            build_app_get(CONTENT_ID_DETECTION_ZONE_LIMITS),
            reply(FloatReply, CONTENT_ID_DETECTION_ZONE_LIMITS, element_count=3),
        )
        assert isinstance(result, FloatReply)
        return DetectionZoneLimits(*(float(value) for value in result.values))

    def set_led_control(self, mode: int, intensity: int) -> None:
        self._ack("set_led_control", build_set_led_control(mode, intensity))

    def get_led_control(self) -> int:
        result = self._reply(
            "get_led_control",
            build_app_get(CONTENT_ID_LED_CONTROL),
            reply(ByteReply, CONTENT_ID_LED_CONTROL, element_count=1),
        )
        assert isinstance(result, ByteReply)
        return result.values[0]


class OutputsInterface(Interface):
    _EXCLUSIVE = (
        frozenset((0x0C, 0x0D)),
        frozenset((0x10, 0x11)),
        frozenset((0x12, 0x13)),
    )

    def set_output_control(self, feature: int, control: int) -> None:
        feature = int(feature)
        self._require_supported_feature(feature)
        with self._session.operation_lock:
            group = next((pair for pair in self._EXCLUSIVE if feature in pair), None)
            if group is not None:
                self._synchronize_group(group)
            self._ack("set_output_control", build_set_output_control(feature, control))
            if group is None:
                self._session.output_state_cache[feature] = int(control)
            else:
                self._synchronize_group(group)

    def get_output_control(self, feature: int) -> int:
        feature = int(feature)
        self._require_supported_feature(feature)
        with self._session.operation_lock:
            return self._get_output_control_locked(feature)

    def _get_output_control_locked(self, feature: int) -> int:
        result = self._reply(
            "get_output_control",
            build_get_output_control(feature),
            reply(IntReply, 0, element_count=1),
        )
        assert isinstance(result, IntReply)
        value = int(result.values[0])
        self._session.output_state_cache[feature] = value
        return value

    def _synchronize_group(self, group: frozenset[int]) -> None:
        for related in group:
            self._get_output_control_locked(related)

    @staticmethod
    def _require_supported_feature(feature: int) -> None:
        if feature == CONTENT_ID_RESPIRATION_EXTENDED:
            raise UnsupportedFirmwareError(
                "extended respiration has no authoritative payload layout in local Legacy-SW"
            )

    def set_debug_output_control(self, feature: int, control: int) -> None:
        feature = int(feature)
        self._require_supported_feature(feature)
        with self._session.operation_lock:
            self._ack(
                "set_debug_output_control", build_set_output_control(feature, control, debug=True)
            )

    def get_debug_output_control(self, feature: int) -> int:
        feature = int(feature)
        self._require_supported_feature(feature)
        with self._session.operation_lock:
            result = self._reply(
                "get_debug_output_control",
                build_get_output_control(feature, debug=True),
                reply(IntReply, 0, element_count=1),
            )
            assert isinstance(result, IntReply)
            return int(result.values[0])


class XepInterface(Interface):
    _BYTE_PARAMETERS: ClassVar[frozenset[X4Parameter]] = frozenset(
        {
            X4Parameter.DOWNCONVERSION,
            X4Parameter.TX_CENTER_FREQUENCY,
            X4Parameter.TX_POWER,
            X4Parameter.PRF_DIV,
        }
    )
    _FLOAT_PARAMETERS: ClassVar[frozenset[X4Parameter]] = frozenset(
        {X4Parameter.FPS, X4Parameter.FRAME_AREA, X4Parameter.FRAME_AREA_OFFSET}
    )

    def _get(self, parameter: X4Parameter | int, count: int = 1):
        parameter_id = int(parameter)
        cls = (
            FloatReply
            if parameter in self._FLOAT_PARAMETERS
            else ByteReply
            if parameter in self._BYTE_PARAMETERS
            else IntReply
        )
        result = self._reply(
            f"x4driver_get_{parameter_id:02x}",
            build_x4_get(parameter_id),
            reply(cls, parameter_id, element_count=count),
        )
        if isinstance(result, ByteReply):
            return result.values[0] if count == 1 else result.values
        if isinstance(result, (IntReply, FloatReply)):
            return result.values[0].item() if count == 1 else result.values.copy()
        raise AssertionError("unexpected X4 reply")

    def x4driver_init(self) -> None:
        from ..commands import build_x4_init

        self._ack("x4driver_init", build_x4_init())

    def x4driver_get_fps(self) -> float:
        return float(self._get(X4Parameter.FPS))

    def x4driver_get_iterations(self) -> int:
        return int(self._get(X4Parameter.ITERATIONS))

    def x4driver_get_pulses_per_step(self) -> int:
        return int(self._get(X4Parameter.PULSES_PER_STEP))

    def x4driver_get_dac_min(self) -> int:
        return int(self._get(X4Parameter.DAC_MIN))

    def x4driver_get_dac_max(self) -> int:
        return int(self._get(X4Parameter.DAC_MAX))

    def x4driver_get_tx_power(self) -> int:
        return int(self._get(X4Parameter.TX_POWER))

    def x4driver_get_downconversion(self) -> bool:
        return bool(self._get(X4Parameter.DOWNCONVERSION))

    def x4driver_get_frame_bin_count(self) -> int:
        return int(self._get(0x26))

    def x4driver_get_frame_area(self) -> FrameArea:
        values = self._get(X4Parameter.FRAME_AREA, 2)
        if not isinstance(values, np.ndarray):
            raise AssertionError("frame-area getter did not return an array")
        return FrameArea(float(values[0]), float(values[1]))

    def x4driver_get_frame_area_offset(self) -> float:
        return float(self._get(X4Parameter.FRAME_AREA_OFFSET))

    def x4driver_get_tx_center_frequency(self) -> int:
        return int(self._get(X4Parameter.TX_CENTER_FREQUENCY))

    def x4driver_get_prf_div(self) -> int:
        return int(self._get(X4Parameter.PRF_DIV))

    def x4driver_set_prf_div(self, value: int) -> None:
        self._ack("x4driver_set_prf_div", build_set_prf_div(value))

    def _unsupported_xep_control(self, *_args: object) -> Never:
        raise UnsupportedFirmwareError("XEP control has no wire producer in local Legacy-SW")

    set_normalization = _unsupported_xep_control
    get_normalization = _unsupported_xep_control
    set_phase_noise_correction = _unsupported_xep_control
    get_phase_noise_correction = _unsupported_xep_control
    set_decimation_factor = _unsupported_xep_control
    get_decimation_factor = _unsupported_xep_control
    set_number_format = _unsupported_xep_control
    get_number_format = _unsupported_xep_control
    set_legacy_output = _unsupported_xep_control
    get_legacy_output = _unsupported_xep_control

    def x4driver_set_fps(self, value: float) -> None:
        self._ack("x4driver_set_fps", build_set_fps(value))

    def x4driver_set_iterations(self, value: int) -> None:
        self._ack("x4driver_set_iterations", build_set_iterations(value))

    def x4driver_set_pulses_per_step(self, value: int) -> None:
        self._ack("x4driver_set_pulses_per_step", build_set_pulses_per_step(value))

    def x4driver_set_dac_min(self, value: int) -> None:
        self._ack("x4driver_set_dac_min", build_set_dac_min(value))

    def x4driver_set_dac_max(self, value: int) -> None:
        self._ack("x4driver_set_dac_max", build_set_dac_max(value))

    def x4driver_set_tx_power(self, value: int) -> None:
        self._ack("x4driver_set_tx_power", build_set_tx_power(value))

    def x4driver_set_downconversion(self, value: bool) -> None:
        self._ack("x4driver_set_downconversion", build_set_downconversion(value))

    def x4driver_set_frame_area(self, start: float, end: float) -> None:
        self._ack("x4driver_set_frame_area", build_set_frame_area(start, end))

    def x4driver_set_frame_area_offset(self, value: float) -> None:
        self._ack("x4driver_set_frame_area_offset", build_set_frame_area_offset(value))

    def x4driver_set_tx_center_frequency(self, value: int) -> None:
        self._ack("x4driver_set_tx_center_frequency", build_set_tx_center_frequency(value))

    def x4driver_set_enable(self, value: bool) -> None:
        self._ack("x4driver_set_enable", build_set_enable(value))


class GpioInterface(Interface):
    @staticmethod
    def _pin(pin: int) -> int:
        if not 0 <= pin <= 0xFFFFFFFF:
            raise ValueError("pin must be an unsigned 32-bit integer")
        return pin

    def set_iopin_control(
        self, pin: int, setup: IoPinSetup | int, feature: IoPinFeature | int
    ) -> None:
        setup_value = int(setup)
        if setup_value & ~0xF:
            raise ValueError(f"unknown IO pin setup bits: 0x{setup_value & ~0xF:x}")
        feature_value = int(IoPinFeature(feature))
        self._ack(
            "set_iopin_control",
            build_set_iopin_control(self._pin(pin), setup_value, feature_value),
        )

    def get_iopin_control(self, pin: int) -> tuple[IoPinSetup, IoPinFeature]:
        result = self._reply(
            "get_iopin_control",
            build_get_iopin_control(self._pin(pin)),
            reply(IntReply, 0x11, element_count=2),
        )
        assert isinstance(result, IntReply)
        return IoPinSetup(int(result.values[0])), IoPinFeature(int(result.values[1]))

    def set_iopin_value(self, pin: int, value: int) -> None:
        if value not in (0, 1):
            raise ValueError("IO pin value must be 0 or 1")
        self._ack("set_iopin_value", build_set_iopin_value(self._pin(pin), value))

    def get_iopin_value(self, pin: int) -> int:
        result = self._reply(
            "get_iopin_value",
            build_get_iopin_value(self._pin(pin)),
            reply(IntReply, 0x21, element_count=1),
        )
        assert isinstance(result, IntReply)
        return int(result.values[0])


class NoisemapInterface(Interface):
    def load_noisemap(self) -> None:
        self._ack("load_noisemap", build_app_action(0x14))

    def store_noisemap(self) -> None:
        with self._unsafe_transaction(
            "MXS_ENABLE_NOISEMAP_FLASH_WRITE",
            allowed_states={DeviceState.OPEN, DeviceState.STOPPED},
        ):
            self._ack("store_noisemap", build_app_action(0x13))

    def delete_noisemap(self) -> None:
        with self._unsafe_transaction(
            "MXS_ENABLE_NOISEMAP_FLASH_WRITE",
            allowed_states={DeviceState.OPEN, DeviceState.STOPPED},
        ):
            self._ack("delete_noisemap", build_app_action(0x16))

    def set_noisemap_control(self, control: int) -> None:
        self._ack("set_noisemap_control", build_noisemap(0x10, control))

    def get_noisemap_control(self) -> int:
        result = self._reply(
            "get_noisemap_control", build_noisemap(0x11), reply(IntReply, 0x11, element_count=1)
        )
        assert isinstance(result, IntReply)
        return int(result.values[0])

    def set_periodic_noisemap_store(self, interval_minutes: int, reserved: int) -> None:
        raise UnsupportedFirmwareError(
            "periodic noisemap storage has no producer in local XEP source"
        )

    def get_periodic_noisemap_store(self) -> tuple[int, int]:
        raise UnsupportedFirmwareError(
            "periodic noisemap storage has no producer in local XEP source"
        )


class ParametersInterface(Interface):
    def get_parameter_file(self, filename: str) -> bytes:
        result = self._reply(
            "get_parameter_file", build_parameter_file(filename), reply(ByteReply, 0x32BA7623)
        )
        assert isinstance(result, ByteReply)
        return result.values

    def set_parameter_file(self, filename: str, data: bytes | str) -> None:
        payload = data.encode() if isinstance(data, str) else data
        self._ack("set_parameter_file", build_parameter_file(filename, payload))


class FilesystemInterface(Interface):
    CHUNK_SIZE = 1024

    def __init__(self, session: DeviceSession) -> None:
        super().__init__(session)
        self._filesystem_lock = session.filesystem_lock

    def search_for_file_by_type(self, file_type: int) -> list[FileIdentifier]:
        with self._filesystem_lock:
            return self._search_for_file_by_type_unlocked(file_type)

    def _search_for_file_by_type_unlocked(self, file_type: int) -> list[FileIdentifier]:
        result = self._reply(
            "search_for_file_by_type", build_filesystem(0x64, file_type), reply(IntReply, 0)
        )
        assert isinstance(result, IntReply)
        return [FileIdentifier(file_type, int(value)) for value in result.values]

    def find_all_files(self) -> list[FileIdentifier]:
        with self._filesystem_lock:
            return self._find_all_files_unlocked()

    def _find_all_files_unlocked(self) -> list[FileIdentifier]:
        result = self._reply("find_all_files", build_filesystem(0x65), reply(IntReply, 0))
        assert isinstance(result, IntReply)
        count = result.element_count // 2
        return [
            FileIdentifier(int(result.values[i]), int(result.values[i + count]))
            for i in range(count)
        ]

    def get_file_length(self, file_type: int, identifier: int) -> int:
        with self._filesystem_lock:
            return self._get_file_length_unlocked(file_type, identifier)

    def _get_file_length_unlocked(self, file_type: int, identifier: int) -> int:
        result = self._reply(
            "get_file_length",
            build_filesystem(0x69, file_type, identifier),
            reply(IntReply, 0, element_count=1),
        )
        assert isinstance(result, IntReply)
        return int(result.values[0])

    def get_file_data(self, file_type: int, identifier: int, offset: int, length: int) -> bytes:
        with self._filesystem_lock:
            return self._get_file_data_unlocked(file_type, identifier, offset, length)

    def _get_file_data_unlocked(
        self, file_type: int, identifier: int, offset: int, length: int
    ) -> bytes:
        if min(offset, length) < 0:
            raise ValueError("offset and length must be nonnegative")
        result = bytearray()
        for position in range(offset, offset + length, self.CHUNK_SIZE):
            count = min(self.CHUNK_SIZE, offset + length - position)
            reply_value = self._reply(
                "get_file_data",
                build_filesystem(0x71, file_type, identifier, position, count),
                reply(ByteReply, 0, element_count=count),
            )
            assert isinstance(reply_value, ByteReply)
            result.extend(reply_value.values)
        return bytes(result)

    def get_file(self, file_type: int, identifier: int) -> DeviceFile:
        with self._filesystem_lock:
            length = self._get_file_length_unlocked(file_type, identifier)
            metadata = FileMetadata(FileIdentifier(file_type, identifier), length)
            return DeviceFile(
                metadata,
                self._get_file_data_unlocked(file_type, identifier, 0, length),
            )


class UnsafeInterface(Interface):
    def __init__(self, session: DeviceSession) -> None:
        super().__init__(session)
        self.registers = RegisterInterface(session)
        self.filesystem_admin = FilesystemAdminInterface(session)

    def start_bootloader(self, *, key: int) -> None:
        with self._unsafe_transaction(
            "MXS_ENABLE_BOOTLOADER", allowed_states={DeviceState.OPEN, DeviceState.STOPPED}
        ):
            self._ack("start_bootloader", build_start_bootloader(key))

    def reset_to_factory_preset(self, *, confirm: bool) -> None:
        with self._unsafe_transaction(
            "MXS_ENABLE_FACTORY_RESET",
            allowed_states={DeviceState.OPEN, DeviceState.STOPPED},
            confirmation=confirm,
        ):
            self._ack("reset_to_factory_preset", build_factory_reset())

    def system_run_test(self, test_code: int) -> bytes:
        with self._unsafe_transaction(
            "MXS_ENABLE_MANUFACTURING_TESTS",
            allowed_states={DeviceState.OPEN, DeviceState.STOPPED},
        ):
            result = self._reply(
                "system_run_test", build_system_test(test_code), reply(ByteReply, 0x5090)
            )
            assert isinstance(result, ByteReply)
            return result.values

    def prepare_inject_frame(self, num_frames: int, num_bins: int, mode: int) -> None:
        with self._unsafe_transaction(
            "MXS_ENABLE_FRAME_INJECTION",
            allowed_states={DeviceState.OPEN, DeviceState.STOPPED, DeviceState.MANUAL},
            allow_manual=True,
        ):
            self._ack(
                "prepare_inject_frame", build_prepare_inject_frame(num_frames, num_bins, mode)
            )

    def inject_frame(self, frame_counter: int, num_bins: int, frame: np.ndarray) -> None:
        with self._unsafe_transaction(
            "MXS_ENABLE_FRAME_INJECTION",
            allowed_states={DeviceState.OPEN, DeviceState.STOPPED, DeviceState.MANUAL},
            allow_manual=True,
        ):
            values = np.asarray(frame, dtype="<f4")
            self._ack(
                "inject_frame",
                build_inject_frame(frame_counter, num_bins, values.tobytes(order="C")),
            )

    def __getattr__(self, name: str):
        for interface in (self.registers, self.filesystem_admin):
            if hasattr(interface, name):
                return getattr(interface, name)
        raise AttributeError(name)


class RegisterInterface(Interface):
    def _guarded_write(self, name: str, packet: bytes) -> None:
        with self._unsafe_transaction(
            "MXS_ENABLE_RAW_REGISTER_WRITES",
            allowed_states={DeviceState.OPEN, DeviceState.STOPPED, DeviceState.MANUAL},
            allow_manual=True,
        ):
            self._ack(name, packet)

    def x4driver_get_spi_register(self, address: int) -> int:
        result = self._reply(
            "x4driver_get_spi_register",
            build_x4_get(X4Parameter.SPI_REGISTER, bytes((address,))),
            reply(ByteReply, int(X4Parameter.SPI_REGISTER), element_count=1),
        )
        assert isinstance(result, ByteReply)
        return result.values[0]

    def x4driver_set_spi_register(self, address: int, value: int) -> None:
        self._guarded_write(
            "x4driver_set_spi_register",
            build_x4_set_register(X4Parameter.SPI_REGISTER, address, value),
        )

    def x4driver_set_pif_register(self, address: int, value: int) -> None:
        self._guarded_write(
            "x4driver_set_pif_register",
            build_x4_set_register(X4Parameter.PIF_REGISTER, address, value),
        )

    def x4driver_set_xif_register(self, address: int, value: int) -> None:
        self._guarded_write(
            "x4driver_set_xif_register",
            build_x4_set_register(X4Parameter.XIF_REGISTER, address, value),
        )

    def _get_register(self, parameter: X4Parameter, address: int) -> int:
        result = self._reply(
            f"get_{parameter.name.lower()}",
            build_x4_get(parameter, bytes((address,))),
            reply(ByteReply, int(parameter), element_count=1),
        )
        assert isinstance(result, ByteReply)
        return result.values[0]

    def x4driver_get_pif_register(self, address: int) -> int:
        return self._get_register(X4Parameter.PIF_REGISTER, address)

    def x4driver_get_xif_register(self, address: int) -> int:
        return self._get_register(X4Parameter.XIF_REGISTER, address)

    def x4driver_write_to_i2c_register(self, address: int, values: bytes) -> None:
        raise UnsupportedFirmwareError(
            "I2C register access has no wire producer in local Legacy-SW"
        )

    def x4driver_read_from_i2c_register(self, length: int) -> bytes:
        raise UnsupportedFirmwareError(
            "I2C register access has no wire producer in local Legacy-SW"
        )

    def read_spi(self, address: int, length: int = 1) -> bytes:
        result = self._reply(
            "read_spi",
            build_x4_read(X4Parameter.SPI_REGISTER, bytes((address,)) + struct.pack("<I", length)),
            reply(ByteReply, int(X4Parameter.SPI_REGISTER), element_count=length),
        )
        assert isinstance(result, ByteReply)
        return result.values

    def write_spi(self, address: int, values: bytes) -> None:
        self._guarded_write(
            "write_spi", build_x4_write(X4Parameter.SPI_REGISTER, bytes((address,)) + values)
        )

    x4driver_read_from_spi_register = read_spi
    x4driver_write_to_spi_register = write_spi


class FilesystemAdminInterface(FilesystemInterface):
    def _guard(self, gate: str = "MXS_ENABLE_UNSAFE", confirmation: bool | None = None) -> None:
        self._require_unsafe(
            gate,
            allowed_states={DeviceState.OPEN, DeviceState.STOPPED},
            confirmation=confirmation,
        )

    @staticmethod
    def _u32(value: int, name: str) -> int:
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"{name} must be an unsigned 32-bit integer")
        return value

    def create_file(self, file_type: int, identifier: int, length: int) -> None:
        with self._filesystem_lock:
            self._create_file_unlocked(file_type, identifier, length)

    def _create_file_unlocked(self, file_type: int, identifier: int, length: int) -> None:
        self._guard()
        self._u32(length, "length")
        self._ack("create_file", build_filesystem(0x66, file_type, identifier, length))

    def open_file(self, file_type: int, identifier: int) -> None:
        with self._filesystem_lock:
            self._open_file_unlocked(file_type, identifier)

    def _open_file_unlocked(self, file_type: int, identifier: int) -> None:
        self._guard()
        self._ack("open_file", build_filesystem(0x72, file_type, identifier))

    def set_file_data(self, file_type: int, identifier: int, offset: int, data: bytes) -> None:
        with self._filesystem_lock:
            self._set_file_data_unlocked(file_type, identifier, offset, data)

    def _set_file_data_unlocked(
        self, file_type: int, identifier: int, offset: int, data: bytes
    ) -> None:
        self._guard()
        self._u32(offset, "offset")
        if offset + len(data) > 0xFFFFFFFF:
            raise ValueError("file write range exceeds uint32")
        for position in range(0, len(data), self.CHUNK_SIZE):
            chunk = data[position : position + self.CHUNK_SIZE]
            self._ack(
                "set_file_data",
                build_filesystem(
                    0x67,
                    file_type,
                    identifier,
                    offset + position,
                    len(chunk),
                    data=chunk,
                ),
            )

    def close_file(self, file_type: int, identifier: int, *, commit: bool) -> None:
        with self._filesystem_lock:
            self._close_file_unlocked(file_type, identifier, commit=commit)

    def _close_file_unlocked(self, file_type: int, identifier: int, *, commit: bool) -> None:
        self._guard()
        self._ack("close_file", build_filesystem(0x68, file_type, identifier, int(commit)))

    def set_file(self, file_type: int, identifier: int, data: bytes) -> None:
        with self._filesystem_lock:
            self._create_file_unlocked(file_type, identifier, len(data))
            try:
                self._set_file_data_unlocked(file_type, identifier, 0, data)
            except BaseException:
                with suppress(BaseException):
                    self._close_file_unlocked(file_type, identifier, commit=False)
                raise
            self._close_file_unlocked(file_type, identifier, commit=True)

    def format_filesystem(self, *, key: int) -> None:
        with self._filesystem_lock:
            self._guard("MXS_ENABLE_FILESYSTEM_FORMAT", confirmation=key != 0)
            self._ack("format_filesystem", build_filesystem(0x73, key))

    def delete_file(self, file_type: int, identifier: int) -> None:
        with self._filesystem_lock:
            self._delete_file_unlocked(file_type, identifier)

    def _delete_file_unlocked(self, file_type: int, identifier: int) -> None:
        self._guard()
        self._ack("delete_file", build_filesystem(0x70, file_type, identifier))
