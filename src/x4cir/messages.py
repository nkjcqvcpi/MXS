"""Strict MCP response and CIR message decoding."""

import struct

import numpy as np

from .constants import (
    CONTENT_ID_BASEBAND_IQ,
    CONTENT_ID_SLEEP_STATUS,
    PONG_READY,
    VALID_PONG_VALUES,
    DataType,
    ResponseType,
)
from .errors import InvalidIqFrameError, MalformedMessageError
from .models import (
    Ack,
    BasebandIqMessage,
    DataFloatMessage,
    ErrorResponse,
    Message,
    Pong,
    Reply,
    SleepStatus,
    UnknownMessage,
)

# References:
# ./Legacy-SW/MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol_host_parser.c
# ./Legacy-SW/XEP/xtXEP_source-3/xtSerial/src/protocol_target.c


def _require(payload: bytes, size: int, description: str) -> None:
    if len(payload) < size:
        raise MalformedMessageError(f"truncated {description}: {len(payload)} < {size}")


def decode_message(payload: bytes) -> Message:
    if not payload:
        raise MalformedMessageError("empty MCP payload")
    response = payload[0]
    if response == ResponseType.ACK:
        if len(payload) != 1:
            raise MalformedMessageError("ACK must contain exactly one byte")
        return Ack()
    if response == ResponseType.ERROR:
        if len(payload) != 5:
            raise MalformedMessageError("ERROR must contain a uint32 code")
        return ErrorResponse(struct.unpack_from("<I", payload, 1)[0])
    if response == ResponseType.PONG:
        if len(payload) != 5:
            raise MalformedMessageError("PONG must contain a uint32 value")
        value = struct.unpack_from("<I", payload, 1)[0]
        if value not in VALID_PONG_VALUES:
            raise MalformedMessageError(f"unexpected PONG value 0x{value:08x}")
        return Pong(value=value, ready=value == PONG_READY)
    if response == ResponseType.REPLY:
        return _decode_reply(payload)
    if response == ResponseType.DATA:
        return _decode_data(payload)
    if response == ResponseType.APPDATA:
        return _decode_appdata(payload)
    return UnknownMessage(response_type=response, payload=payload)


def _decode_reply(payload: bytes) -> Reply:
    _require(payload, 11, "REPLY")
    raw_type = payload[1]
    try:
        data_type: DataType | int = DataType(raw_type)
    except ValueError:
        data_type = raw_type
    content_id, info = struct.unpack_from("<II", payload, 2)
    if len(payload) == 11:
        return Reply(data_type, content_id, info, b"", payload[10])
    _require(payload, 15, "REPLY length")
    length = struct.unpack_from("<I", payload, 10)[0]
    expected = 15 + length
    if len(payload) != expected:
        raise MalformedMessageError(
            f"REPLY byte count mismatch: declared {length}, payload {len(payload)}"
        )
    return Reply(data_type, content_id, info, bytes(payload[14 : 14 + length]), payload[-1])


def _decode_data(payload: bytes) -> Message:
    _require(payload, 2, "DATA header")
    if payload[1] != DataType.FLOAT:
        return UnknownMessage(payload[0], payload)
    _require(payload, 10, "DataFloat header")
    content_id, frame_counter = struct.unpack_from("<II", payload, 2)
    if len(payload) == 10:
        samples = np.empty(0, dtype=np.float32)
        return DataFloatMessage(content_id, frame_counter, samples)
    _require(payload, 14, "DataFloat count")
    count = struct.unpack_from("<I", payload, 10)[0]
    expected = 14 + count * 4
    if len(payload) != expected:
        raise MalformedMessageError(
            f"DataFloat count mismatch: declared {count}, payload bytes {len(payload)}"
        )
    samples = np.frombuffer(payload, dtype="<f4", count=count, offset=14).copy()
    return DataFloatMessage(content_id, frame_counter, samples)


def data_float_to_iq(message: DataFloatMessage) -> np.ndarray:
    if message.samples.size % 2:
        raise InvalidIqFrameError("downconverted DataFloat sample count must be even")
    bins = message.samples.size // 2
    iq = np.empty(bins, dtype=np.complex64)
    iq.real = message.samples[:bins]
    iq.imag = message.samples[bins:]
    return iq


def _decode_appdata(payload: bytes) -> Message:
    _require(payload, 5, "APPDATA header")
    content_id = struct.unpack_from("<I", payload, 1)[0]
    if content_id == CONTENT_ID_SLEEP_STATUS:
        if len(payload) != 33:
            raise MalformedMessageError("SleepStatus must be exactly 33 bytes")
        values = struct.unpack_from("<IIffIff", payload, 5)
        return SleepStatus(*values)
    if content_id == CONTENT_ID_BASEBAND_IQ:
        return _decode_baseband_iq(payload)
    return UnknownMessage(payload[0], payload)


def _decode_baseband_iq(payload: bytes) -> BasebandIqMessage:
    fixed_size = 29
    _require(payload, fixed_size, "baseband IQ header")
    content_id, counter, bins = struct.unpack_from("<III", payload, 1)
    bin_length, sample_frequency, carrier_frequency, range_offset = struct.unpack_from(
        "<ffff", payload, 13
    )
    expected = fixed_size + bins * 8
    if len(payload) != expected:
        raise MalformedMessageError(
            f"baseband IQ count mismatch: {bins} bins require {expected} bytes"
        )
    floats = np.frombuffer(payload, dtype="<f4", count=bins * 2, offset=fixed_size)
    iq = np.empty(bins, dtype=np.complex64)
    iq.real = floats[:bins]
    iq.imag = floats[bins:]
    return BasebandIqMessage(
        content_id,
        counter,
        bins,
        bin_length,
        sample_frequency,
        carrier_frequency,
        range_offset,
        iq,
    )
