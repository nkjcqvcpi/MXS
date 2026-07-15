"""Short, non-destructive tests against the fixed X4M200 module."""

import asyncio
import threading
import time
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from mxs import X4M200, AsyncX4M200, CirFrame, X4Config
from mxs.constants import OutputControl, OutputFeature, ProfileId, SensorMode, SystemInfoCode
from mxs.errors import (
    InvalidDeviceStateError,
    UnsafeOperationDisabledError,
    UnsupportedFirmwareError,
)
from mxs.recording import WireRecorder, replay_wire, replay_wire_records


def _assert_ordered_frames(frames: list[CirFrame]) -> None:
    counters = [frame.frame_counter for frame in frames]
    assert all(((right - left) & 0xFFFFFFFF) > 0 for left, right in pairwise(counters))
    assert sum(frame.sequence_gap for frame in frames) == 0


@pytest.mark.hardware
def test_identity_protocol_and_capabilities(device_port: str) -> None:
    with X4M200(port=device_port, baudrate="auto") as device:
        assert device.detected_baudrate == 115200
        assert device.module.ping().ready
        required_codes = (
            SystemInfoCode.ITEM_NUMBER,
            SystemInfoCode.ORDER_CODE,
            SystemInfoCode.FIRMWARE_ID,
            SystemInfoCode.VERSION,
            SystemInfoCode.BUILD,
            SystemInfoCode.SERIAL_NUMBER,
            SystemInfoCode.VERSION_LIST,
        )
        values = {code: device.module.get_system_info(code).strip() for code in required_codes}
        for code in required_codes:
            assert values[code]
        assert values[SystemInfoCode.ORDER_CODE] == "X4M200"
        assert device.profile.get_sensor_mode() is SensorMode.STOP
        assert isinstance(device.profile.get_profileid(), int)
        capabilities = device.probe_capabilities()
        assert capabilities.order_code == "X4M200"
        assert capabilities.supports_extended_respiration is False
        assert capabilities.supports_periodic_noisemap_store is False
        assert not capabilities.probe_failures


@pytest.mark.hardware
@pytest.mark.stateful
def test_baudrate_round_trips(device_port: str) -> None:
    try:
        with X4M200(port=device_port, baudrate=115200) as device:
            assert device.module.ping().ready
            device.switch_to_high_baudrate()
            assert device.detected_baudrate == 921600
            assert device.module.ping().ready
        with X4M200(port=device_port, baudrate=921600) as device:
            assert device.module.ping().ready
            device.module.set_baudrate(115200)
            assert device.detected_baudrate == 115200
            assert device.module.ping().ready
        with X4M200(port=device_port, baudrate=115200) as device:
            assert device.module.ping().ready
    finally:
        with X4M200(port=device_port, baudrate="auto") as device:
            device.profile.set_sensor_mode(SensorMode.STOP)
            if device.detected_baudrate != 115200:
                device.module.set_baudrate(115200)


@pytest.mark.hardware
@pytest.mark.stateful
@pytest.mark.parametrize(("downconversion", "dtype"), [(False, np.float32), (True, np.complex64)])
def test_capture_100_frames(device_port: str, downconversion: bool, dtype: object) -> None:
    with X4M200(port=device_port, frame_queue_size=128) as device:
        device.configure(X4Config(downconversion=downconversion))
        try:
            device.start()
            stream = device.frames()
            frames = [next(stream)]
            frames.extend([device.read_frame(timeout=2.0) for _ in range(99)])
        finally:
            device.stop()
        assert all(frame.samples.dtype == dtype for frame in frames)
        assert len({frame.samples.shape for frame in frames}) == 1
        assert all(np.isfinite(frame.samples).all() for frame in frames)
        _assert_ordered_frames(frames)
        statistics = device.statistics()
        assert statistics.crc_errors == 0
        assert statistics.frame_counter_gaps == 0
        assert device.profile.get_sensor_mode() is SensorMode.STOP


@pytest.mark.hardware
@pytest.mark.stateful
@pytest.mark.asyncio
@pytest.mark.timeout(45)
async def test_async_capture_512_frames(device_port: str) -> None:
    device = AsyncX4M200(port=device_port, frame_queue_size=640)
    unopened = AsyncX4M200(port=device_port)
    with pytest.raises(RuntimeError, match="not open"):
        await unopened.read_frame(timeout=0.001)
    try:
        await device.__aenter__()
        assert await device.module.ping() is not None
        assert await device.profile.get_sensor_mode() is SensorMode.STOP
        await device.configure(X4Config(downconversion=True))
        await device.start()
        cancelled = asyncio.create_task(device.read_frame(timeout=2.0))
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        stream = device.frames()
        frames = [await anext(stream)]
        frames.extend([await device.read_frame(timeout=2.0) for _ in range(511)])
        await device.stop()
        statistics = await device.statistics()
        _assert_ordered_frames(frames)
        assert statistics.crc_errors == 0
        assert statistics.frame_counter_gaps == 0
        assert statistics.consumer_drops == 0
        assert statistics.queue_overflows == 0
    finally:
        await device.__aexit__(None, None, None)
    await asyncio.sleep(0)
    assert not any(thread.name.startswith("mxs-") for thread in threading.enumerate())


