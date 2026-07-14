from mxs.capabilities import DeviceCapabilities


def test_capability_queries_are_conservative() -> None:
    assert DeviceCapabilities(supports_baseband_ap=True).supports("supports_baseband_ap")
    assert not DeviceCapabilities().supports("supports_baseband_ap")
