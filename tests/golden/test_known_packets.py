from pathlib import Path

from x4cir.framing import McpStreamDecoder
from x4cir.messages import decode_message
from x4cir.models import DataFloatMessage, SleepStatus
from x4cir.recording import replay_wire


def test_sleep_status_hardware_fixture() -> None:
    fixture = Path(__file__).parent / "fixtures" / "sleep_status.hex"
    decoder = McpStreamDecoder()
    payloads = decoder.feed(bytes.fromhex(fixture.read_text()))
    assert len(payloads) == 1
    assert decode_message(payloads[0]) == SleepStatus(1360, 4, 0.0, 0.0, 0, 0.0, 0.0)
    assert decoder.statistics.crc_errors == 0


def test_real_rf_wire_replay_includes_noescape_frames() -> None:
    fixture = Path(__file__).parent / "fixtures" / "device_rf_baseline.mcpbin"
    decoder = McpStreamDecoder()
    frames: list[DataFloatMessage] = []
    for chunk in replay_wire(fixture):
        for payload in decoder.feed(chunk):
            message = decode_message(payload)
            if isinstance(message, DataFloatMessage):
                frames.append(message)
    assert len(frames) >= 100
    assert {frame.samples.size for frame in frames} == {846}
    assert decoder.statistics.noescape_packets >= 100
    assert decoder.statistics.crc_errors == 0
