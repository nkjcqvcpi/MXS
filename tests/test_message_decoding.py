"""Message decoding from packets captured from the connected X4M200."""

import struct
from dataclasses import replace

import numpy as np
import pytest

from mxs import X4M200, X4Config
from mxs.constants import (
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
    DataType,
    ResponseType,
    SensorMode,
)
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
@pytest.mark.stateful
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


@pytest.mark.hardware
@pytest.mark.stateful
def test_source_backed_mutations_of_live_packets_cover_supported_layouts(
    device_port: str,
) -> None:
    chunks: list[bytes] = []
    with X4M200(port=device_port, raw_chunk_callback=chunks.append) as device:
        assert device.module.ping().ready
        device.configure(X4Config())
        device.start()
        device.read_frame(timeout=2.0)
        device.stop()
        assert device.profile.get_profileid() >= 0
        worker = device._session.worker  # pyright: ignore[reportPrivateUsage]
        assert worker is not None
        worker.flush_callbacks(2.0)
        decoder = McpStreamDecoder()
        captured = [payload for chunk in chunks for payload in decoder.feed(chunk)]
        app_seed = next(payload for payload in captured if payload[0] == ResponseType.DATA)
        reply_seed = next(payload for payload in captured if payload[0] == ResponseType.REPLY)
        ack_seed = next(payload for payload in captured if payload[0] == ResponseType.ACK)
        pong_seed = next(payload for payload in captured if payload[0] == ResponseType.PONG)

        def app(content_id: int, data: bytes) -> bytes:
            return bytes((ResponseType.APPDATA,)) + struct.pack("<I", content_id) + data

        application_payloads = (
            app(CONTENT_ID_SLEEP_STATUS, struct.pack("<IIffIff", 1, 2, 3, 4, 5, 6, 7)),
            app(
                CONTENT_ID_BASEBAND_AP,
                struct.pack("<IIffff4f", 1, 2, 0.1, 1.0, 7.0, 0.0, 1, 2, 3, 4),
            ),
            app(CONTENT_ID_VITAL_SIGNS, struct.pack("<II10f", 1, 2, *range(10))),
            app(CONTENT_ID_RESPIRATION_STATUS, struct.pack("<IIIffI", 1, 2, 3, 4, 5, 6)),
            app(
                CONTENT_ID_RESPIRATION_MOVING_LIST,
                struct.pack("<II4f", 1, 2, 1, 2, 3, 4),
            ),
            app(
                CONTENT_ID_RESPIRATION_DETECTION_LIST,
                struct.pack("<II6f", 1, 2, 1, 2, 3, 4, 5, 6),
            ),
            app(
                CONTENT_ID_NORMALIZED_MOVEMENT,
                struct.pack("<IffI4f", 1, 0.0, 0.5, 2, 1, 2, 3, 4),
            ),
        )
        matrix_prefix = struct.pack("<6I", 1, 2, 0, 3, 2, 0)
        matrix_tail = struct.pack("<5f", 17, 8.5, 0, 1, 2)
        application_payloads += (
            app(
                CONTENT_ID_PULSE_DOPPLER_FLOAT,
                matrix_prefix + matrix_tail + struct.pack("<2f", 1, 2),
            ),
            app(
                CONTENT_ID_NOISEMAP_FLOAT,
                matrix_prefix + matrix_tail + struct.pack("<2f", 1, 2),
            ),
            app(
                CONTENT_ID_PULSE_DOPPLER_BYTE,
                matrix_prefix + struct.pack("<2f", -10, 0.5) + matrix_tail + b"\x01\x02",
            ),
            app(
                CONTENT_ID_NOISEMAP_BYTE,
                matrix_prefix + struct.pack("<2f", -10, 0.5) + matrix_tail + b"\x01\x02",
            ),
            app(0xFFFFFFFF, app_seed[5:]),
        )

        data_seed = app_seed

        def data(data_type: DataType, content: bytes) -> bytes:
            return (
                data_seed[:1]
                + bytes((data_type,))
                + struct.pack("<II", 1, 2)
                + struct.pack("<I", len(content))
                + content
            )

        generic_payloads = (
            data(DataType.BYTE, b"ab"),
            data(DataType.STRING, b"hi"),
            data(DataType.USER, b"xy"),
            data(DataType.INT, b"ab"),
            data_seed[:1] + b"\xff" + data_seed[2:10],
            data_seed[:1] + bytes((DataType.FLOAT,)) + struct.pack("<II", 1, 2),
            data_seed[:1] + bytes((DataType.BYTE,)) + struct.pack("<II", 1, 2),
        )

        def typed_reply(data_type: DataType, content: bytes) -> bytes:
            return (
                reply_seed[:1]
                + bytes((data_type,))
                + struct.pack("<II", 1, 0)
                + struct.pack("<I", len(content) // (4 if data_type is DataType.FLOAT else 1))
                + content
                + bytes((4 if data_type is DataType.FLOAT else 1,))
            )

        reply_payloads = (
            reply_seed[:1] + bytes((DataType.NONE,)) + struct.pack("<II", 1, 0),
            reply_seed[:1] + bytes((DataType.BYTE,)) + struct.pack("<II", 1, 0) + b"\x01",
            typed_reply(DataType.BYTE, b"x"),
            typed_reply(DataType.FLOAT, struct.pack("<f", 1.0)),
            typed_reply(DataType.STRING, b"ok"),
            typed_reply(DataType.USER, b"z"),
        )
        system_payload = bytes((ResponseType.SYSTEM,)) + reply_seed[2:6] + b"live-copy"

        for payload in application_payloads + generic_payloads + reply_payloads + (system_payload,):
            message = decode_message(payload)
            device._session.router.route(  # pyright: ignore[reportPrivateUsage]
                message, payload
            )

        malformed = (
            ack_seed + b"x",
            bytes((ResponseType.ERROR,)) + ack_seed,
            pong_seed[:-1],
            pong_seed[:1] + struct.pack("<I", 0),
            app_seed[:1],
            app_seed[:-1],
            app(CONTENT_ID_BASEBAND_IQ, struct.pack("<IIIffff", 1, 2, 2, 0, 0, 0, 0)),
            application_payloads[0][:-1],
            application_payloads[1][:-1],
            application_payloads[2][:-1],
            application_payloads[3][:-1],
            application_payloads[4][:-1],
            application_payloads[5][:-1],
            application_payloads[6][:-1],
            application_payloads[7][:-1],
            data(DataType.STRING, b"\xff"),
            reply_seed[:1] + bytes((DataType.NONE,)) + struct.pack("<II", 1, 0) + b"\x00\x00",
            reply_seed[:1] + bytes((DataType.NONE,)) + struct.pack("<II", 1, 0) + b"\x01",
            reply_seed[:1] + bytes((DataType.BYTE,)) + struct.pack("<II", 1, 0) + b"\x02",
            typed_reply(DataType.BYTE, b"x")[:-1] + b"\x02",
            data(DataType.BYTE, b"ab")[:-1],
            reply_seed[:1] + bytes((DataType.STRING,)) + struct.pack("<III", 1, 0, 1) + b"\xff\x01",
        )
        for payload in malformed:
            with pytest.raises(MalformedMessageError):
                decode_message(payload)
