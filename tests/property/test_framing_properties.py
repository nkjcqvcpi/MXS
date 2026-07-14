from hypothesis import given
from hypothesis import strategies as st

from mxs.framing import McpStreamDecoder, encode_classic_frame


@given(st.binary(max_size=4096), st.lists(st.integers(min_value=1, max_value=64), max_size=40))
def test_round_trip_arbitrary_fragmentation(payload: bytes, sizes: list[int]) -> None:
    wire = encode_classic_frame(payload)
    decoder = McpStreamDecoder(max_packet_size=8192)
    frames: list[bytes] = []
    offset = 0
    for size in sizes:
        frames.extend(decoder.feed(wire[offset : offset + size]))
        offset += size
    frames.extend(decoder.feed(wire[offset:]))
    assert frames == [payload]


@given(st.lists(st.binary(max_size=128), min_size=1, max_size=20), st.binary(max_size=20))
def test_concatenation_with_noise_prefix(payloads: list[bytes], noise: bytes) -> None:
    noise = noise.replace(b"\x7d", b"\x00").replace(b"\x7c\x7c\x7c\x7c", b"\x00")
    decoder = McpStreamDecoder()
    wire = noise + b"".join(encode_classic_frame(payload) for payload in payloads)
    assert decoder.feed(wire) == payloads
