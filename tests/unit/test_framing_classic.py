import pytest

from mxs.constants import ESCAPE_BYTE, START_BYTE, STOP_BYTE
from mxs.framing import DecoderState, McpStreamDecoder, encode_classic_frame


@pytest.mark.parametrize("payload", [b"", b"abc", bytes([START_BYTE, STOP_BYTE, ESCAPE_BYTE])])
def test_classic_round_trip(payload: bytes) -> None:
    decoder = McpStreamDecoder()
    assert decoder.feed(encode_classic_frame(payload)) == [payload]


def test_escaped_checksum() -> None:
    payload = bytes((START_BYTE ^ ESCAPE_BYTE,))
    frame = encode_classic_frame(payload)
    assert frame[-3] == ESCAPE_BYTE
    assert McpStreamDecoder().feed(frame) == [payload]


def test_every_chunk_split_and_concatenation() -> None:
    packet = encode_classic_frame(b"fragmented")
    for split in range(len(packet) + 1):
        decoder = McpStreamDecoder()
        assert decoder.feed(packet[:split]) + decoder.feed(packet[split:]) == [b"fragmented"]
    decoder = McpStreamDecoder()
    assert decoder.feed(packet + encode_classic_frame(b"second")) == [b"fragmented", b"second"]


def test_noise_restart_crc_and_recovery() -> None:
    decoder = McpStreamDecoder()
    bad = bytearray(encode_classic_frame(b"bad"))
    bad[-2] ^= 1
    stream = b"noise" + bytes((START_BYTE, 1, 2, START_BYTE)) + bytes(bad[1:])
    assert decoder.feed(stream + encode_classic_frame(b"good")) == [b"good"]
    assert decoder.statistics.crc_errors == 1
    assert decoder.statistics.resynchronizations == 1


def test_oversize_truncated_and_reset() -> None:
    decoder = McpStreamDecoder(max_packet_size=2)
    decoder.feed(bytes((START_BYTE, 1, 2, 3, 4)))
    assert decoder.state is DecoderState.SEARCHING
    assert decoder.statistics.oversized_packets == 1
    decoder.feed(encode_classic_frame(b"x")[:-1])
    decoder.finalize()
    assert decoder.statistics.malformed_packets == 1
    assert decoder.feed(encode_classic_frame(b"ok")) == [b"ok"]


def test_invalid_limit_and_empty_wire_frame() -> None:
    with pytest.raises(ValueError):
        McpStreamDecoder(0)
    decoder = McpStreamDecoder()
    assert decoder.feed(bytes((START_BYTE, STOP_BYTE))) == []
    assert decoder.statistics.malformed_packets == 1
