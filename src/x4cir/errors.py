"""Typed public exceptions."""

from dataclasses import dataclass


class X4CirError(Exception):
    """Base exception for the package."""


class SerialOpenError(X4CirError):
    pass


class DeviceNotFoundError(X4CirError):
    pass


class DeviceDisconnectedError(X4CirError):
    pass


class BaudDetectionError(X4CirError):
    pass


class ProtocolError(X4CirError):
    pass


class ChecksumError(ProtocolError):
    pass


class FrameTooLargeError(ProtocolError):
    pass


class MalformedMessageError(ProtocolError):
    pass


class CommandTimeoutError(X4CirError):
    pass


@dataclass(slots=True)
class CommandRejectedError(X4CirError):
    command_name: str
    packet: bytes
    firmware_error_code: int
    elapsed_seconds: float
    recent_control_headers: tuple[bytes, ...]
    device_state: str

    def __str__(self) -> str:
        return (
            f"{self.command_name} rejected with firmware error "
            f"0x{self.firmware_error_code:08x} after {self.elapsed_seconds:.3f}s "
            f"in state {self.device_state}"
        )


class InvalidDeviceStateError(X4CirError):
    pass


class InvalidIqFrameError(X4CirError):
    pass


class FrameBackpressureError(X4CirError):
    pass


class WorkerTerminatedError(X4CirError):
    pass