@pytest.mark.hardware
@pytest.mark.stateful
def test_supported_profile_messages_and_outputs(device_port: str) -> None:
    with X4M200(port=device_port) as device:
        device.profile.set_sensor_mode(SensorMode.STOP)
        device.profile.load_profile(ProfileId.RESPIRATION_2)
        sleep = device.messages.sleep.subscribe(32, "error")
        respiration = device.messages.respiration.subscribe(32, "error")
        baseband_iq = device.messages.baseband_iq.subscribe(32, "error")
        device.outputs.set_output_control(OutputFeature.SLEEP, OutputControl.ENABLE)
        device.outputs.set_output_control(OutputFeature.RESPIRATION, OutputControl.ENABLE)
        device.outputs.set_output_control(OutputFeature.BASEBAND_IQ, OutputControl.ENABLE)
        assert device.outputs.get_output_control(OutputFeature.SLEEP) & OutputControl.ENABLE
        assert device.outputs.get_output_control(OutputFeature.RESPIRATION) & OutputControl.ENABLE
        assert device.outputs.get_output_control(OutputFeature.BASEBAND_IQ) & OutputControl.ENABLE
        assert device.outputs.get_output_control(OutputFeature.BASEBAND_AMPLITUDE_PHASE) == 0
        try:
            device.profile.set_sensor_mode(SensorMode.RUN)
            assert sleep.read(timeout=8.0) is not None
            assert respiration.read(timeout=8.0) is not None
            assert baseband_iq.read(timeout=8.0) is not None
        finally:
            device.profile.set_sensor_mode(SensorMode.STOP)
        assert device.profile.get_sensor_mode() is SensorMode.STOP


@pytest.mark.hardware
@pytest.mark.stateful
@pytest.mark.parametrize(
    ("first", "second"),
    [
        (OutputFeature.BASEBAND_IQ, OutputFeature.BASEBAND_AMPLITUDE_PHASE),
        (OutputFeature.PULSE_DOPPLER_FLOAT, OutputFeature.PULSE_DOPPLER_BYTE),
        (OutputFeature.NOISEMAP_FLOAT, OutputFeature.NOISEMAP_BYTE),
    ],
)
def test_output_exclusivity_uses_live_state(
    device_port: str, first: OutputFeature, second: OutputFeature
) -> None:
    with X4M200(port=device_port) as device:
        device.profile.set_sensor_mode(SensorMode.STOP)
        for feature in (first, second):
            device.outputs.set_output_control(feature, OutputControl.DISABLE)
        device.outputs.set_output_control(first, OutputControl.ENABLE)
        assert device.outputs.get_output_control(first) & OutputControl.ENABLE
        with pytest.raises(InvalidDeviceStateError, match="mutually exclusive"):
            device.outputs.set_output_control(second, OutputControl.ENABLE)
        assert device.outputs.get_output_control(second) == 0
        device.outputs.set_output_control(first, OutputControl.DISABLE)
        device.outputs.set_output_control(second, OutputControl.ENABLE)
        assert device.outputs.get_output_control(second) & OutputControl.ENABLE


@pytest.mark.hardware
@pytest.mark.stateful
def test_five_second_wire_recording_and_replay(device_port: str, tmp_path: Path) -> None:
    path = tmp_path / "live.mcpbin"
    raw_chunks: list[bytes] = []
    with (
        WireRecorder(path, device_port, 115200) as recorder,
        X4M200(
            port=device_port,
            baudrate=115200,
            raw_chunk_callback=raw_chunks.append,
            wire_chunk_callback=recorder.write_chunk,
        ) as device,
    ):
        assert device.module.ping().ready
        time.sleep(5.0)
    records = list(replay_wire_records(path))
    assert any(record.direction == "rx" for record in records)
    assert any(record.direction == "tx" for record in records)
    timestamps = [record.timestamp_monotonic_ns for record in records]
    assert all(timestamp > 0 for timestamp in timestamps)
    assert timestamps == sorted(timestamps)
    replayed_rx = list(replay_wire(path))
    assert replayed_rx
    assert b"".join(replayed_rx) == b"".join(raw_chunks)
    assert path.read_bytes().endswith(b"\xff\x00\x00\x00\x00")


