"""Deterministic protocol regressions gated by real-device preflight."""

import struct
from collections.abc import Callable

import pytest

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
from mxs.constants import NO_ESCAPE_MARKER, OutputFeature, ProfileId, SensorMode, X4Parameter
from mxs.errors import ReplyMismatchError
from mxs.expectations import reply
from mxs.framing import DecoderState, McpStreamDecoder, encode_classic_frame
from mxs.messages import decode_message
from mxs.models import ByteReply, FloatReply, IntReply, Pong, Reply, StringReply


@pytest.mark.hardware
def test_live_classic_framing_fragmentation_checksum_and_truncation(device_port: str) -> None:
    from mxs import X4M200

    chunks: list[bytes] = []
    with X4M200(port=device_port, raw_chunk_callback=chunks.append) as device:
        assert device.module.ping().ready
        assert device.module.get_system_info(1) == "X4M200"
    decoder = McpStreamDecoder()
    payloads = [payload for chunk in chunks for payload in decoder.feed(chunk)]
    assert payloads
    payload = payloads[0]
    wire = encode_classic_frame(payload)
    for split in range(len(wire) + 1):
        decoder = McpStreamDecoder()
        assert decoder.feed(wire[:split]) + decoder.feed(wire[split:]) == [payload]
    bad = bytearray(wire)
    bad[-2] = next(value for value in range(256) if value not in {0x7D, 0x7E, 0x7F, bad[-2]})
    decoder = McpStreamDecoder()
    assert decoder.feed(bytes(bad) + wire) == [payload]
    assert decoder.statistics.crc_errors == 1
    decoder = McpStreamDecoder(max_packet_size=max(1, len(payload) - 1))
    decoder.feed(wire)
    assert decoder.state is DecoderState.SEARCHING
    assert decoder.statistics.oversized_packets == 1
    decoder = McpStreamDecoder()
    decoder.feed(wire[:-1])
    decoder.finalize()
    assert decoder.statistics.malformed_packets == 1
    with pytest.raises(ValueError):
        McpStreamDecoder(0)


@pytest.mark.hardware
def test_live_noescape_fragmentation_length_and_truncation(device_port: str) -> None:
    from mxs import X4M200, X4Config

    chunks: list[bytes] = []
    with X4M200(port=device_port, raw_chunk_callback=chunks.append) as device:
        device.configure(X4Config())
        device.start()
        device.read_frame(timeout=2.0)
        device.stop()
    wire = b"".join(chunks)
    start = wire.find(NO_ESCAPE_MARKER)
    assert start >= 0
    length = struct.unpack_from("<I", wire, start + 4)[0]
    packet = wire[start : start + 9 + length]
    assert len(packet) == 9 + length
    payload = packet[9:]
    for split in range(len(packet) + 1):
        decoder = McpStreamDecoder()
        assert decoder.feed(packet[:split]) + decoder.feed(packet[split:]) == [payload]
    zero = bytearray(packet[:8])
    zero[4:8] = struct.pack("<I", 0)
    decoder = McpStreamDecoder()
    assert decoder.feed(bytes(zero)) == []
    assert decoder.statistics.malformed_packets == 1
    oversized = bytearray(packet[:8])
    oversized[4:8] = struct.pack("<I", length + 1)
    decoder = McpStreamDecoder(max_packet_size=length)
    assert decoder.feed(bytes(oversized)) == []
    assert decoder.statistics.oversized_packets == 1
    decoder = McpStreamDecoder()
    decoder.feed(packet[:-1])
    decoder.finalize()
    assert decoder.statistics.malformed_packets == 1


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
        build_parameter_file("a.txt", b"value"),
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
        lambda: build_load_profile(-1),
        lambda: build_system_info(256),
        lambda: build_set_detection_zone(1, 1),
        lambda: build_set_detection_zone(float("inf"), 2),
        lambda: build_parameter_file("a" * 256),
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


