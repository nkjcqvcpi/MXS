import pytest

from mxs.commands import (
    build_app_action,
    build_app_get,
    build_app_set,
    build_debug_level,
    build_factory_reset,
    build_filesystem,
    build_get_iopin_control,
    build_get_iopin_value,
    build_get_output_control,
    build_get_sensor_mode,
    build_inject_frame,
    build_load_profile,
    build_module_reset,
    build_noisemap,
    build_parameter_file,
    build_prepare_inject_frame,
    build_set_detection_zone,
    build_set_iopin_control,
    build_set_iopin_value,
    build_set_led_control,
    build_set_output_control,
    build_set_prf_div,
    build_start_bootloader,
    build_system_info,
    build_system_test,
    build_x4_get,
    build_x4_read,
    build_x4_write,
)
from mxs.constants import ProfileId


def test_extended_command_builders_and_validation() -> None:
    assert {member.name: int(member) for member in ProfileId} == {
        "RESPIRATION": 0x1423A2D6,
        "SLEEP": 0x00F17B17,
        "RESPIRATION_2": 0x064E57AD,
        "RESPIRATION_3": 0x47FABEBA,
        "RESPIRATION_4": 0x4AC5D074,
        "RESPIRATION_5": 0xA9E03260,
    }
    builders = (
        build_get_sensor_mode(),
        build_load_profile(1),
        build_module_reset(),
        build_debug_level(1),
        build_start_bootloader(),
        build_system_info(2),
        build_system_test(1),
        build_factory_reset(),
        build_app_get(1),
        build_app_set(1, b"a"),
        build_set_detection_zone(0, 1),
        build_set_led_control(1, 2),
        build_set_output_control(1, 1),
        build_set_prf_div(16),
        build_get_output_control(1),
        build_set_iopin_control(1, 2, 3),
        build_get_iopin_control(1),
        build_set_iopin_value(1, 1),
        build_get_iopin_value(1),
        build_noisemap(0x10, 1),
        build_app_action(0x13),
        build_filesystem(0x64, 1),
        build_parameter_file("a.txt"),
        build_parameter_file("a.txt", b"data"),
        build_prepare_inject_frame(1, 2, 0),
        build_inject_frame(1, 2, b"\0" * 16),
        build_x4_get(1),
        build_x4_read(1, b"a"),
        build_x4_write(1, b"a"),
    )
    assert all(packet.startswith(b"\x7d") and packet.endswith(b"\x7e") for packet in builders)
    with pytest.raises(ValueError):
        build_debug_level(10)
    with pytest.raises(ValueError):
        build_set_detection_zone(2, 1)
    with pytest.raises(ValueError):
        build_parameter_file("../bad", b"x")
    with pytest.raises(ValueError):
        build_prepare_inject_frame(0, 2, 0)
    with pytest.raises(ValueError):
        build_inject_frame(1, 2, b"bad")
    with pytest.raises(ValueError):
        build_set_prf_div(256)
