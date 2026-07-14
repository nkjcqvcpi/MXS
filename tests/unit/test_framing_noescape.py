import struct

from x4cir.constants import NO_ESCAPE_MARKER
from x4cir.framing import McpStreamDecoder, encode_classic_frame


def noescape(payload: bytes, checksum: int = 0) -> bytes:
    return NO_ESCAPE_MARKER + struct.pack("<I", len(payload)) + bytes((checksum,)) + payload


def test_marker_and_length_split_at_every_boundary() -> None:
    packet = noescape(b"payload")
    for split in range(len(packet) + 1):
        decoder = McpStreamDecoder()
        assert decoder.feed(packet[:split]) + decoder.feed(packet[split:]) == [b"payload"]


def test_special_payload_multiple_and_mixed_modes() -> None:
    control = bytes(range(0x7C, 0x80))
    decoder = McpStreamDecoder()
    stream = noescape(control) + noescape(b"two") + encode_classic_frame(b"classic")
    assert decoder.feed(stream) == [control, b"two", b"classic"]


def test_invalid_oversized_truncated_recovery() -> None:
    decoder = McpStreamDecoder(max_packet_size=8)
    assert decoder.feed(NO_ESCAPE_MARKER + struct.pack("<I", 0)) == []
    assert decoder.statistics.malformed_packets == 1
    assert decoder.feed(NO_ESCAPE_MARKER + struct.pack("<I", 9)) == []
    assert decoder.statistics.oversized_packets == 1
    decoder.feed(noescape(b"abc")[:-1])
    decoder.finalize()
    assert decoder.feed(noescape(b"ok")) == [b"ok"]
