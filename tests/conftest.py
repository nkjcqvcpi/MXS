"""Mandatory real-X4M200 pytest preflight and restoration."""

import os
import stat
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, cast

import pytest

from mxs import X4M200
from mxs.constants import SensorMode

DEVICE_PORT = "/dev/tty.usbmodem2101"


class _FixtureItem(Protocol):
    nodeid: str
    fixturenames: list[str]


def _require_character_device(port: str) -> None:
    try:
        mode = Path(port).stat().st_mode
    except OSError as error:
        raise pytest.UsageError(f"X4M200 is unavailable at {port}: {error}") from error
    if not stat.S_ISCHR(mode):
        raise pytest.UsageError(f"X4M200 path is not a character device: {port}")


def _require_free_port(port: str) -> None:
    result = subprocess.run(["lsof", port], capture_output=True, check=False, text=True)
    if result.returncode not in (0, 1):
        raise pytest.UsageError(f"lsof failed for {port}: {result.stderr.strip()}")
    if result.stdout.strip():
        raise pytest.UsageError(f"X4M200 serial port is busy:\n{result.stdout.rstrip()}")


def _restore_stop_and_baud(port: str) -> None:
    with X4M200(port=port, baudrate="auto") as device:
        pong = device.module.ping()
        if not pong.ready:
            raise RuntimeError("X4M200 firmware did not report ready")
        if device.module.get_system_info(1).strip() != "X4M200":
            raise RuntimeError("connected serial module is not an X4M200")
        device.profile.set_sensor_mode(SensorMode.STOP)
        if device.detected_baudrate != 115200:
            device.module.set_baudrate(115200)
        if device.profile.get_sensor_mode() is not SensorMode.STOP:
            raise RuntimeError("X4M200 did not enter STOP mode")


@pytest.fixture(scope="session")
def device_port() -> Iterator[str]:
    configured = os.getenv("MXS_TEST_PORT", DEVICE_PORT)
    if configured != DEVICE_PORT:
        raise pytest.UsageError(f"MXS_TEST_PORT must be the fixed device path {DEVICE_PORT}")
    _require_character_device(DEVICE_PORT)
    _require_free_port(DEVICE_PORT)
    try:
        _restore_stop_and_baud(DEVICE_PORT)
    except BaseException as error:
        raise pytest.UsageError(f"X4M200 preflight failed: {error}") from error
    yield DEVICE_PORT
    _require_character_device(DEVICE_PORT)
    _require_free_port(DEVICE_PORT)
    _restore_stop_and_baud(DEVICE_PORT)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    fixture_items = (cast("_FixtureItem", item) for item in items)
    missing = [item.nodeid for item in fixture_items if "device_port" not in item.fixturenames]
    if missing:
        joined = "\n".join(missing)
        raise pytest.UsageError(f"every test must require the real-device fixture:\n{joined}")
