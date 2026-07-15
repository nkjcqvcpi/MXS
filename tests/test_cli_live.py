"""Short CLI execution paths against the mandatory real device."""

from pathlib import Path

import pytest

from mxs import cli
from mxs.constants import ProfileId


@pytest.mark.hardware
@pytest.mark.stateful
def test_safe_cli_execution_paths(
    device_port: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    common = ["--port", device_port, "--baud", "115200"]
    assert cli.main(["ports"]) == 0
    assert cli.main(["sniff", *common, "--seconds", "0", "--hex"]) == 0
    assert cli.main(["probe", *common]) == 0
    assert cli.main(["doctor", *common]) == 0
    assert cli.main(["info", *common]) == 0
    assert cli.main(["capabilities", *common]) == 0
    assert cli.main(["profile", "load", hex(ProfileId.RESPIRATION_2), *common]) == 0
    for setting in ("xep.fps", "xep.iterations", "xep.frame-area", "profile-id", "sensor-mode"):
        assert cli.main(["get", setting, *common]) == 0
    assert cli.main(["outputs", "get", "0xc", *common]) == 0
    assert cli.main(["files", "list", *common]) == 0
    assert cli.main(["noisemap", "get-control", *common]) == 1
    assert cli.main(["gpio", "get-control", "1", *common]) == 0
    assert cli.main(["gpio", "get-value", "1", *common]) == 0
    assert cli.main(["sensor-mode", "stop", *common]) == 0
    assert cli.main(["set", "profile-id", hex(ProfileId.RESPIRATION_2), *common]) == 0
    assert cli.main(["set", "xep.iterations", "16", *common]) == 0
    assert cli.main(["outputs", "set", "0xc", "1", *common]) == 0
    assert cli.main(["unsafe", "store-noisemap", *common]) == 1
    assert cli.main(["unsafe", "delete-noisemap", *common]) == 1
    assert cli.main(["unsafe", "format-filesystem", *common]) == 1
    assert cli.main(["unsafe", "factory-reset", *common]) == 1

    capture = tmp_path / "capture.npz"
    assert cli.main(["capture", *common, "--frames", "1", "--output", str(capture)]) == 0
    assert capture.exists()
    wire = tmp_path / "wire.mcpbin"
    assert cli.main(["record-wire", *common, "--duration", "0", "--output", str(wire)]) == 0
    assert cli.main(["replay-wire", str(wire)]) == 0
    assert cli.main(["benchmark", str(wire), "--iterations", "1"]) == 0
    messages = tmp_path / "messages"
    assert cli.main(["record-messages", *common, "--duration", "0", "--output", str(messages)]) == 0
    assert cli.main(["replay-messages", str(messages)]) == 0
    assert capsys.readouterr().out
