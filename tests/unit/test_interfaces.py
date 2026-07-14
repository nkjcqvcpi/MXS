from typing import cast

import numpy as np
import pytest

from mxs.errors import UnsafeOperationDisabledError, UnsupportedFirmwareError
from mxs.expectations import ResponseExpectation
from mxs.interfaces import (
    FilesystemInterface,
    GpioInterface,
    ModuleInterface,
    NoisemapInterface,
    OutputsInterface,
    ParametersInterface,
    ProfileInterface,
    UnsafeInterface,
    XepInterface,
)
from mxs.models import Ack, ByteReply, FloatReply, IntReply, Pong, StringReply
from mxs.session import DeviceSession


class StubSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self.high_baud = False

    def execute(self, name: str, packet: bytes, expectation: ResponseExpectation):
        self.calls.append((name, packet))
        if expectation.response_class is Ack:
            return Ack()
        if expectation.response_class is Pong:
            return Pong(0xAAEEAEEA, True)
        reply_class = expectation.reply_class
        content_id = expectation.content_id or 0
        info = expectation.info or 0
        count = expectation.element_count or (2 if content_id == 0x14 else 1)
        if reply_class is StringReply:
            return StringReply(content_id, info, 6, 1, "X4M200")
        if reply_class is ByteReply:
            return ByteReply(content_id, info, count, 1, bytes(range(1, count + 1)))
        if reply_class is FloatReply:
            if content_id == 0x96A10A1D:
                count = 3
            elif content_id == 0x96A10A1C:
                count = 2
            return FloatReply(content_id, info, count, 4, np.arange(1, count + 1, dtype=np.float32))
        if reply_class is IntReply:
            if name == "find_all_files":
                return IntReply(content_id, info, 4, 4, np.asarray([1, 2, 10, 20], np.int32))
            if name == "search_for_file_by_type":
                return IntReply(content_id, info, 2, 4, np.asarray([2, 3], np.int32))
            return IntReply(content_id, info, count, 4, np.arange(1, count + 1, dtype=np.int32))
        raise AssertionError(reply_class)

    def switch_to_high_baudrate(self) -> None:
        self.high_baud = True


@pytest.fixture
def session() -> DeviceSession:
    return cast(DeviceSession, StubSession())


def test_module_profile_and_output_interfaces(session: DeviceSession) -> None:
    module = ModuleInterface(session)
    module.set_debug_level(2)
    module.set_baudrate(921600)
    assert module.ping().ready
    assert module.get_system_info(2) == "X4M200"
    module.module_reset()
    profile = ProfileInterface(session)
    profile.load_profile(1)
    profile.set_sensor_mode(0x13)
    assert int(profile.get_sensor_mode()) == 1
    assert profile.get_profileid() == 1
    profile.set_sensitivity(5)
    assert profile.get_sensitivity() == 1
    profile.set_tx_center_frequency(3)
    assert profile.get_tx_center_frequency() == 1
    profile.set_detection_zone(0.4, 2.0)
    assert profile.get_detection_zone().end == 2
    assert profile.get_detection_zone_limits().step == 3
    profile.set_led_control(1, 50)
    assert profile.get_led_control() == 1
    with pytest.raises(ValueError):
        profile.set_sensitivity(10)
    outputs = OutputsInterface(session)
    outputs.set_output_control(0x0C, 1)
    with pytest.raises(ValueError):
        outputs.set_output_control(0x0D, 1)
    assert outputs.get_output_control(0x0C) == 1
    outputs.set_debug_output_control(3, 1)
    assert outputs.get_debug_output_control(3) == 1


