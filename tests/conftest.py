"""Mandatory real-X4M200 preflight and per-test state restoration."""

import os
import stat
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import pytest

from mxs import X4M200
from mxs.constants import OutputControl, OutputFeature, SensorMode, SystemInfoCode

DEVICE_PORT = "/dev/tty.usbmodem2101"
SUPPORTED_OUTPUTS = tuple(
    feature for feature in OutputFeature if feature is not OutputFeature.RESPIRATION_EXTENDED
)


class _FixtureItem(Protocol):
    nodeid: str
    fixturenames: list[str]


class _MarkerNode(Protocol):
    def get_closest_marker(self, name: str) -> object | None: ...


class _FixtureRequest(Protocol):
    node: _MarkerNode


@dataclass(frozen=True, slots=True)
class DeviceBaseline:
    baudrate: int
    sensor_mode: SensorMode
    profile_id: int
    outputs: dict[OutputFeature, int]


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


def _assert_no_mxs_threads() -> None:
    names: list[str] = []
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        names = [thread.name for thread in threading.enumerate() if thread.name.startswith("mxs-")]
        if not names:
            return
        time.sleep(0.01)
    raise RuntimeError(f"MXS workers remain alive: {names}")


def _identify(device: X4M200) -> None:
    if not device.module.ping().ready:
        raise RuntimeError("X4M200 firmware did not report ready")
    order = device.module.get_system_info(SystemInfoCode.ORDER_CODE).strip()
    if order != "X4M200":
        raise RuntimeError(f"connected serial module is {order!r}, not X4M200")


def _capture_baseline(port: str) -> DeviceBaseline:
    with X4M200(port=port, baudrate="auto") as device:
        _identify(device)
        baudrate = device.detected_baudrate
        if baudrate is None:
            raise RuntimeError("automatic baud detection produced no result")
        sensor_mode = device.profile.get_sensor_mode()
        profile_id = device.profile.get_profileid()
        outputs = {
            feature: device.outputs.get_output_control(feature) for feature in SUPPORTED_OUTPUTS
        }
        device.profile.set_sensor_mode(SensorMode.STOP)
        if baudrate != 115200:
            device.module.set_baudrate(115200)
    _assert_no_mxs_threads()
    return DeviceBaseline(baudrate, sensor_mode, profile_id, outputs)


def _restore_device(port: str, baseline: DeviceBaseline) -> None:
    _require_character_device(port)
    _require_free_port(port)
    with X4M200(port=port, baudrate="auto") as device:
        _identify(device)
        device.profile.set_sensor_mode(SensorMode.STOP)
        for feature in SUPPORTED_OUTPUTS:
            if device.outputs.get_output_control(feature):
                device.outputs.set_output_control(feature, OutputControl.DISABLE)
        device.profile.restore_profile(baseline.profile_id)
        device.profile.set_sensor_mode(SensorMode.STOP)
        for feature in SUPPORTED_OUTPUTS:
            if device.outputs.get_output_control(feature):
                device.outputs.set_output_control(feature, OutputControl.DISABLE)
        for feature, control in baseline.outputs.items():
            if control:
                device.outputs.set_output_control(feature, control)
        if device.detected_baudrate != 115200:
            device.module.set_baudrate(115200)
        if device.profile.get_sensor_mode() is not SensorMode.STOP:
            raise RuntimeError("X4M200 restoration did not end in STOP mode")
        if device.profile.get_profileid() != baseline.profile_id:
            raise RuntimeError("X4M200 restoration did not restore the baseline profile")
        actual_outputs = {
            feature: device.outputs.get_output_control(feature) for feature in SUPPORTED_OUTPUTS
        }
        if actual_outputs != baseline.outputs:
            raise RuntimeError("X4M200 restoration did not restore baseline outputs")
        if device.detected_baudrate != 115200:
            raise RuntimeError("X4M200 restoration did not end at 115200 baud")
        if not device.module.ping().ready:
            raise RuntimeError("X4M200 restoration PING failed")
    _assert_no_mxs_threads()


@pytest.fixture(scope="session")
def device_baseline() -> Iterator[DeviceBaseline]:
    configured = os.getenv("MXS_TEST_PORT", DEVICE_PORT)
    if configured != DEVICE_PORT:
        raise pytest.UsageError(f"MXS_TEST_PORT must be the fixed device path {DEVICE_PORT}")
    _require_character_device(DEVICE_PORT)
    _require_free_port(DEVICE_PORT)
    try:
        baseline = _capture_baseline(DEVICE_PORT)
    except BaseException as error:
        raise pytest.UsageError(f"X4M200 preflight failed: {error}") from error
    try:
        yield baseline
    finally:
        _restore_device(DEVICE_PORT, baseline)


@pytest.fixture(scope="session")
def device_port(device_baseline: DeviceBaseline) -> str:
    del device_baseline
    return DEVICE_PORT


@pytest.fixture(autouse=True)
def restore_device_after_test(
    request: pytest.FixtureRequest, device_port: str, device_baseline: DeviceBaseline
) -> Iterator[None]:
    try:
        yield
    finally:
        node = cast("_FixtureRequest", request).node
        if node.get_closest_marker("stateful") is not None:
            _restore_device(device_port, device_baseline)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    fixture_items = (cast("_FixtureItem", item) for item in items)
    missing = [item.nodeid for item in fixture_items if "device_port" not in item.fixturenames]
    if missing:
        joined = "\n".join(missing)
        raise pytest.UsageError(f"every test must require the real-device fixture:\n{joined}")
