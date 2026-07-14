"""Serial port discovery."""

from dataclasses import dataclass

from serial.tools import list_ports

from .errors import AmbiguousDeviceError, DeviceNotFoundError


@dataclass(slots=True, frozen=True)
class PortInfo:
    device: str
    description: str
    manufacturer: str | None
    serial_number: str | None
    vid: int | None
    pid: int | None
    location: str | None
    interface: str | None
    hwid: str


def list_serial_ports() -> list[PortInfo]:
    return [
        PortInfo(
            port.device,
            port.description,
            port.manufacturer,
            port.serial_number,
            port.vid,
            port.pid,
            port.location,
            port.interface,
            port.hwid,
        )
        for port in list_ports.comports()
    ]


def discover_port() -> str:
    ports = list_serial_ports()
    candidates = [
        port
        for port in ports
        if any(
            token in f"{port.description} {port.manufacturer or ''}".lower()
            for token in ("xethru", "novelda", "x4m", "usbmodem")
        )
    ]
    if not candidates:
        raise DeviceNotFoundError("no supported XeThru serial device was found")
    if len(candidates) != 1:
        devices = ", ".join(port.device for port in candidates)
        raise AmbiguousDeviceError(f"multiple XeThru candidates found: {devices}")
    return candidates[0].device
