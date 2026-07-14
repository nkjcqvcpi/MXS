import threading
import time
from collections import deque

from mxs.commands import build_ping, build_set_fps
from mxs.framing import encode_classic_frame

SLEEP_FRAME = bytes.fromhex(
    "7d506ca1752350050000040000000000000000000000000000000000000000000000e77e"
)


class FakeSerial:
    def __init__(
        self,
        baudrate: int,
        *,
        partial_read: int = 17,
        partial_write: int = 4,
        initial_stream: bool = True,
        data_before_ack: bool = True,
        emit_start_frame: bool = True,
    ) -> None:
        self.baudrate = baudrate
        self.partial_read = partial_read
        self.partial_write = partial_write
        self.data_before_ack = data_before_ack
        self.emit_start_frame = emit_start_frame
        self.closed = False
        self.disconnected = False
        self.reject_next = False
        self.suppress_next_response = False
        self.delay_ack = 0.0
        self.writes: list[bytes] = []
        self._incoming: deque[int] = deque(SLEEP_FRAME if initial_stream else b"")
        self._outgoing = bytearray()
        self._condition = threading.Condition()

    def readinto(self, buffer: bytearray) -> int:
        if self.disconnected:
            raise OSError("fake disconnect")
        deadline = time.monotonic() + 0.01
        with self._condition:
            while not self._incoming and not self.closed and time.monotonic() < deadline:
                self._condition.wait(0.002)
            count = min(len(buffer), self.partial_read, len(self._incoming))
            for index in range(count):
                buffer[index] = self._incoming.popleft()
            return count

    def write(self, data: bytes | memoryview) -> int:
        if self.disconnected:
            raise OSError("fake disconnect")
        chunk = bytes(data[: self.partial_write])
        self._outgoing.extend(chunk)
        if chunk and self._outgoing[-1] == 0x7E:
            packet = bytes(self._outgoing)
            self._outgoing.clear()
            self.writes.append(packet)
            self._respond(packet)
        return len(chunk)

    def _respond(self, packet: bytes) -> None:
        if self.suppress_next_response:
            self.suppress_next_response = False
            return
        if self.delay_ack:
            time.sleep(self.delay_ack)
        if packet == build_ping():
            response = encode_classic_frame(b"\x01\xea\xae\xee\xaa")
        elif self.reject_next:
            response = encode_classic_frame(b"\x20\x21\x00\x00\x00")
            self.reject_next = False
        else:
            response = encode_classic_frame(b"\x10")
        frame = encode_classic_frame(
            b"\xa0\x12\x00\x00\x00\x00\x2a\x00\x00\x00\x04\x00\x00\x00"
            + b"\x00\x00\x80?\x00\x00\x00@\x00\x00@@\x00\x00\x80@"
        )
        if packet == build_set_fps(17.0) and not self.emit_start_frame:
            self.inject(response)
        elif packet == build_set_fps(17.0) and self.data_before_ack:
            self.inject(frame + response)
        elif packet == build_set_fps(17.0):
            self.inject(response + frame)
        else:
            self.inject(response)

    def inject(self, data: bytes) -> None:
        with self._condition:
            self._incoming.extend(data)
            self._condition.notify_all()

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True
        with self._condition:
            self._condition.notify_all()


class FakeSerialFactory:
    def __init__(self, **options: object) -> None:
        self.options = options
        self.instances: list[FakeSerial] = []

    def __call__(self, _port: str, baudrate: int) -> FakeSerial:
        serial = FakeSerial(baudrate, **self.options)  # type: ignore[arg-type]
        self.instances.append(serial)
        return serial
