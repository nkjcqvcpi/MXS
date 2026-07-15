"""Source-layout message decoder vectors, with no serial-device simulation."""

import struct

import numpy as np
import pytest

from mxs.constants import (
    CONTENT_ID_BASEBAND_AP,
    CONTENT_ID_BASEBAND_IQ,
    CONTENT_ID_NOISEMAP_BYTE,
    CONTENT_ID_NORMALIZED_MOVEMENT,
    CONTENT_ID_RAW_FRAME,
    CONTENT_ID_RESPIRATION_DETECTION_LIST,
    CONTENT_ID_RESPIRATION_MOVING_LIST,
    CONTENT_ID_RESPIRATION_STATUS,
    CONTENT_ID_VITAL_SIGNS,
)
from mxs.errors import InvalidIqFrameError, MalformedMessageError
from mxs.messages import data_float_to_iq, decode_message
from mxs.models import (
    Ack,
    BasebandAmplitudePhaseMessage,
    BasebandIqMessage,
    DataByteMessage,
    DataFloatMessage,
    DataStringMessage,
    DataUserMessage,
    ErrorResponse,
    FloatReply,
    IntReply,
    MatrixMessage,
    NormalizedMovementList,
    Pong,
    RespirationDetectionList,
    RespirationMovingList,
    RespirationStatus,
    SystemMessage,
    UnknownMessage,
    VitalSigns,
)


def _app(content_id: int, data: bytes) -> bytes:
    return b"\x50" + struct.pack("<I", content_id) + data


def _data_float(samples: list[float], counter: int = 4) -> bytes:
    return (
        b"\xa0\x12"
        + struct.pack("<III", CONTENT_ID_RAW_FRAME, counter, len(samples))
        + struct.pack(f"<{len(samples)}f", *samples)
    )


def test_control_reply_and_generic_data_layouts() -> None:
    assert decode_message(b"\x10") == Ack()
    assert decode_message(b"\x20\x34\x12\x00\x00") == ErrorResponse(0x1234)
    assert decode_message(b"\x01" + struct.pack("<I", 0xAAEEAEEA)) == Pong(0xAAEEAEEA, True)
    assert isinstance(decode_message(b"\x99abc"), UnknownMessage)

    common = struct.pack("<II", 1, 2)
    assert decode_message(b"\x11\x00" + common).element_count == 0  # type: ignore[union-attr]
    assert decode_message(b"\x11\x11" + common).element_count == 0  # type: ignore[union-attr]
    assert decode_message(b"\x11\x13" + common + b"\x01").element_count == 0  # type: ignore[union-attr]
    byte = decode_message(b"\x11\x10" + common + struct.pack("<I", 1) + b"x\x01")
    user = decode_message(b"\x11\x50" + common + struct.pack("<I", 1) + b"y\x01")
    assert byte.values == b"x"  # type: ignore[union-attr]
    assert user.value == b"y"  # type: ignore[union-attr]
    integer = decode_message(b"\x11\x11" + struct.pack("<IIIi", 7, 0, 1, 42))
    assert isinstance(integer, IntReply) and integer.values.tolist() == [42]
    floating = decode_message(
        b"\x11\x12" + struct.pack("<III", 3, 4, 2) + struct.pack("<ff", 1, 2) + b"\x04"
    )
    assert isinstance(floating, FloatReply) and floating.values.tolist() == [1, 2]

    assert isinstance(
        decode_message(b"\xa0\x10" + struct.pack("<III", 1, 2, 2) + b"ab"), DataByteMessage
    )
    assert isinstance(
        decode_message(b"\xa0\x13" + struct.pack("<III", 1, 2, 2) + b"hi"), DataStringMessage
    )
    assert isinstance(
        decode_message(b"\xa0\x50" + struct.pack("<III", 1, 2, 2) + b"ab"), DataUserMessage
    )
    assert isinstance(decode_message(b"\x30" + struct.pack("<I", 5) + b"ok"), SystemMessage)


