"""Classic and no-escape MCP framing."""

from dataclasses import dataclass
from enum import Enum, auto

from .constants import (
    DEFAULT_MAX_PACKET_SIZE,
    ESCAPE_BYTE,
    NO_ESCAPE_MARKER,
    START_BYTE,
    STOP_BYTE,
)
from .errors import ChecksumError, FrameTooLargeError, ProtocolError


class DecoderState(Enum):
    SEARCHING = auto()
    IN_CLASSIC_FRAME = auto()
    CLASSIC_ESCAPED = auto()
    READING_NOESC_LENGTH = auto()
    READING_NOESC_PAYLOAD = auto()


@dataclass(slots=True)
class DecoderStatistics:
    classic_packets: int = 0
    noescape_packets: int = 0
    crc_errors: int = 0
    malformed_packets: int = 0
    oversized_packets: int = 0
    resynchronizations: int = 0
    noise_bytes: int = 0


def encode_classic_frame(payload: bytes | bytearray | memoryview) -> bytes:
    """Encode one independently checksummed classic MCP frame.

    Reference: Legacy-SW/MCPWrapper/mcp_wrapper_1.3.1/src/mcp/protocol.c
    (`packet_start`, `process_byte`, and `packet_end`).
    """
    checksum = START_BYTE
    encoded = bytearray((START_BYTE,))
    for value in memoryview(payload).cast("B"):
        checksum ^= value
        if value in (START_BYTE, STOP_BYTE, ESCAPE_BYTE):
            encoded.append(ESCAPE_BYTE)
        encoded.append(value)
    if checksum in (START_BYTE, STOP_BYTE, ESCAPE_BYTE):
        encoded.append(ESCAPE_BYTE)
    encoded.extend((checksum, STOP_BYTE))
    return bytes(encoded)


class McpStreamDecoder:
    """Incrementally decode a stream that alternates framing modes."""

    def __init__(self, max_packet_size: int = DEFAULT_MAX_PACKET_SIZE) -> None:
        if max_packet_size <= 0:
            raise ValueError("max_packet_size must be positive")
        self.max_packet_size = max_packet_size
        self.state = DecoderState.SEARCHING
        self.statistics = DecoderStatistics()
        self.errors: list[ProtocolError] = []
        self._classic = bytearray()
        self._marker_count = 0
        self._noesc_length = bytearray()
        self._noesc_payload = bytearray()
        self._noesc_expected = 0
        self._noesc_checksum_pending = False

    def reset(self) -> None:
        self.state = DecoderState.SEARCHING
        self._classic.clear()
        self._marker_count = 0
        self._noesc_length.clear()
        self._noesc_payload.clear()
        self._noesc_expected = 0
        self._noesc_checksum_pending = False

    def finalize(self) -> None:
        """Report and discard a truncated partial frame."""
        if self.state is not DecoderState.SEARCHING or self._marker_count:
            self.statistics.malformed_packets += 1
            self.errors.append(ProtocolError("truncated MCP frame"))
        self.reset()

    def feed(self, data: bytes | bytearray | memoryview) -> list[bytes]:
        frames: list[bytes] = []
        for value in memoryview(data).cast("B"):
            if self.state is DecoderState.SEARCHING:
                self._search(value)
            elif self.state is DecoderState.IN_CLASSIC_FRAME:
                self._classic_byte(value, frames)
            elif self.state is DecoderState.CLASSIC_ESCAPED:
                self._append_classic(value)
                self.state = DecoderState.IN_CLASSIC_FRAME
            elif self.state is DecoderState.READING_NOESC_LENGTH:
                self._length_byte(value)
            else:
                self._noescape_byte(value, frames)
        return frames

    def _search(self, value: int) -> None:
        if value == START_BYTE:
            self._marker_count = 0
            self._classic.clear()
            self.state = DecoderState.IN_CLASSIC_FRAME
            return
        if value == NO_ESCAPE_MARKER[0]:
            self._marker_count += 1
            if self._marker_count == len(NO_ESCAPE_MARKER):
                self._marker_count = 0
                self._noesc_length.clear()
                self.state = DecoderState.READING_NOESC_LENGTH
            return
        self.statistics.noise_bytes += self._marker_count + 1
        self._marker_count = 0

    def _classic_byte(self, value: int, frames: list[bytes]) -> None:
        if value == ESCAPE_BYTE:
            self.state = DecoderState.CLASSIC_ESCAPED
        elif value == START_BYTE:
            if self._classic:
                self.statistics.resynchronizations += 1
            self._classic.clear()
        elif value == STOP_BYTE:
            self._finish_classic(frames)
        else:
            self._append_classic(value)

    def _append_classic(self, value: int) -> None:
        self._classic.append(value)
        if len(self._classic) > self.max_packet_size + 1:
            self.statistics.oversized_packets += 1
            self.errors.append(FrameTooLargeError("classic MCP frame exceeds configured limit"))
            self.reset()

    def _finish_classic(self, frames: list[bytes]) -> None:
        if not self._classic:
            self.statistics.malformed_packets += 1
            self.errors.append(ProtocolError("classic MCP frame has no checksum"))
            self.reset()
            return
        payload = self._classic[:-1]
        expected = START_BYTE
        for value in payload:
            expected ^= value
        if self._classic[-1] == expected:
            frames.append(bytes(payload))
            self.statistics.classic_packets += 1
        else:
            self.statistics.crc_errors += 1
            self.errors.append(ChecksumError("classic MCP XOR checksum mismatch"))
        self.reset()

    def _length_byte(self, value: int) -> None:
        self._noesc_length.append(value)
        if len(self._noesc_length) != 4:
            return
        self._noesc_expected = int.from_bytes(self._noesc_length, "little")
        if not 0 < self._noesc_expected <= self.max_packet_size:
            if self._noesc_expected > self.max_packet_size:
                self.statistics.oversized_packets += 1
                error: ProtocolError = FrameTooLargeError(
                    f"no-escape length {self._noesc_expected} exceeds configured limit"
                )
            else:
                self.statistics.malformed_packets += 1
                error = ProtocolError("zero-length no-escape frame")
            self.errors.append(error)
            self.reset()
            return
        self._noesc_payload.clear()
        self._noesc_checksum_pending = True
        self.state = DecoderState.READING_NOESC_PAYLOAD

    def _noescape_byte(self, value: int, frames: list[bytes]) -> None:
        if self._noesc_checksum_pending:
            self._noesc_checksum_pending = False
            return
        self._noesc_payload.append(value)
        if len(self._noesc_payload) == self._noesc_expected:
            frames.append(bytes(self._noesc_payload))
            self.statistics.noescape_packets += 1
            self.reset()
