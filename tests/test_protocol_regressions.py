"""Deterministic protocol regressions gated by real-device preflight."""

import struct

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mxs.commands import (
    build_app_action,
    build_app_get,
    build_app_set,
    build_debug_level,
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
    build_set_baudrate,
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
    build_system_info,
    build_x4_get,
    build_x4_init,
    build_x4_read,
    build_x4_write,
)
from mxs.constants import (
    ESCAPE_BYTE,
    NO_ESCAPE_MARKER,
    START_BYTE,
    STOP_BYTE,
    ProfileId,
    SensorMode,
)
from mxs.framing import DecoderState, McpStreamDecoder, encode_classic_frame
from mxs.messages import decode_message
from mxs.models import ByteReply, Pong, StringReply


@pytest.mark.parametrize("payload", [b"", b"abc", bytes([START_BYTE, STOP_BYTE, ESCAPE_BYTE])])
def test_classic_framing_escape_checksum_and_incremental_chunks(payload: bytes) -> None:
    wire = encode_classic_frame(payload)
    for split in range(len(wire) + 1):
        decoder = McpStreamDecoder()
        assert decoder.feed(wire[:split]) + decoder.feed(wire[split:]) == [payload]
    assert McpStreamDecoder().feed(wire + encode_classic_frame(b"next")) == [payload, b"next"]


def test_classic_malformed_truncated_oversized_and_recovery() -> None:
    decoder = McpStreamDecoder(max_packet_size=4)
    bad = bytearray(encode_classic_frame(b"bad"))
    bad[-2] ^= 1
    assert decoder.feed(bytes(bad) + encode_classic_frame(b"ok")) == [b"ok"]
    assert decoder.statistics.crc_errors == 1
    decoder.feed(bytes((START_BYTE, 1, 2, 3, 4, 5, 6)))
    assert decoder.state is DecoderState.SEARCHING
    assert decoder.statistics.oversized_packets == 1
    decoder.feed(encode_classic_frame(b"x")[:-1])
    decoder.finalize()
    assert decoder.statistics.malformed_packets == 1
    assert McpStreamDecoder().feed(bytes((START_BYTE, STOP_BYTE))) == []
    with pytest.raises(ValueError):
        McpStreamDecoder(0)


def _noescape(payload: bytes, checksum: int = 0) -> bytes:
    return NO_ESCAPE_MARKER + struct.pack("<I", len(payload)) + bytes((checksum,)) + payload


def test_noescape_boundaries_mixed_modes_and_rejection() -> None:
    packet = _noescape(b"payload")
    for split in range(len(packet) + 1):
        decoder = McpStreamDecoder()
        assert decoder.feed(packet[:split]) + decoder.feed(packet[split:]) == [b"payload"]
    decoder = McpStreamDecoder(max_packet_size=8)
    assert decoder.feed(_noescape(bytes(range(0x7C, 0x80))) + encode_classic_frame(b"c")) == [
        bytes(range(0x7C, 0x80)),
        b"c",
    ]
    assert decoder.feed(NO_ESCAPE_MARKER + struct.pack("<I", 0)) == []
    assert decoder.statistics.malformed_packets == 1
    assert decoder.feed(NO_ESCAPE_MARKER + struct.pack("<I", 9)) == []
    assert decoder.statistics.oversized_packets == 1
    decoder.feed(_noescape(b"abc")[:-1])
    decoder.finalize()
    assert decoder.feed(_noescape(b"ok")) == [b"ok"]


@settings(max_examples=25, deadline=None, derandomize=True)
@given(st.binary(max_size=1024), st.lists(st.integers(min_value=1, max_value=64), max_size=20))
def test_property_classic_round_trip_fragmentation(payload: bytes, sizes: list[int]) -> None:
    wire = encode_classic_frame(payload)
    decoder = McpStreamDecoder(max_packet_size=2048)
    frames: list[bytes] = []
    offset = 0
    for size in sizes:
        frames.extend(decoder.feed(wire[offset : offset + size]))
        offset += size
    frames.extend(decoder.feed(wire[offset:]))
    assert frames == [payload]


