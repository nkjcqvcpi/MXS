"""Message decoding from packets captured from the connected X4M200."""

from dataclasses import replace

import numpy as np
import pytest

from mxs import X4M200, X4Config
from mxs.constants import SensorMode
from mxs.errors import InvalidIqFrameError, MalformedMessageError
from mxs.framing import McpStreamDecoder
from mxs.messages import data_float_to_iq, decode_message
from mxs.models import (
    ByteReply,
    DataFloatMessage,
    IntReply,
    Pong,
    Reply,
    StringReply,
    UnknownMessage,
)


def _decode_chunks(chunks: list[bytes]) -> list[object]:
    decoder = McpStreamDecoder()
    return [decode_message(payload) for chunk in chunks for payload in decoder.feed(chunk)]


@pytest.mark.hardware
def test_live_control_and_reply_layouts(device_port: str) -> None:
    chunks: list[bytes] = []
    with X4M200(port=device_port, raw_chunk_callback=chunks.append) as device:
        assert device.module.ping().ready
        assert device.module.get_system_info(1) == "X4M200"
        assert device.profile.get_sensor_mode() is SensorMode.STOP
        assert isinstance(device.profile.get_profileid(), int)
    decoded = _decode_chunks(chunks)
    assert any(isinstance(message, Pong) for message in decoded)
    assert any(isinstance(message, StringReply) for message in decoded)
    assert any(isinstance(message, ByteReply) for message in decoded)
    assert any(isinstance(message, IntReply) for message in decoded)


@pytest.mark.hardware
def test_live_data_layout_and_iq_conversion(device_port: str) -> None:
    chunks: list[bytes] = []
    with X4M200(port=device_port, raw_chunk_callback=chunks.append) as device:
        device.configure(X4Config(downconversion=False))
        device.start()
        frame = device.read_frame(timeout=2.0)
        device.stop()
        decoded = _decode_chunks(chunks)
        raw = next(message for message in decoded if isinstance(message, DataFloatMessage))
        assert raw.samples.dtype == np.float32
        assert np.array_equal(raw.samples, frame.samples, equal_nan=True)
        iq = data_float_to_iq(raw)
        assert iq.dtype == np.complex64
        odd = replace(raw, samples=raw.samples[:-1])
        with pytest.raises(InvalidIqFrameError):
            data_float_to_iq(odd)


@pytest.mark.hardware
def test_mutated_live_packets_reject_malformed_layouts(device_port: str) -> None:
    chunks: list[bytes] = []
    with X4M200(port=device_port, raw_chunk_callback=chunks.append) as device:
        assert device.profile.get_profileid() >= 0
    decoder = McpStreamDecoder()
    payloads = [payload for chunk in chunks for payload in decoder.feed(chunk)]
    reply_payload = next(
        payload for payload in payloads if isinstance(decode_message(payload), Reply)
    )
    for truncated in (reply_payload[:0], reply_payload[:1], reply_payload[:-1]):
        with pytest.raises(MalformedMessageError):
            decode_message(truncated)
    bad_datatype = bytearray(reply_payload)
    bad_datatype[1] = 0xFF
    with pytest.raises(MalformedMessageError, match="datatype"):
        decode_message(bytes(bad_datatype))
    unknown = bytearray(reply_payload)
    unknown[0] = 0x99
    assert isinstance(decode_message(bytes(unknown)), UnknownMessage)