def test_raw_baseband_and_application_layouts() -> None:
    raw = decode_message(_data_float([1.0, np.nan, 2.0, np.inf]))
    assert isinstance(raw, DataFloatMessage) and raw.samples.dtype == np.float32
    iq = data_float_to_iq(raw)
    assert iq.dtype == np.complex64 and iq[0] == np.complex64(1 + 2j)
    odd = decode_message(_data_float([1.0]))
    assert isinstance(odd, DataFloatMessage)
    with pytest.raises(InvalidIqFrameError):
        data_float_to_iq(odd)

    iq_header = b"\x50" + struct.pack(
        "<IIIffff", CONTENT_ID_BASEBAND_IQ, 8, 2, 0.1, 1.0, 7.29, -0.5
    )
    baseband_iq = decode_message(iq_header + struct.pack("<ffff", 1, 2, 3, 4))
    assert isinstance(baseband_iq, BasebandIqMessage)
    np.testing.assert_array_equal(baseband_iq.samples, np.asarray([1 + 3j, 2 + 4j], np.complex64))

    baseband_ap = decode_message(
        _app(CONTENT_ID_BASEBAND_AP, struct.pack("<IIffff4f", 1, 2, 0.1, 1, 2, 3, 4, 5, 6, 7))
    )
    assert isinstance(baseband_ap, BasebandAmplitudePhaseMessage)
    np.testing.assert_array_equal(baseband_ap.amplitude, [4, 5])

    respiration = decode_message(
        _app(CONTENT_ID_RESPIRATION_STATUS, struct.pack("<IIIffI", 1, 2, 12, 3, 4, 5))
    )
    vital = decode_message(_app(CONTENT_ID_VITAL_SIGNS, struct.pack("<II10f", 1, 2, *range(10))))
    moving = decode_message(
        _app(CONTENT_ID_RESPIRATION_MOVING_LIST, struct.pack("<II4f", 4, 2, 1, 2, 3, 4))
    )
    detection = decode_message(
        _app(
            CONTENT_ID_RESPIRATION_DETECTION_LIST,
            struct.pack("<II6f", 4, 2, 1, 2, 3, 4, 5, 6),
        )
    )
    normalized = decode_message(
        _app(CONTENT_ID_NORMALIZED_MOVEMENT, struct.pack("<IffI4f", 4, 0, 0.5, 2, 1, 2, 3, 4))
    )
    assert isinstance(respiration, RespirationStatus)
    assert isinstance(vital, VitalSigns)
    assert isinstance(moving, RespirationMovingList)
    assert isinstance(detection, RespirationDetectionList)
    assert isinstance(normalized, NormalizedMovementList)

    matrix_header = struct.pack("<6I7f", 1, 2, 0, 3, 2, 0, -10, 0.5, 17, 8.5, 0, 1, 2)
    matrix = decode_message(_app(CONTENT_ID_NOISEMAP_BYTE, matrix_header + b"\x01\x02"))
    assert isinstance(matrix, MatrixMessage) and matrix.values.dtype == np.uint8


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\x10x",
        b"\x20",
        b"\x01",
        b"\x01\x00\x00\x00\x00",
        b"\x11\x12",
        b"\x11\xff" + struct.pack("<II", 1, 2),
        b"\xa0\x12" + b"\0" * 9,
        b"\xa0\x13" + struct.pack("<III", 1, 2, 1) + b"\xff",
        b"\x50",
        _app(CONTENT_ID_RESPIRATION_MOVING_LIST, struct.pack("<II", 1, 2)),
        b"\x50" + struct.pack("<IIIffff", CONTENT_ID_BASEBAND_IQ, 1, 2, 0, 0, 0, 0),
    ],
)
def test_malformed_and_truncated_layout_rejection(payload: bytes) -> None:
    with pytest.raises(MalformedMessageError):
        decode_message(payload)


def test_empty_and_unknown_layout_variants() -> None:
    common = struct.pack("<II", 1, 2)
    empty_float = decode_message(b"\xa0\x12" + common)
    assert isinstance(empty_float, DataFloatMessage) and empty_float.samples.size == 0
    assert decode_message(b"\xa0\x10" + common).data == b""  # type: ignore[union-attr]
    assert isinstance(decode_message(b"\xa0\x11" + common), UnknownMessage)
    assert isinstance(decode_message(b"\xa0\xff"), UnknownMessage)
    assert isinstance(decode_message(b"\x50" + struct.pack("<I", 99)), UnknownMessage)
    with pytest.raises(MalformedMessageError, match="NONE"):
        decode_message(b"\x11\x00" + common + b"\x01")
    with pytest.raises(MalformedMessageError, match="element size"):
        decode_message(b"\x11\x10" + common + struct.pack("<I", 1) + b"x\x02")
    with pytest.raises(MalformedMessageError, match="UTF-8"):
        decode_message(b"\x11\x13" + common + struct.pack("<I", 1) + b"\xff\x01")
