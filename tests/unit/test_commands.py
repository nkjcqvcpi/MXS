import pytest

from mxs.commands import (
    build_ping,
    build_set_baudrate,
    build_set_dac_max,
    build_set_dac_min,
    build_set_dac_step,
    build_set_downconversion,
    build_set_enable,
    build_set_fps,
    build_set_frame_area,
    build_set_frame_area_offset,
    build_set_iopin_control,
    build_set_iterations,
    build_set_pulses_per_step,
    build_set_sensor_mode,
    build_set_tx_center_frequency,
    build_set_tx_power,
    build_system_info,
    build_x4_init,
)
from mxs.constants import IoPinFeature, IoPinSetup, SensorMode, SystemInfoCode

# Independently transcribed vectors generated from the local C field order and
# XOR/escaping rules, without calling the Python encoder under test.
VECTORS = {
    "STOP": "7d20134e7e",
    "MANUAL": "7d20124f7e",
    "PING": "7d01aeeaaaee7c7e",
    "INIT": "7d50200d7e",
    "BAUD": "7d908000100e00737e",
    "FPS0": "7d501010000000000000002d7e",
    "FPS17": "7d50101000000000008841e47e",
    "DC0": "7d501013000000002e7e",
    "DC1": "7d501013000000012f7e",
    "DMIN": "7d501016000000b50300009d7e",
    "DMAX": "7d5010170000004c040000627e",
    "ITER": "7d501012000000100000003f7e",
    "FREQ": "7d501020000000031e7e",
    "POWER": "7d501021000000021e7e",
    "PPS": "7d5010110000002c010000017e",
    "OFF": "7d501018000000ec51383e9e7e",
    "AREA": "7d501014000000000000bf0000a040767e",
}


def test_all_golden_commands() -> None:
    actual = {
        "STOP": build_set_sensor_mode(SensorMode.STOP),
        "MANUAL": build_set_sensor_mode(SensorMode.MANUAL),
        "PING": build_ping(),
        "INIT": build_x4_init(),
        "BAUD": build_set_baudrate(921600),
        "FPS0": build_set_fps(0),
        "FPS17": build_set_fps(17),
        "DC0": build_set_downconversion(False),
        "DC1": build_set_downconversion(True),
        "DMIN": build_set_dac_min(949),
        "DMAX": build_set_dac_max(1100),
        "ITER": build_set_iterations(16),
        "FREQ": build_set_tx_center_frequency(3),
        "POWER": build_set_tx_power(2),
        "PPS": build_set_pulses_per_step(300),
        "OFF": build_set_frame_area_offset(0.18),
        "AREA": build_set_frame_area(-0.5, 5.0),
    }
    assert {key: value.hex() for key, value in actual.items()} == VECTORS


@pytest.mark.parametrize(
    "call",
    [
        lambda: build_set_fps(-1),
        lambda: build_set_baudrate(9600),
        lambda: build_set_frame_area(1, 0),
        lambda: build_set_tx_power(8),
    ],
)
def test_command_validation(call: object) -> None:
    with pytest.raises(ValueError):
        call()  # type: ignore[operator]


def test_remaining_builders_and_bounds() -> None:
    assert build_set_sensor_mode(SensorMode.NORMAL)
    assert build_set_dac_step(4)
    assert build_set_enable(True)
    assert build_set_tx_center_frequency(4)
    for call in (
        lambda: build_set_iterations(-1),
        lambda: build_set_dac_step(256),
        lambda: build_set_downconversion(2),
        lambda: build_set_enable(2),
        lambda: build_set_fps(float("nan")),
        lambda: build_set_tx_center_frequency(2),
    ):
        with pytest.raises(ValueError):
            call()


def test_system_info_gpio_and_baud_golden_vectors() -> None:
    assert [build_system_info(code).hex() for code in SystemInfoCode] == [
        "7d905800b57e",
        "7d905801b47e",
        "7d905802b77e",
        "7d905803b67e",
        "7d905804b17e",
        "7d905806b37e",
        "7d905807b27e",
        "7d905808bd7e",
        "7d905809bc7e",
    ]
    setups = [IoPinSetup.INPUT, *IoPinSetup]
    assert [build_set_iopin_control(1, setup, 0).hex() for setup in setups] == [
        "7d40100100000000000000000000002c7e",
        "7d40100100000001000000000000002d7e",
        "7d40100100000002000000000000002e7e",
        "7d4010010000000400000000000000287e",
        "7d4010010000000800000000000000247e",
    ]
    assert [build_set_iopin_control(1, 0, feature).hex() for feature in IoPinFeature] == [
        "7d40100100000000000000000000002c7e",
        "7d40100100000000000000010000002d7e",
        "7d40100100000000000000020000002e7e",
        "7d40100100000000000000030000002f7e",
        "7d4010010000000000000004000000287e",
        "7d4010010000000000000005000000297e",
    ]
    assert build_set_baudrate(115200).hex() == "7d908000c20100ae7e"
