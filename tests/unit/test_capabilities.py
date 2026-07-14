from mxs.capabilities import DeviceCapabilities
from mxs.device import X4M200
from tests.conftest import FakeSerialFactory


def test_capability_queries_are_conservative() -> None:
    assert DeviceCapabilities(supports_baseband_ap=True).supports("supports_baseband_ap")
    assert not DeviceCapabilities().supports("supports_baseband_ap")


def test_probe_capabilities_records_diagnostics_without_identity_inference() -> None:
    device = X4M200(port="fake", serial_factory=FakeSerialFactory())

    class Module:
        def get_system_info(self, code: object) -> str:
            if int(code) == 7:  # type: ignore[arg-type]
                raise ValueError("malformed optional reply")
            return "X4M200"

    class Profile:
        @staticmethod
        def get_profileid() -> int:
            return 1

        @staticmethod
        def get_sensor_mode() -> int:
            raise ValueError("bad mode")

    device.module = Module()  # type: ignore[assignment]
    device.profile = Profile()  # type: ignore[assignment]
    result = device.probe_capabilities()
    assert result.order_code == "X4M200"
    assert result.supports_device_filesystem is None
    assert {failure.operation for failure in result.probe_failures} == {
        "version_list",
        "sensor_mode",
    }
