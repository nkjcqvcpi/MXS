"""CLI grammar and API-parity regressions after real-device preflight."""

import argparse

import pytest

from mxs import cli
from mxs.discovery import PortInfo, discover_port
from mxs.errors import AmbiguousDeviceError, DeviceNotFoundError
from scripts.check_api_parity import audit


def test_cli_parser_accepts_every_command_shape() -> None:
    parser = cli._base_parser()  # pyright: ignore[reportPrivateUsage]
    argv = (
        ["ports"],
        ["sniff", "--seconds", "0", "--hex"],
        ["probe"],
        ["info"],
        ["capabilities"],
        ["doctor"],
        ["replay-wire", "capture.mcpbin"],
        ["benchmark", "capture.mcpbin", "--iterations", "1"],
        ["profile", "load", "1"],
        ["sensor-mode", "stop"],
        ["get", "xep.fps"],
        ["set", "xep.iterations", "8"],
        ["outputs", "get", "0xc"],
        ["outputs", "set", "0xc", "1"],
        ["messages", "sleep", "--count", "1"],
        ["noisemap", "get-control"],
        ["gpio", "get-value", "1"],
        ["unsafe", "factory-reset", "--confirm"],
        ["files", "list"],
        ["capture", "--frames", "1", "--output", "capture.npz"],
        ["stream", "--stats"],
        ["record-wire", "--duration", "1", "--output", "capture.mcpbin"],
        ["record-messages", "--duration", "1", "--output", "messages"],
        ["replay-messages", "messages"],
    )
    assert [parser.parse_args(args).command for args in argv]
    assert cli._baud("auto") == "auto"  # pyright: ignore[reportPrivateUsage]
    assert cli._baud("115200") == 115200  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(argparse.ArgumentTypeError):
        cli._baud("9600")  # pyright: ignore[reportPrivateUsage]


def test_api_parity_registry_is_complete() -> None:
    assert audit() == []


def test_port_discovery_selection_without_serial_emulation(monkeypatch: pytest.MonkeyPatch) -> None:
    import mxs.discovery

    candidate = PortInfo("/dev/tty.usbmodem2101", "X4M200", None, None, None, None, None, None, "")
    unrelated = PortInfo("/dev/tty.other", "UART", None, None, None, None, None, None, "")
    monkeypatch.setattr(mxs.discovery, "list_serial_ports", lambda: [unrelated, candidate])
    assert discover_port() == candidate.device

    monkeypatch.setattr(mxs.discovery, "list_serial_ports", lambda: [unrelated])
    with pytest.raises(DeviceNotFoundError):
        discover_port()

    second = PortInfo("/dev/tty.usbmodem2201", "Novelda", None, None, None, None, None, None, "")
    monkeypatch.setattr(mxs.discovery, "list_serial_ports", lambda: [candidate, second])
    with pytest.raises(AmbiguousDeviceError, match=r"usbmodem2101.*usbmodem2201"):
        discover_port()