def test_command_builders_and_validation() -> None:
    packets = (
        build_ping(),
        build_set_sensor_mode(SensorMode.STOP),
        build_set_sensor_mode(SensorMode.NORMAL, 1),
        build_set_baudrate(115200),
        build_x4_init(),
        build_get_sensor_mode(),
        build_load_profile(ProfileId.RESPIRATION_2),
        build_module_reset(),
        build_debug_level(1),
        build_system_info(2),
        build_app_get(1),
        build_app_set(1, b"a"),
        build_app_action(0x13),
        build_set_detection_zone(0, 1),
        build_set_led_control(1, 2),
        build_set_output_control(1, 1),
        build_get_output_control(1),
        build_set_iopin_control(1, 2, 3),
        build_get_iopin_control(1),
        build_set_iopin_value(1, 1),
        build_get_iopin_value(1),
        build_noisemap(0x10, 1),
        build_filesystem(0x64, 1),
        build_parameter_file("a.txt"),
        build_prepare_inject_frame(1, 2, 0),
        build_inject_frame(1, 2, b"\0" * 16),
        build_x4_get(1),
        build_x4_read(1, b"a"),
        build_x4_write(1, b"a"),
        build_set_prf_div(16),
        build_set_fps(17),
        build_set_iterations(16),
        build_set_pulses_per_step(300),
        build_set_dac_min(949),
        build_set_dac_max(1100),
        build_set_downconversion(True),
        build_set_enable(True),
        build_set_frame_area(-0.5, 5),
        build_set_frame_area_offset(0.18),
        build_set_tx_center_frequency(3),
        build_set_tx_power(2),
    )
    assert all(packet.startswith(b"\x7d") and packet.endswith(b"\x7e") for packet in packets)
    assert build_set_baudrate(921600).hex() == "7d908000100e00737e"

    invalid = (
        lambda: build_set_baudrate(9600),
        lambda: build_set_fps(float("nan")),
        lambda: build_set_fps(-1),
        lambda: build_set_frame_area(2, 1),
        lambda: build_set_tx_power(8),
        lambda: build_set_downconversion(2),
        lambda: build_set_enable(2),
        lambda: build_set_tx_center_frequency(2),
        lambda: build_debug_level(10),
        lambda: build_parameter_file("../bad"),
        lambda: build_prepare_inject_frame(0, 1, 0),
        lambda: build_inject_frame(1, 2, b"bad"),
        lambda: build_set_prf_div(256),
    )
    for call in invalid:
        with pytest.raises(ValueError):
            call()


def test_profile_identifiers_are_source_exact() -> None:
    assert {member.name: int(member) for member in ProfileId} == {
        "RESPIRATION": 0x1423A2D6,
        "SLEEP": 0x00F17B17,
        "RESPIRATION_2": 0x064E57AD,
        "RESPIRATION_3": 0x47FABEBA,
        "RESPIRATION_4": 0x4AC5D074,
        "RESPIRATION_5": 0xA9E03260,
    }


def test_live_rx_bytes_decode_incrementally(device_port: str) -> None:
    from mxs import X4M200

    chunks: list[bytes] = []
    with X4M200(port=device_port, raw_chunk_callback=chunks.append) as device:
        assert device.module.ping().ready
        assert device.module.get_system_info(1) == "X4M200"
        assert device.profile.get_sensor_mode() is SensorMode.STOP
    assert chunks
    decoder = McpStreamDecoder()
    payloads = [payload for chunk in chunks for payload in decoder.feed(chunk)]
    assert payloads
    decoded = [decode_message(payload) for payload in payloads]
    assert any(isinstance(message, Pong) for message in decoded)
    assert any(isinstance(message, StringReply) for message in decoded)
    assert any(isinstance(message, ByteReply) for message in decoded)
    assert decoder.statistics.crc_errors == 0
