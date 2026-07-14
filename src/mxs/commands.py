"""Pure MCP command builders with explicit little-endian fields."""

import math
import struct

from .constants import (
    CMD_DEBUG_OUTPUT,
    CMD_DIRECT,
    CMD_GET_SENSOR_MODE,
    CMD_IOPIN,
    CMD_LED_CONTROL,
    CMD_LOAD_PROFILE,
    CMD_MODULE_RESET,
    CMD_NOISEMAP,
    CMD_OUTPUT,
    CMD_PING,
    CMD_SET_SENSOR_MODE,
    CMD_X4_DRIVER,
    DIRECT_SET_BAUDRATE,
    PING_VALUE,
    X4_GET,
    X4_INIT,
    X4_READ,
    X4_SET,
    X4_WRITE,
    SensorMode,
    X4Parameter,
)
from .framing import encode_classic_frame

# Reference:
# ./Legacy-SW/MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol.c
# (`createSetSensorModeCommand`, `createPingCommand`, `createSetBaudRateCommand`,
# and `createX4DriverSet*Command`).


def _frame(payload: bytes) -> bytes:
    return encode_classic_frame(payload)


def _u32(value: int, name: str) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{name} must fit uint32")
    return struct.pack("<I", value)


def _u8(value: int, name: str) -> bytes:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must fit uint8")
    return bytes((value,))


def _f32(value: float, name: str) -> bytes:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return struct.pack("<f", value)


def build_ping() -> bytes:
    return _frame(bytes((CMD_PING,)) + struct.pack("<I", PING_VALUE))


def build_set_sensor_mode(mode: SensorMode | int, param: int = 0) -> bytes:
    parsed = SensorMode(mode)
    payload = bytes((CMD_SET_SENSOR_MODE, parsed))
    if parsed is SensorMode.NORMAL:
        payload += _u8(param, "param")
    return _frame(payload)


def build_set_baudrate(baudrate: int) -> bytes:
    if baudrate not in (115200, 921600):
        raise ValueError("supported baud rates are 115200 and 921600")
    return _frame(bytes((CMD_DIRECT, DIRECT_SET_BAUDRATE)) + _u32(baudrate, "baudrate"))


def build_x4_init() -> bytes:
    return _frame(bytes((CMD_X4_DRIVER, X4_INIT)))


def _x4(parameter: X4Parameter, value: bytes) -> bytes:
    return _frame(bytes((CMD_X4_DRIVER, X4_SET)) + struct.pack("<I", parameter) + value)


def build_x4_get(parameter: X4Parameter | int, argument: bytes = b"") -> bytes:
    return _frame(bytes((CMD_X4_DRIVER, X4_GET)) + _u32(int(parameter), "parameter") + argument)


def build_set_prf_div(value: int) -> bytes:
    return _x4(X4Parameter.PRF_DIV, _u8(value, "prf_div"))


def build_x4_write(parameter: X4Parameter | int, argument: bytes) -> bytes:
    return _frame(bytes((CMD_X4_DRIVER, X4_WRITE)) + _u32(int(parameter), "parameter") + argument)


def build_x4_set_register(parameter: X4Parameter | int, address: int, value: int) -> bytes:
    return _frame(
        bytes((CMD_X4_DRIVER, X4_SET))
        + _u32(int(parameter), "parameter")
        + _u8(address, "address")
        + _u8(value, "value")
    )


def build_x4_read(parameter: X4Parameter | int, argument: bytes) -> bytes:
    return _frame(bytes((CMD_X4_DRIVER, X4_READ)) + _u32(int(parameter), "parameter") + argument)


def build_get_sensor_mode() -> bytes:
    return _frame(bytes((CMD_GET_SENSOR_MODE,)))


def build_load_profile(profile_id: int) -> bytes:
    return _frame(bytes((CMD_LOAD_PROFILE,)) + _u32(profile_id, "profile_id"))


def build_module_reset() -> bytes:
    return _frame(bytes((CMD_MODULE_RESET,)))


def build_debug_level(level: int) -> bytes:
    if not 0 <= level <= 9:
        raise ValueError("debug level must be between 0 and 9")
    return _frame(bytes((0xB0, level)))


def build_start_bootloader(key: int = 0xA2B95EF0) -> bytes:
    return _frame(b"\x02" + _u32(key, "key"))


def build_system_info(info_code: int) -> bytes:
    return _frame(b"\x90\x58" + _u8(info_code, "info_code"))


def build_system_test(test_code: int) -> bytes:
    return _frame(b"\x90\x50" + _u8(test_code, "test_code"))


def build_prepare_inject_frame(num_frames: int, num_bins: int, mode: int) -> bytes:
    if num_frames <= 0 or num_bins <= 0:
        raise ValueError("num_frames and num_bins must be positive")
    return _frame(b"\x90\x76" + struct.pack("<III", num_frames, num_bins, mode))


def build_inject_frame(frame_counter: int, num_bins: int, values: bytes) -> bytes:
    if len(values) != num_bins * 2 * 4:
        raise ValueError("injected IQ frame must contain 2 * num_bins float32 values")
    return _frame(
        b"\x90\x75" + _u32(frame_counter, "frame_counter") + _u32(num_bins, "num_bins") + values
    )


def build_factory_reset() -> bytes:
    return _frame(b"\x10\x12")


def build_app_get(content_id: int, argument: bytes = b"") -> bytes:
    return _frame(b"\x10\x11" + _u32(content_id, "content_id") + argument)


