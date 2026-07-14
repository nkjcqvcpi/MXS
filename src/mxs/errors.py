"""Typed public exceptions."""

from dataclasses import dataclass


class MxsError(Exception):
    """Base exception for the package."""


# 0.1 name retained for source compatibility.
class SerialOpenError(MxsError):
    pass


class DeviceNotFoundError(MxsError):
    pass


class DeviceDisconnectedError(MxsError):
    pass


class BaudDetectionError(MxsError):
    pass


class ProtocolError(MxsError):
    pass


class ChecksumError(ProtocolError):
    pass


class FrameTooLargeError(ProtocolError):
    pass


class MalformedMessageError(ProtocolError):
    pass


class CommandTimeoutError(MxsError):
    pass


@dataclass(slots=True)
class CommandRejectedError(MxsError):
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


class InvalidDeviceStateError(MxsError):
    pass


class InvalidIqFrameError(MxsError):
    pass


class FrameBackpressureError(MxsError):
    pass


class WorkerTerminatedError(MxsError):
    pass


class UnsafeOperationDisabledError(MxsError):
    pass


class UnsupportedFirmwareError(MxsError):
    pass


class SessionDesynchronizedError(MxsError):
    pass


class AmbiguousDeviceError(MxsError):
    pass


class MessageQueueOverflowError(MxsError):
    pass


class RecordingBackpressureError(MxsError):
    pass


class ReplyMismatchError(ProtocolError):
    pass
