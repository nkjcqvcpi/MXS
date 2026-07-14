"""Strict MCP response and CIR message decoding."""

import struct

import numpy as np

from .constants import (
    CONTENT_ID_BASEBAND_AP,
    CONTENT_ID_BASEBAND_IQ,
    CONTENT_ID_NOISEMAP_BYTE,
    CONTENT_ID_NOISEMAP_FLOAT,
    CONTENT_ID_NORMALIZED_MOVEMENT,
    CONTENT_ID_PULSE_DOPPLER_BYTE,
    CONTENT_ID_PULSE_DOPPLER_FLOAT,
    CONTENT_ID_RESPIRATION_DETECTION_LIST,
    CONTENT_ID_RESPIRATION_MOVING_LIST,
    CONTENT_ID_RESPIRATION_STATUS,
    CONTENT_ID_SLEEP_STATUS,
    CONTENT_ID_VITAL_SIGNS,
    PONG_READY,
    VALID_PONG_VALUES,
    DataType,
    ResponseType,
)
from .errors import InvalidIqFrameError, MalformedMessageError
from .models import (
    Ack,
    BasebandAmplitudePhaseMessage,
    BasebandIqMessage,
    ByteReply,
    DataByteMessage,
    DataFloatMessage,
    DataStringMessage,
    DataUserMessage,
    EmptyReply,
    ErrorResponse,
    FloatReply,
    IntReply,
    MatrixMessage,
    Message,
    NormalizedMovementList,
    Pong,
    Reply,
    RespirationDetectionList,
    RespirationMovingList,
    RespirationStatus,
    SleepStatus,
    StringReply,
    SystemMessage,
    UnknownMessage,
    UserReply,
    VitalSigns,
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
    if response == ResponseType.SYSTEM:
        _require(payload, 5, "SYSTEM content ID")
        return SystemMessage(struct.unpack_from("<I", payload, 1)[0], bytes(payload[5:]))
    if response == ResponseType.APPDATA:
        return _decode_appdata(payload)
    return UnknownMessage(response_type=response, payload=payload)


def _decode_reply(payload: bytes) -> Reply:
    _require(payload, 10, "REPLY")
    try:
        data_type = DataType(payload[1])
    except ValueError as error:
        raise MalformedMessageError(f"unknown REPLY datatype 0x{payload[1]:02x}") from error
    content_id, info = struct.unpack_from("<II", payload, 2)
    if data_type is DataType.NONE:
        if len(payload) not in (10, 11):
            raise MalformedMessageError("NONE REPLY contains element data")
        element_size = payload[10] if len(payload) == 11 else 0
        if element_size != 0:
            raise MalformedMessageError("NONE REPLY has nonzero element size")
        return EmptyReply(content_id, info, 0, 0)
    if len(payload) == 11:
        element_size = payload[10]
        expected_size = _element_size(data_type)
        if element_size != expected_size:
            raise MalformedMessageError(
                f"empty REPLY element size {element_size}, expected {expected_size}"
            )
        return _typed_reply(data_type, content_id, info, 0, element_size, b"")
    if len(payload) == 10 and data_type is DataType.INT:
        return IntReply(content_id, info, 0, 4, np.empty(0, dtype=np.int32))
    _require(payload, 14, "REPLY element count")
    count = int(struct.unpack_from("<I", payload, 10)[0])
    element_size = _element_size(data_type)
    data_end = 14 + count * element_size
    if len(payload) == data_end:
        # XEP's integer producer omits the final size field.
        if data_type is not DataType.INT:
            raise MalformedMessageError("REPLY is missing its trailing element-size field")
    elif len(payload) == data_end + 1:
        trailing_size = int(payload[data_end])
        if trailing_size != element_size:
            raise MalformedMessageError(
                f"REPLY element size {trailing_size}, expected {element_size}"
            )
    else:
        raise MalformedMessageError(
            f"REPLY count mismatch: {count} elements require {data_end} or {data_end + 1} bytes"
        )
    return _typed_reply(
        data_type, content_id, info, count, element_size, bytes(payload[14:data_end])
    )


def _element_size(data_type: DataType) -> int:
    return {
        DataType.BYTE: 1,
        DataType.INT: 4,
        DataType.FLOAT: 4,
        DataType.STRING: 1,
        DataType.USER: 1,
    }[data_type]


def _typed_reply(
    data_type: DataType,
    content_id: int,
    info: int,
    count: int,
    element_size: int,
    data: bytes,
) -> Reply:
    common = (content_id, info, count, element_size)
    if data_type is DataType.BYTE:
        return ByteReply(*common, data)
    if data_type is DataType.INT:
        return IntReply(*common, np.frombuffer(data, dtype="<i4").copy())
    if data_type is DataType.FLOAT:
        return FloatReply(*common, np.frombuffer(data, dtype="<f4").copy())
    if data_type is DataType.STRING:
        try:
            value = data.rstrip(b"\0").decode("utf-8")
        except UnicodeDecodeError as error:
            raise MalformedMessageError("STRING REPLY is not UTF-8") from error
        return StringReply(*common, value)
    if data_type is DataType.USER:
        return UserReply(*common, data)
    raise AssertionError(f"unhandled REPLY datatype {data_type}")


def _decode_data(payload: bytes) -> Message:
    _require(payload, 2, "DATA header")
    try:
        data_type = DataType(payload[1])
    except ValueError:
        return UnknownMessage(payload[0], payload)
    _require(payload, 10, "DATA header")
    content_id, info = struct.unpack_from("<II", payload, 2)
    if len(payload) == 10:
        if data_type is DataType.FLOAT:
            return DataFloatMessage(content_id, info, np.empty(0, dtype=np.float32))
        return _typed_data(data_type, content_id, info, b"")
    _require(payload, 14, "DATA count")
    count = struct.unpack_from("<I", payload, 10)[0]
    element_size = 4 if data_type is DataType.FLOAT else 1
    expected = 14 + count * element_size
    if len(payload) != expected:
        raise MalformedMessageError(
            f"DATA count mismatch: declared {count}, payload bytes {len(payload)}"
        )
    data = payload[14:]
    if data_type is DataType.FLOAT:
        samples = np.frombuffer(data, dtype="<f4", count=count).copy()
        return DataFloatMessage(content_id, info, samples)
    return _typed_data(data_type, content_id, info, data)


def _typed_data(data_type: DataType, content_id: int, info: int, data: bytes) -> Message:
    if data_type is DataType.BYTE:
        return DataByteMessage(content_id, info, bytes(data))
    if data_type is DataType.STRING:
        try:
            return DataStringMessage(content_id, info, data.rstrip(b"\0").decode("utf-8"))
        except UnicodeDecodeError as error:
            raise MalformedMessageError("DATA STRING is not UTF-8") from error
    if data_type is DataType.USER:
        return DataUserMessage(content_id, info, bytes(data))
    return UnknownMessage(ResponseType.DATA, bytes((ResponseType.DATA, data_type)) + data)


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
    decoder = MESSAGE_DECODERS.get((ResponseType.APPDATA, content_id))
    if decoder is not None:
        return decoder(payload)
    return UnknownMessage(payload[0], payload)


def _decode_sleep(payload: bytes) -> SleepStatus:
    if len(payload) != 33:
        raise MalformedMessageError("SleepStatus must be exactly 33 bytes")
    return SleepStatus(*struct.unpack_from("<IIffIff", payload, 5))


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


def _decode_baseband_ap(payload: bytes) -> BasebandAmplitudePhaseMessage:
    fixed_size = 29
    _require(payload, fixed_size, "baseband amplitude/phase header")
    content_id, counter, bins = struct.unpack_from("<III", payload, 1)
    bin_length, sample_frequency, carrier_frequency, range_offset = struct.unpack_from(
        "<ffff", payload, 13
    )
    expected = fixed_size + bins * 8
    if len(payload) != expected:
        raise MalformedMessageError("baseband amplitude/phase count mismatch")
    values = np.frombuffer(payload, dtype="<f4", count=bins * 2, offset=fixed_size)
    return BasebandAmplitudePhaseMessage(
        content_id,
        counter,
        bins,
        bin_length,
        sample_frequency,
        carrier_frequency,
        range_offset,
        values[:bins].copy(),
        values[bins:].copy(),
    )


def _decode_respiration(payload: bytes) -> RespirationStatus:
    if len(payload) != 29:
        raise MalformedMessageError("RespirationStatus must be exactly 29 bytes")
    return RespirationStatus(*struct.unpack_from("<IIIffI", payload, 5))


def _decode_vital_signs(payload: bytes) -> VitalSigns:
    if len(payload) != 53:
        raise MalformedMessageError("VitalSigns must be exactly 53 bytes")
    return VitalSigns(*struct.unpack_from("<II10f", payload, 5))


def _decode_float_lists(payload: bytes, columns: int, kind: str):
    _require(payload, 13, f"{kind} header")
    counter, count = struct.unpack_from("<II", payload, 5)
    expected = 13 + count * columns * 4
    if len(payload) != expected:
        raise MalformedMessageError(f"{kind} count mismatch")
    values = np.frombuffer(payload, dtype="<f4", count=count * columns, offset=13)
    return counter, tuple(
        values[index * count : (index + 1) * count].copy() for index in range(columns)
    )


def _decode_moving(payload: bytes) -> RespirationMovingList:
    counter, values = _decode_float_lists(payload, 2, "RespirationMovingList")
    return RespirationMovingList(counter, values[0], values[1])


def _decode_detection(payload: bytes) -> RespirationDetectionList:
    counter, values = _decode_float_lists(payload, 3, "RespirationDetectionList")
    return RespirationDetectionList(counter, values[0], values[1], values[2])


def _decode_normalized(payload: bytes) -> NormalizedMovementList:
    _require(payload, 21, "NormalizedMovementList header")
    counter, start, bin_length, count = struct.unpack_from("<IffI", payload, 5)
    expected = 21 + count * 8
    if len(payload) != expected:
        raise MalformedMessageError("NormalizedMovementList count mismatch")
    values = np.frombuffer(payload, dtype="<f4", count=count * 2, offset=21)
    return NormalizedMovementList(
        counter, start, bin_length, values[:count].copy(), values[count:].copy()
    )


def _decode_matrix(payload: bytes) -> MatrixMessage:
    content_id = struct.unpack_from("<I", payload, 1)[0]
    is_byte = content_id in (CONTENT_ID_PULSE_DOPPLER_BYTE, CONTENT_ID_NOISEMAP_BYTE)
    _require(payload, 57 if is_byte else 49, "matrix header")
    counter, matrix_counter, range_index, range_bins, frequency_count, instance = (
        struct.unpack_from("<6I", payload, 5)
    )
    offset = 29
    step_start = step_size = None
    if is_byte:
        step_start, step_size = struct.unpack_from("<ff", payload, offset)
        offset += 8
    fps, decimated_fps, frequency_start, frequency_step, distance = struct.unpack_from(
        "<5f", payload, offset
    )
    offset += 20
    expected = offset + frequency_count * (1 if is_byte else 4)
    if len(payload) != expected:
        raise MalformedMessageError("matrix value count mismatch")
    if is_byte:
        values = np.frombuffer(payload, dtype=np.uint8, count=frequency_count, offset=offset).copy()
    else:
        values = np.frombuffer(payload, dtype="<f4", count=frequency_count, offset=offset).copy()
    return MatrixMessage(
        content_id,
        counter,
        matrix_counter,
        range_index,
        range_bins,
        frequency_count,
        instance,
        fps,
        decimated_fps,
        frequency_start,
        frequency_step,
        distance,
        values,
        step_start,
        step_size,
    )


MESSAGE_DECODERS = {
    (ResponseType.APPDATA, CONTENT_ID_SLEEP_STATUS): _decode_sleep,
    (ResponseType.APPDATA, CONTENT_ID_RESPIRATION_STATUS): _decode_respiration,
    (ResponseType.APPDATA, CONTENT_ID_VITAL_SIGNS): _decode_vital_signs,
    (ResponseType.APPDATA, CONTENT_ID_RESPIRATION_MOVING_LIST): _decode_moving,
    (ResponseType.APPDATA, CONTENT_ID_RESPIRATION_DETECTION_LIST): _decode_detection,
    (ResponseType.APPDATA, CONTENT_ID_NORMALIZED_MOVEMENT): _decode_normalized,
    (ResponseType.APPDATA, CONTENT_ID_BASEBAND_IQ): _decode_baseband_iq,
    (ResponseType.APPDATA, CONTENT_ID_BASEBAND_AP): _decode_baseband_ap,
    (ResponseType.APPDATA, CONTENT_ID_PULSE_DOPPLER_FLOAT): _decode_matrix,
    (ResponseType.APPDATA, CONTENT_ID_PULSE_DOPPLER_BYTE): _decode_matrix,
    (ResponseType.APPDATA, CONTENT_ID_NOISEMAP_FLOAT): _decode_matrix,
    (ResponseType.APPDATA, CONTENT_ID_NOISEMAP_BYTE): _decode_matrix,
}
