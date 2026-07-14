"""Verified XeThru MCP protocol constants."""

from enum import IntEnum

# Reference:
# ./Legacy-SW/MCPWrapper/mcp_wrapper_1.3.1/src/mcp/xtserial_definitions.h
START_BYTE = 0x7D
STOP_BYTE = 0x7E
ESCAPE_BYTE = 0x7F
NO_ESCAPE_MARKER = b"\x7c\x7c\x7c\x7c"
DEFAULT_MAX_PACKET_SIZE = 4 * 1024 * 1024

PING_VALUE = 0xEEAAEAAE
PONG_READY = 0xAAEEAEEA
PONG_NOT_READY = 0xAEEAEEAA
PONG_SAFE_MODE = 0xFFEEFEEF
VALID_PONG_VALUES = frozenset((PONG_READY, PONG_NOT_READY, PONG_SAFE_MODE))


class ResponseType(IntEnum):
    PONG = 0x01
    ACK = 0x10
    REPLY = 0x11
    HIL = 0x12
    ERROR = 0x20
    SYSTEM = 0x30
    APPDATA = 0x50
    DATA = 0xA0


class DataType(IntEnum):
    NONE = 0x00
    BYTE = 0x10
    INT = 0x11
    FLOAT = 0x12
    STRING = 0x13
    USER = 0x50


class SensorMode(IntEnum):
    RUN = 0x01
    NORMAL = 0x10
    IDLE = 0x11
    MANUAL = 0x12
    STOP = 0x13


class X4Parameter(IntEnum):
    FPS = 0x10
    PULSES_PER_STEP = 0x11
    ITERATIONS = 0x12
    DOWNCONVERSION = 0x13
    FRAME_AREA = 0x14
    DAC_STEP = 0x15
    DAC_MIN = 0x16
    DAC_MAX = 0x17
    FRAME_AREA_OFFSET = 0x18
    ENABLE = 0x19
    TX_CENTER_FREQUENCY = 0x20
    TX_POWER = 0x21
    SPI_REGISTER = 0x22
    PIF_REGISTER = 0x23
    XIF_REGISTER = 0x24
    PRF_DIV = 0x25


class DeviceState(IntEnum):
    CLOSED = 0
    OPEN = 1
    STOPPED = 2
    MANUAL = 3
    CONFIGURED = 4
    STREAMING = 5
    ERROR = 6
    CLOSING = 7


CONTENT_ID_RAW_FRAME = 0x00000000
CONTENT_ID_BASEBAND_IQ = 0x0000000C
CONTENT_ID_BASEBAND_AP = 0x0000000D
CONTENT_ID_SLEEP_STATUS = 0x2375A16C

# Command bytes from xtserial_definitions.h.
CMD_PING = 0x01
CMD_SET_SENSOR_MODE = 0x20
CMD_X4_DRIVER = 0x50
CMD_DIRECT = 0x90
DIRECT_SET_BAUDRATE = 0x80
X4_SET = 0x10
X4_INIT = 0x20
