import argparse
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mxs import cli
from mxs.capabilities import DeviceCapabilities
from mxs.discovery import PortInfo
from mxs.models import CirFrame, FileIdentifier, SessionStatistics
from mxs.recording import WireRecorder

# pyright: reportPrivateUsage=false


def _system_info(code: object) -> str:
    return f"value-{int(code)}"  # type: ignore[arg-type]


def _ignore(_value: object) -> None:
    pass


def _timeout_read(**_kwargs: object) -> object:
    raise TimeoutError


def _subscribe(*_args: object) -> SimpleNamespace:
    return SimpleNamespace(read=_timeout_read)


class FakeDevice:
    def __init__(self, **_kwargs: object) -> None:
        self.module = SimpleNamespace(get_system_info=_system_info)
        self.profile = SimpleNamespace(
            load_profile=_ignore,
            set_sensor_mode=_ignore,
            get_profileid=lambda: 1,
            get_sensor_mode=lambda: 0x13,
        )
        self.xep = SimpleNamespace(
            x4driver_get_fps=lambda: 17.0,
            x4driver_get_iterations=lambda: 16,
            x4driver_get_frame_area=lambda: (0.0, 5.0),
        )
        self.filesystem = SimpleNamespace(find_all_files=lambda: [FileIdentifier(1, 2)])
        self.messages = SimpleNamespace(all=SimpleNamespace(subscribe=_subscribe))
        self.detected_baudrate = 115200

    def configure(self, _config: object) -> None:
        pass

    def start(self) -> None:
        pass

    def read_frame(self, timeout: float | None = None) -> CirFrame:
        return CirFrame(1, 1, 0, "rf", np.asarray([1], np.float32), (0, 1))

    def frames(self) -> Iterator[CirFrame]:
        yield self.read_frame()

    def probe_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(order_code="X4M200")

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        pass


class FakeSession:
    def __init__(
        self,
        *_args: object,
        raw_chunk_callback: Callable[[bytes], None] | None = None,
        **_kwargs: object,
    ) -> None:
        self.detected_baudrate = 115200
        self.router = SimpleNamespace(
            valid_packet_count=1,
            message_types={"SleepStatus"},
            content_ids={1},
            last_counter=2,
        )
        self.raw_chunk_callback = raw_chunk_callback

    def open(self) -> None:
        if self.raw_chunk_callback is not None:
            self.raw_chunk_callback(b"data")

    def statistics(self) -> SessionStatistics:
        return SessionStatistics()

    def close_passive(self) -> None:
        pass


def _no_sleep(_seconds: float) -> None:
    pass


def test_cli_parsing_discovery_replay_and_benchmark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli._baud("auto") == "auto"
    assert cli._baud("115200") == 115200
    with pytest.raises(argparse.ArgumentTypeError):
        cli._baud("9600")
    monkeypatch.setattr(
        cli,
        "list_serial_ports",
        lambda: [PortInfo("fake", "XeThru", "Novelda", "1", 1, 2, "a", None, "hw")],
    )
    assert cli.main(["ports"]) == 0
    assert "fake" in capsys.readouterr().out
    wire = tmp_path / "wire.mcpbin"
    with WireRecorder(wire, "fake", 115200) as recorder:
        recorder.write_chunk(b"abc")
    assert cli.main(["replay-wire", str(wire)]) == 0
    assert '"bytes": 3' in capsys.readouterr().out
    assert cli.main(["benchmark", str(wire), "--iterations", "1"]) == 0
    assert "bytes_per_second" in capsys.readouterr().out


def test_cli_info_capabilities_and_configured_actions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "X4M200", FakeDevice)
    for args in (
        ["info", "--port", "fake"],
        ["capabilities", "--port", "fake"],
        ["profile", "load", "1", "--port", "fake"],
        ["sensor-mode", "stop", "--port", "fake"],
        ["get", "xep.fps", "--port", "fake"],
        ["get", "xep.iterations", "--port", "fake"],
        ["get", "xep.frame-area", "--port", "fake"],
        ["get", "profile-id", "--port", "fake"],
        ["get", "sensor-mode", "--port", "fake"],
        ["files", "list", "--port", "fake"],
    ):
        assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "X4M200" in output
    assert "17.0" in output
    assert "0x00000001" in output


def test_cli_passive_capture_stream_and_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "X4M200", FakeDevice)
    monkeypatch.setattr(cli, "DeviceSession", FakeSession)
    monkeypatch.setattr(cli.time, "sleep", _no_sleep)
    assert cli.main(["sniff", "--port", "fake", "--seconds", "0", "--hex"]) == 0
    assert cli.main(["probe", "--port", "fake"]) == 0
    assert cli.main(["doctor", "--port", "fake"]) == 0
    target = tmp_path / "capture.npz"
    assert cli.main(["capture", "--port", "fake", "--frames", "1", "--output", str(target)]) == 0
    assert target.exists()
    assert cli.main(["stream", "--port", "fake", "--stats"]) == 0
    wire = tmp_path / "record.mcpbin"
    assert (
        cli.main(["record-wire", "--port", "fake", "--duration", "0", "--output", str(wire)]) == 0
    )
    assert wire.exists()
    messages = tmp_path / "messages"
    assert (
        cli.main(
            [
                "record-messages",
                "--port",
                "fake",
                "--duration",
                "0",
                "--output",
                str(messages),
            ]
        )
        == 0
    )
    assert cli.main(["replay-messages", str(messages)]) == 0
    assert "counter=1" in capsys.readouterr().out
