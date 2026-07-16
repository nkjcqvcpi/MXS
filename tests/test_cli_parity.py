"""CLI grammar and API-parity regressions after real-device preflight."""

import argparse
import stat
from pathlib import Path

import pytest

from mxs import X4M200, cli
from mxs.discovery import discover_port
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


def test_live_port_discovery(device_port: str) -> None:
    discovered = discover_port()
    assert discovered in {device_port, device_port.replace("/tty.", "/cu.")}
    assert stat.S_ISCHR(Path(discovered).stat().st_mode)


def test_not_executed_parity_symbols_are_explicit(device_port: str) -> None:
    device = X4M200(port=device_port)
    symbols = (
        device.module.set_debug_level,
        device.module.reset,
        device.module.module_reset,
        device.profile.set_detection_zone,
        device.profile.set_led_control,
        device.outputs.set_debug_output_control,
        device.outputs.get_debug_output_control,
        device.noisemap.load_noisemap,
        device.parameters.set_parameter_file,
        device.filesystem.get_file,
        device.xep.x4driver_init,
        device.xep.x4driver_set_enable,
        device.messages,
    )
    assert all(symbol is not None for symbol in symbols)
