"""Pure MCP command builders with explicit little-endian fields."""

import math
import struct

from .constants import (
    CMD_DIRECT,
    CMD_PING,
    CMD_SET_SENSOR_MODE,
    CMD_X4_DRIVER,
    DIRECT_SET_BAUDRATE,
    PING_VALUE,
    X4_INIT,
    X4_SET,
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


def build_set_sensor_mode(mode: SensorMode | int) -> bytes:
    parsed = SensorMode(mode)
    payload = bytes((CMD_SET_SENSOR_MODE, parsed))
    if parsed is SensorMode.NORMAL:
        payload += b"\x00"
    return _frame(payload)


def build_set_baudrate(baudrate: int) -> bytes:
    if baudrate not in (115200, 921600):
        raise ValueError("supported baud rates are 115200 and 921600")
    return _frame(bytes((CMD_DIRECT, DIRECT_SET_BAUDRATE)) + _u32(baudrate, "baudrate"))


def build_x4_init() -> bytes:
    return _frame(bytes((CMD_X4_DRIVER, X4_INIT)))


def _x4(parameter: X4Parameter, value: bytes) -> bytes:
    return _frame(bytes((CMD_X4_DRIVER, X4_SET)) + struct.pack("<I", parameter) + value)


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