def build_app_set(content_id: int, data: bytes) -> bytes:
    return _frame(b"\x10\x10" + _u32(content_id, "content_id") + data)


def build_set_detection_zone(start: float, end: float) -> bytes:
    if not (math.isfinite(start) and math.isfinite(end) and start < end):
        raise ValueError("detection-zone start must be finite and precede end")
    return build_app_set(0x96A10A1C, struct.pack("<ff", start, end))


def build_set_led_control(mode: int, intensity: int) -> bytes:
    return _frame(bytes((CMD_LED_CONTROL,)) + _u8(mode, "mode") + _u8(intensity, "intensity"))


def build_set_output_control(feature: int, control: int, *, debug: bool = False) -> bytes:
    command = CMD_DEBUG_OUTPUT if debug else CMD_OUTPUT
    return _frame(bytes((command, 0x10)) + _u32(feature, "feature") + _u32(control, "control"))


def build_get_output_control(feature: int, *, debug: bool = False) -> bytes:
    command = CMD_DEBUG_OUTPUT if debug else CMD_OUTPUT
    return _frame(bytes((command, 0x11)) + _u32(feature, "feature"))


def build_set_iopin_control(pin: int, setup: int, feature: int) -> bytes:
    return _frame(bytes((CMD_IOPIN, 0x10)) + struct.pack("<III", pin, setup, feature))


def build_get_iopin_control(pin: int) -> bytes:
    return _frame(bytes((CMD_IOPIN, 0x11)) + _u32(pin, "pin"))


def build_set_iopin_value(pin: int, value: int) -> bytes:
    return _frame(bytes((CMD_IOPIN, 0x20)) + _u32(pin, "pin") + _u32(value, "value"))


def build_get_iopin_value(pin: int) -> bytes:
    return _frame(bytes((CMD_IOPIN, 0x21)) + _u32(pin, "pin"))


def build_noisemap(action: int, value: int | None = None) -> bytes:
    payload = bytes((CMD_NOISEMAP, action))
    if value is not None:
        payload += _u32(value, "value")
    return _frame(payload)


def build_app_action(action: int) -> bytes:
    return _frame(b"\x10" + _u8(action, "action"))


def build_filesystem(command: int, *values: int, data: bytes = b"") -> bytes:
    payload = b"\x90" + _u8(command, "command")
    payload += b"".join(_u32(value, "filesystem argument") for value in values)
    return _frame(payload + data)


def build_parameter_file(filename: str, data: bytes | None = None) -> bytes:
    encoded_name = filename.encode("utf-8") + b"\0"
    if b"/" in encoded_name or b"\\" in encoded_name or len(encoded_name) > 256:
        raise ValueError("parameter filename must be a simple UTF-8 name of at most 255 bytes")
    if data is None:
        return build_app_get(0x32BA7623, _u32(len(encoded_name), "filename length") + encoded_name)
    encoded_data = data + (b"" if data.endswith(b"\0") else b"\0")
    argument = (
        struct.pack("<II", len(encoded_name), len(encoded_data)) + encoded_name + encoded_data
    )
    return build_app_set(0x32BA7623, argument)


def build_set_fps(fps: float) -> bytes:
    if fps < 0:
        raise ValueError("fps must be nonnegative")
    return _x4(X4Parameter.FPS, _f32(fps, "fps"))


def build_set_iterations(iterations: int) -> bytes:
    return _x4(X4Parameter.ITERATIONS, _u32(iterations, "iterations"))


def build_set_pulses_per_step(value: int) -> bytes:
    return _x4(X4Parameter.PULSES_PER_STEP, _u32(value, "pulses_per_step"))


def build_set_downconversion(enabled: bool | int) -> bytes:
    if enabled not in (False, True, 0, 1):
        raise ValueError("downconversion must be boolean")
    return _x4(X4Parameter.DOWNCONVERSION, bytes((int(enabled),)))


def build_set_frame_area(start: float, end: float) -> bytes:
    if start >= end:
        raise ValueError("frame area start must precede end")
    return _x4(X4Parameter.FRAME_AREA, _f32(start, "start") + _f32(end, "end"))


def build_set_dac_step(value: int) -> bytes:
    return _x4(X4Parameter.DAC_STEP, _u8(value, "dac_step"))


def build_set_dac_min(value: int) -> bytes:
    return _x4(X4Parameter.DAC_MIN, _u32(value, "dac_min"))


def build_set_dac_max(value: int) -> bytes:
    return _x4(X4Parameter.DAC_MAX, _u32(value, "dac_max"))


def build_set_frame_area_offset(value: float) -> bytes:
    return _x4(X4Parameter.FRAME_AREA_OFFSET, _f32(value, "frame_area_offset"))


def build_set_enable(enabled: bool | int) -> bytes:
    if enabled not in (False, True, 0, 1):
        raise ValueError("enable must be boolean")
    return _x4(X4Parameter.ENABLE, bytes((int(enabled),)))


def build_set_tx_center_frequency(value: int) -> bytes:
    if value not in (3, 4):
        raise ValueError("center frequency must be 3 or 4")
    return _x4(X4Parameter.TX_CENTER_FREQUENCY, bytes((value,)))


def build_set_tx_power(value: int) -> bytes:
    if not 0 <= value <= 3:
        raise ValueError("TX power must be between 0 and 3")
    return _x4(X4Parameter.TX_POWER, bytes((value,)))