@pytest.mark.hardware
@pytest.mark.stateful
def test_five_reopen_cycles(device_port: str) -> None:
    for _ in range(5):
        with X4M200(port=device_port, baudrate=115200) as device:
            assert device.module.ping().ready
    assert not any(thread.name.startswith("mxs-") for thread in threading.enumerate())


@pytest.mark.hardware
def test_all_unsupported_apis_transmit_nothing(device_port: str) -> None:
    with X4M200(port=device_port) as device:
        calls: list[Callable[[], object]] = [
            lambda: device.outputs.set_output_control(
                OutputFeature.RESPIRATION_EXTENDED, OutputControl.ENABLE
            ),
            lambda: device.outputs.get_output_control(OutputFeature.RESPIRATION_EXTENDED),
            lambda: device.outputs.set_debug_output_control(
                OutputFeature.RESPIRATION_EXTENDED, OutputControl.ENABLE
            ),
            lambda: device.outputs.get_debug_output_control(OutputFeature.RESPIRATION_EXTENDED),
            lambda: device.noisemap.set_periodic_noisemap_store(1, 0),
            device.noisemap.get_periodic_noisemap_store,
            lambda: device.xep.set_normalization(1),
            device.xep.get_normalization,
            lambda: device.xep.set_phase_noise_correction(1),
            device.xep.get_phase_noise_correction,
            lambda: device.xep.set_decimation_factor(2),
            device.xep.get_decimation_factor,
            lambda: device.xep.set_number_format(1),
            device.xep.get_number_format,
            lambda: device.xep.set_legacy_output(1),
            device.xep.get_legacy_output,
            lambda: device.unsafe.registers.x4driver_write_to_i2c_register(0, b"\x00"),
            lambda: device.unsafe.registers.x4driver_read_from_i2c_register(1),
        ]
        for call in calls:
            transmitted = device.statistics().bytes_transmitted
            with pytest.raises(UnsupportedFirmwareError):
                call()
            assert device.statistics().bytes_transmitted == transmitted


@pytest.mark.hardware
@pytest.mark.stateful
@pytest.mark.unsafe
def test_unsafe_operations_stop_before_destructive_tx(
    device_port: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    gates = (
        "MXS_ENABLE_BOOTLOADER",
        "MXS_ENABLE_FACTORY_RESET",
        "MXS_ENABLE_MANUFACTURING_TESTS",
        "MXS_ENABLE_FRAME_INJECTION",
        "MXS_ENABLE_RAW_REGISTER_WRITES",
        "MXS_ENABLE_UNSAFE",
        "MXS_ENABLE_FILESYSTEM_FORMAT",
        "MXS_ENABLE_NOISEMAP_FLASH_WRITE",
    )
    for gate in gates:
        monkeypatch.delenv(gate, raising=False)
    with X4M200(port=device_port) as device:
        calls: list[Callable[[], object]] = [
            lambda: device.unsafe.start_bootloader(key=0),
            lambda: device.unsafe.reset_to_factory_preset(confirm=True),
            lambda: device.unsafe.system_run_test(0),
            lambda: device.unsafe.prepare_inject_frame(1, 1, 0),
            lambda: device.unsafe.inject_frame(0, 1, np.zeros(1, dtype=np.float32)),
            lambda: device.unsafe.registers.write_spi(0, b"\x00"),
            lambda: device.unsafe.filesystem_admin.create_file(0, 0, 0),
            lambda: device.unsafe.filesystem_admin.format_filesystem(key=1),
            device.noisemap.store_noisemap,
            device.noisemap.delete_noisemap,
        ]
        for call in calls:
            transmitted = device.statistics().bytes_transmitted
            with pytest.raises(UnsafeOperationDisabledError):
                call()
            assert device.statistics().bytes_transmitted == transmitted

        device.configure(X4Config(fps=10.0))
        device.start()
        monkeypatch.setenv("MXS_ENABLE_RAW_REGISTER_WRITES", "1")
        transmitted = device.statistics().bytes_transmitted
        try:
            with pytest.raises(InvalidDeviceStateError):
                device.unsafe.registers.write_spi(0, b"\x00")
            assert device.statistics().bytes_transmitted == transmitted
        finally:
            monkeypatch.delenv("MXS_ENABLE_RAW_REGISTER_WRITES", raising=False)
            device.stop()
