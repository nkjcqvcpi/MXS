"""Broad safe API validation against the real module."""

import pytest

from mxs import X4M200, X4Config
from mxs.constants import OutputFeature, ProfileId, SensorMode, SystemInfoCode
from mxs.errors import CommandRejectedError, CommandTimeoutError, ProtocolError


@pytest.mark.hardware
@pytest.mark.stateful
def test_safe_profile_xep_gpio_noisemap_and_filesystem_surfaces(device_port: str) -> None:
    with X4M200(port=device_port) as device:
        capabilities = device.probe_capabilities()
        assert capabilities.order_code == "X4M200"
        assert device.get_system_info(SystemInfoCode.ORDER_CODE) == "X4M200"
        device.profile.set_sensor_mode(SensorMode.STOP)
        device.profile.load_profile(ProfileId.RESPIRATION_2)

        sensitivity = device.profile.get_sensitivity()
        center_frequency = device.profile.get_tx_center_frequency()
        detection_zone = device.profile.get_detection_zone()
        limits = device.profile.get_detection_zone_limits()
        assert isinstance(device.profile.get_led_control(), int)
        assert 0 <= sensitivity <= 9
        assert center_frequency in (3, 4)
        assert limits.minimum - limits.step <= detection_zone.start < detection_zone.end
        assert detection_zone.end <= limits.maximum + limits.step
        device.profile.set_sensitivity(sensitivity)
        device.profile.set_tx_center_frequency(center_frequency)

        setup, feature = device.gpio.get_iopin_control(1)
        value = device.gpio.get_iopin_value(1)
        device.gpio.set_iopin_control(1, setup, feature)
        device.gpio.set_iopin_value(1, value)

        noisemap_control = device.noisemap.get_noisemap_control()
        device.noisemap.set_noisemap_control(noisemap_control)

        files = device.filesystem.find_all_files()
        if files:
            first = files[0]
            length = device.filesystem.get_file_length(first.file_type, first.identifier)
            assert length >= 0

        for feature_id in OutputFeature:
            if feature_id is not OutputFeature.RESPIRATION_EXTENDED:
                assert isinstance(device.outputs.get_output_control(feature_id), int)

        device.configure(X4Config())
        assert device.xep.x4driver_get_iterations() == 16
        assert device.xep.x4driver_get_pulses_per_step() == 300
        assert device.xep.x4driver_get_dac_min() == 949
        assert device.xep.x4driver_get_dac_max() == 1100
        assert device.xep.x4driver_get_tx_power() == 2
        assert not device.xep.x4driver_get_downconversion()
        assert device.xep.x4driver_get_frame_bin_count() > 0
        assert device.xep.x4driver_get_frame_area().start < device.xep.x4driver_get_frame_area().end
        assert device.xep.x4driver_get_frame_area_offset() == pytest.approx(0.18)
        assert device.xep.x4driver_get_tx_center_frequency() == 3
        assert device.xep.x4driver_get_prf_div() > 0
        device.xep.x4driver_set_fps(0)
        device.xep.x4driver_set_iterations(16)
        device.xep.x4driver_set_pulses_per_step(300)
        device.xep.x4driver_set_dac_min(949)
        device.xep.x4driver_set_dac_max(1100)
        device.xep.x4driver_set_tx_power(2)
        device.xep.x4driver_set_downconversion(False)
        area = device.xep.x4driver_get_frame_area()
        device.xep.x4driver_set_frame_area(area.start, area.end)
        device.xep.x4driver_set_frame_area_offset(0.18)
        device.xep.x4driver_set_tx_center_frequency(3)
        device.xep.x4driver_set_prf_div(device.xep.x4driver_get_prf_div())

        with pytest.raises(ValueError, match="sensitivity"):
            device.profile.set_sensitivity(10)
        with pytest.raises(ValueError, match="center-frequency"):
            device.profile.set_tx_center_frequency(2)
        with pytest.raises(ValueError, match="pin"):
            device.gpio.get_iopin_value(-1)
        with pytest.raises(ValueError, match="setup"):
            device.gpio.set_iopin_control(1, 0x10, 0)
        with pytest.raises(ValueError, match="value"):
            device.gpio.set_iopin_value(1, 2)
        with pytest.raises(ValueError, match="nonnegative"):
            device.filesystem.get_file_data(0, 0, -1, 1)

        if files:
            first = files[0]
            matching = device.filesystem.search_for_file_by_type(first.file_type)
            assert first in matching
            assert device.filesystem.get_file_data(first.file_type, first.identifier, 0, 0) == b""


@pytest.mark.hardware
def test_safe_optional_reads_fail_typed_when_firmware_rejects(device_port: str) -> None:
    with X4M200(port=device_port) as device:
        failures = (CommandRejectedError, CommandTimeoutError, ProtocolError)
        for call in (
            lambda: device.parameters.get_parameter_file("profile.par"),
            lambda: device.unsafe.registers.x4driver_get_spi_register(0),
            lambda: device.unsafe.registers.x4driver_get_pif_register(0),
            lambda: device.unsafe.registers.x4driver_get_xif_register(0),
        ):
            try:
                call()
            except failures:
                break
