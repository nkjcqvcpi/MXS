import struct

import numpy as np
import pytest

from mxs.constants import CONTENT_ID_BASEBAND_IQ, CONTENT_ID_RAW_FRAME
from mxs.errors import InvalidIqFrameError, MalformedMessageError
from mxs.messages import data_float_to_iq, decode_message
from mxs.models import (
    Ack,
    BasebandIqMessage,
    DataFloatMessage,
    ErrorResponse,
    FloatReply,
    IntReply,
    Pong,
    UnknownMessage,
)


def data_float(samples: list[float], counter: int = 4) -> bytes:
    return (
        b"\xa0\x12"
        + struct.pack("<III", CONTENT_ID_RAW_FRAME, counter, len(samples))
        + struct.pack(f"<{len(samples)}f", *samples)
    )


def test_control_messages_and_unknown() -> None:
    assert decode_message(b"\x10") == Ack()
    assert decode_message(b"\x20\x34\x12\x00\x00") == ErrorResponse(0x1234)
    assert decode_message(b"\x01" + struct.pack("<I", 0xAAEEAEEA)) == Pong(0xAAEEAEEA, True)
    assert isinstance(decode_message(b"\x99abc"), UnknownMessage)


def test_data_float_and_iq_vectorization() -> None:
    message = decode_message(data_float([1.0, np.nan, 2.0, np.inf]))
    assert isinstance(message, DataFloatMessage)
    assert message.samples.dtype == np.float32
    iq = data_float_to_iq(message)
    assert iq.dtype == np.complex64
    assert iq[0] == np.complex64(1 + 2j)
    odd = decode_message(data_float([1.0]))
    assert isinstance(odd, DataFloatMessage)
    with pytest.raises(InvalidIqFrameError):
        data_float_to_iq(odd)


@pytest.mark.parametrize(
    "payload", [b"", b"\x10x", data_float([1.0])[:-1], b"\xa0\x12" + b"\0" * 9]
)
def test_malformed_messages(payload: bytes) -> None:
    with pytest.raises(MalformedMessageError):
        decode_message(payload)


def test_reply_and_data_edge_variants() -> None:
    common = struct.pack("<II", 1, 2)
    assert decode_message(b"\x11\x00" + common).element_count == 0  # type: ignore[union-attr]
    with pytest.raises(MalformedMessageError, match="NONE"):
        decode_message(b"\x11\x00" + common + b"\x01")
    assert decode_message(b"\x11\x11" + common).element_count == 0  # type: ignore[union-attr]
    assert decode_message(b"\x11\x13" + common + b"\x01").element_count == 0  # type: ignore[union-attr]
    with pytest.raises(MalformedMessageError, match="unknown REPLY"):
        decode_message(b"\x11\xff" + common)
    with pytest.raises(MalformedMessageError, match="UTF-8"):
        decode_message(b"\x11\x13" + common + struct.pack("<I", 1) + b"\xff\x01")
    assert decode_message(b"\x11\x10" + common + struct.pack("<I", 1) + b"x\x01").values == b"x"  # type: ignore[union-attr]
    assert decode_message(b"\x11\x50" + common + struct.pack("<I", 1) + b"y\x01").value == b"y"  # type: ignore[union-attr]
    with pytest.raises(MalformedMessageError, match="element size"):
        decode_message(b"\x11\x10" + common + struct.pack("<I", 1) + b"x\x02")
    assert isinstance(decode_message(b"\xa0\xff"), UnknownMessage)
    empty_float = decode_message(b"\xa0\x12" + common)
    assert isinstance(empty_float, DataFloatMessage) and empty_float.samples.size == 0
    assert decode_message(b"\xa0\x10" + common).data == b""  # type: ignore[union-attr]
    assert isinstance(decode_message(b"\xa0\x11" + common), UnknownMessage)
    with pytest.raises(MalformedMessageError, match="DATA STRING"):
        decode_message(b"\xa0\x13" + common + struct.pack("<I", 1) + b"\xff")


def test_baseband_iq_appdata() -> None:
    header = b"\x50" + struct.pack("<IIIffff", CONTENT_ID_BASEBAND_IQ, 8, 2, 0.1, 1.0, 7.29, -0.5)
    payload = header + struct.pack("<ffff", 1.0, 2.0, 3.0, 4.0)
    message = decode_message(payload)
    assert isinstance(message, BasebandIqMessage)
    assert message.samples.dtype == np.complex64
    np.testing.assert_array_equal(message.samples, np.asarray([1 + 3j, 2 + 4j], np.complex64))


def test_reply_short_long_and_unknown_datatype() -> None:
    short = b"\x11\x12" + struct.pack("<II", 3, 4) + b"\x04"
    decoded = decode_message(short)
    assert isinstance(decoded, FloatReply)
    assert decoded.element_count == 0
    long = b"\x11\x12" + struct.pack("<III", 3, 4, 2) + struct.pack("<ff", 1, 2) + b"\x04"
    decoded = decode_message(long)
    assert isinstance(decoded, FloatReply)
    np.testing.assert_array_equal(decoded.values, [1, 2])
    integer_without_size = b"\x11\x11" + struct.pack("<IIIi", 7, 0, 1, 42)
    integer = decode_message(integer_without_size)
    assert isinstance(integer, IntReply)
    assert integer.values.tolist() == [42]
    with pytest.raises(MalformedMessageError):
        decode_message(long[:-1])
    with pytest.raises(MalformedMessageError):
        decode_message(b"\x11\x99" + struct.pack("<II", 3, 4))


def test_zero_data_unknown_data_and_unknown_appdata() -> None:
    zero = decode_message(b"\xa0\x12" + struct.pack("<II", 0, 1))
    assert isinstance(zero, DataFloatMessage)
    assert zero.samples.size == 0
    with pytest.raises(MalformedMessageError):
        decode_message(b"\xa0\x10")
    assert isinstance(decode_message(b"\x50" + struct.pack("<I", 99)), UnknownMessage)


@pytest.mark.parametrize(
    "payload",
    [
        b"\x20",
        b"\x01",
        b"\x01\x00\x00\x00\x00",
        b"\x11\x12",
        b"\x50",
        b"\x50" + struct.pack("<I", 0x2375A16C),
        b"\x50" + struct.pack("<IIIffff", CONTENT_ID_BASEBAND_IQ, 1, 2, 0, 0, 0, 0),
    ],
)
def test_strict_control_and_appdata_bounds(payload: bytes) -> None:
    with pytest.raises(MalformedMessageError):
        decode_message(payload)
