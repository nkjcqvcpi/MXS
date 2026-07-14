from types import SimpleNamespace

import pytest

from mxs import discovery
from mxs.errors import AmbiguousDeviceError, DeviceNotFoundError


def port(device: str, description: str = "XeThru X4M200") -> SimpleNamespace:
    return SimpleNamespace(
        device=device,
        description=description,
        manufacturer="Novelda",
        serial_number="1",
        vid=1,
        pid=2,
        location="a",
        interface=None,
        hwid="hw",
    )


def no_ports() -> list[SimpleNamespace]:
    return []


def test_port_discovery_unique_none_and_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery.list_ports, "comports", lambda: [port("one")])
    assert discovery.list_serial_ports()[0].hwid == "hw"
    assert discovery.discover_port() == "one"
    monkeypatch.setattr(discovery.list_ports, "comports", no_ports)
    with pytest.raises(DeviceNotFoundError):
        discovery.discover_port()
    monkeypatch.setattr(discovery.list_ports, "comports", lambda: [port("one"), port("two")])
    with pytest.raises(AmbiguousDeviceError):
        discovery.discover_port()
