"""Serial port discovery."""

from dataclasses import dataclass

from serial.tools import list_ports


@dataclass(slots=True, frozen=True)
class PortInfo:
    device: str
    description: str
    manufacturer: str | None
    serial_number: str | None


def list_serial_ports() -> list[PortInfo]:
    return [
        PortInfo(port.device, port.description, port.manufacturer, port.serial_number)
        for port in list_ports.comports()
    ]