@pytest.mark.hardware
@pytest.mark.stateful
def test_live_reply_content_ids_match_target_producers(device_port: str) -> None:
    from mxs import X4M200, X4Config

    chunks: list[bytes] = []
    with X4M200(port=device_port, raw_chunk_callback=chunks.append) as device:
        device.profile.load_profile(ProfileId.RESPIRATION_2)

        def capture_reply(call: Callable[[], object]) -> bytes:
            before = len(chunks)
            call()
            worker = device._session.worker  # pyright: ignore[reportPrivateUsage]
            assert worker is not None
            worker.flush_callbacks(2.0)
            decoder = McpStreamDecoder()
            payloads = [
                payload
                for chunk in chunks[before:]
                for payload in decoder.feed(chunk)
                if isinstance(decode_message(payload), Reply)
            ]
            assert payloads
            return payloads[-1]

        files = device.filesystem.find_all_files()
        cases: list[tuple[bytes, type[Reply], int, int, int]] = [
            (capture_reply(lambda: device.module.get_system_info(1)), StringReply, 0x58, 6, 1),
            (capture_reply(device.profile.get_sensor_mode), ByteReply, 0, 1, 0),
            (capture_reply(device.profile.get_profileid), IntReply, 0, 1, 0),
            (
                capture_reply(lambda: device.outputs.get_output_control(OutputFeature.BASEBAND_IQ)),
                IntReply,
                0,
                1,
                0,
            ),
            (capture_reply(lambda: device.gpio.get_iopin_control(1)), IntReply, 0, 2, 0),
            (capture_reply(lambda: device.gpio.get_iopin_value(1)), IntReply, 0x21, 1, 0),
            (capture_reply(device.filesystem.find_all_files), IntReply, 0, len(files) * 2, 0),
            (
                capture_reply(lambda: device.filesystem.search_for_file_by_type(0)),
                IntReply,
                0,
                0,
                0,
            ),
            (capture_reply(device.profile.get_sensitivity), IntReply, 0, 1, 0),
            (
                capture_reply(device.profile.get_tx_center_frequency),
                IntReply,
                0,
                1,
                0,
            ),
            (
                capture_reply(device.profile.get_detection_zone),
                FloatReply,
                0,
                2,
                0,
            ),
            (
                capture_reply(device.profile.get_detection_zone_limits),
                FloatReply,
                0,
                3,
                0,
            ),
            (
                capture_reply(device.profile.get_led_control),
                ByteReply,
                0,
                1,
                0,
            ),
            (capture_reply(device.noisemap.get_noisemap_control), IntReply, 0, 1, 0),
        ]
        if files:
            first = files[0]
            cases.append(
                (
                    capture_reply(
                        lambda: device.filesystem.get_file_length(first.file_type, first.identifier)
                    ),
                    IntReply,
                    0,
                    1,
                    0,
                )
            )
        device.configure(X4Config())
        x4_cases: tuple[tuple[Callable[[], object], type[Reply], X4Parameter | int, int], ...] = (
            (device.xep.x4driver_get_fps, FloatReply, X4Parameter.FPS, 1),
            (device.xep.x4driver_get_iterations, IntReply, X4Parameter.ITERATIONS, 1),
            (
                device.xep.x4driver_get_pulses_per_step,
                IntReply,
                X4Parameter.PULSES_PER_STEP,
                1,
            ),
            (device.xep.x4driver_get_dac_min, IntReply, X4Parameter.DAC_MIN, 1),
            (device.xep.x4driver_get_dac_max, IntReply, X4Parameter.DAC_MAX, 1),
            (device.xep.x4driver_get_tx_power, ByteReply, X4Parameter.TX_POWER, 1),
            (
                device.xep.x4driver_get_downconversion,
                ByteReply,
                X4Parameter.DOWNCONVERSION,
                1,
            ),
            (device.xep.x4driver_get_frame_bin_count, IntReply, 0x26, 1),
            (device.xep.x4driver_get_frame_area, FloatReply, X4Parameter.FRAME_AREA, 2),
            (
                device.xep.x4driver_get_frame_area_offset,
                FloatReply,
                X4Parameter.FRAME_AREA_OFFSET,
                1,
            ),
            (
                device.xep.x4driver_get_tx_center_frequency,
                ByteReply,
                X4Parameter.TX_CENTER_FREQUENCY,
                1,
            ),
            (device.xep.x4driver_get_prf_div, ByteReply, X4Parameter.PRF_DIV, 1),
        )
        cases.extend(
            (capture_reply(call), reply_class, int(content_id), count, 0)
            for call, reply_class, content_id, count in x4_cases
        )

        for payload, reply_class, source_id, count, info in cases:
            expectation = reply(
                reply_class, content_ids={source_id}, info=info, element_count=count
            )
            observed = decode_message(payload)
            assert isinstance(observed, Reply)
            expectation.validate(observed)
            wrong_content = bytearray(payload)
            wrong_content[2:6] = struct.pack("<I", 0xFFFFFFFF if source_id == 0 else 0)
            with pytest.raises(ReplyMismatchError, match="content ID"):
                expectation.validate(decode_message(bytes(wrong_content)))  # type: ignore[arg-type]