def test_xep_gpio_noisemap_and_parameters(session: DeviceSession) -> None:
    xep = XepInterface(session)
    xep.x4driver_init()
    xep.x4driver_set_fps(10)
    xep.x4driver_set_iterations(8)
    xep.x4driver_set_pulses_per_step(100)
    xep.x4driver_set_dac_min(900)
    xep.x4driver_set_dac_max(1100)
    xep.x4driver_set_tx_power(2)
    xep.x4driver_set_downconversion(True)
    xep.x4driver_set_frame_area(0, 2)
    xep.x4driver_set_frame_area_offset(0.1)
    xep.x4driver_set_tx_center_frequency(3)
    xep.x4driver_set_prf_div(16)
    xep.x4driver_set_enable(True)
    assert xep.x4driver_get_fps() == 1
    assert xep.x4driver_get_iterations() == 1
    assert xep.x4driver_get_pulses_per_step() == 1
    assert xep.x4driver_get_dac_min() == 1
    assert xep.x4driver_get_dac_max() == 1
    assert xep.x4driver_get_tx_power() == 1
    assert xep.x4driver_get_downconversion()
    assert xep.x4driver_get_frame_bin_count() == 1
    assert xep.x4driver_get_frame_area().end == 2
    assert xep.x4driver_get_frame_area_offset() == 1
    assert xep.x4driver_get_tx_center_frequency() == 1
    assert xep.x4driver_get_prf_div() == 1
    gpio = GpioInterface(session)
    gpio.set_iopin_control(1, 1, 0)
    assert gpio.get_iopin_control(1) == (1, 2)
    gpio.set_iopin_value(1, 1)
    assert gpio.get_iopin_value(1) == 1
    noisemap = NoisemapInterface(session)
    noisemap.load_noisemap()
    noisemap.store_noisemap()
    noisemap.set_noisemap_control(3)
    assert noisemap.get_noisemap_control() == 1
    with pytest.raises(UnsupportedFirmwareError):
        noisemap.get_periodic_noisemap_store()
    parameters = ParametersInterface(session)
    assert parameters.get_parameter_file("a.txt") == b"\x01"
    parameters.set_parameter_file("a.txt", "data")


def test_filesystem_and_unsafe_gates(
    session: DeviceSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    filesystem = FilesystemInterface(session)
    assert filesystem.search_for_file_by_type(5)[0].file_type == 5
    assert filesystem.find_all_files()[0].identifier == 10
    assert filesystem.get_file_length(1, 2) == 1
    assert filesystem.get_file_data(1, 2, 0, 1) == b"\x01"
    assert filesystem.get_file(1, 2).metadata.length == 1
    unsafe = UnsafeInterface(session)
    with pytest.raises(UnsafeOperationDisabledError):
        unsafe.start_bootloader(key=1)
    monkeypatch.setenv("MXS_ENABLE_BOOTLOADER", "1")
    unsafe.start_bootloader(key=1)
    monkeypatch.setenv("MXS_ENABLE_FACTORY_RESET", "1")
    with pytest.raises(ValueError):
        unsafe.reset_to_factory_preset(confirm=False)
    unsafe.reset_to_factory_preset(confirm=True)
    assert unsafe.registers.read_spi(1) == b"\x01"
    monkeypatch.setenv("MXS_ENABLE_RAW_REGISTER_WRITES", "1")
    unsafe.registers.write_spi(1, b"\x02")
    unsafe.registers.x4driver_set_spi_register(1, 2)
    unsafe.registers.x4driver_set_pif_register(1, 2)
    unsafe.registers.x4driver_set_xif_register(1, 2)
    unsafe.x4driver_write_to_spi_register(1, b"\x02")
    assert unsafe.x4driver_read_from_spi_register(1) == b"\x01"
    assert unsafe.registers.x4driver_get_spi_register(1) == 1
    assert unsafe.registers.x4driver_get_pif_register(1) == 1
    assert unsafe.registers.x4driver_get_xif_register(1) == 1
    with pytest.raises(UnsupportedFirmwareError):
        unsafe.registers.x4driver_read_from_i2c_register(1)
    monkeypatch.setenv("MXS_ENABLE_FILESYSTEM_FORMAT", "1")
    unsafe.filesystem_admin.format_filesystem(key=7)
    monkeypatch.setenv("MXS_ENABLE_UNSAFE", "1")
    unsafe.filesystem_admin.create_file(1, 2, 4)
    unsafe.filesystem_admin.open_file(1, 2)
    unsafe.filesystem_admin.set_file_data(1, 2, 0, b"data")
    unsafe.filesystem_admin.close_file(1, 2, commit=True)
    unsafe.filesystem_admin.set_file(1, 2, b"data")
    unsafe.filesystem_admin.delete_file(1, 2)
    monkeypatch.setenv("MXS_ENABLE_FRAME_INJECTION", "1")
    unsafe.prepare_inject_frame(1, 2, 0)
    unsafe.inject_frame(1, 2, np.zeros(4, np.float32))
