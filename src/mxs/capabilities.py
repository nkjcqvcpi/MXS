"""Conservative firmware capability representation."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceCapabilities:
    item_number: str | None = None
    order_code: str | None = None
    firmware_id: str | None = None
    firmware_version: str | None = None
    build: str | None = None
    serial_number: str | None = None
    version_list: str | None = None
    profile_id: int | None = None
    sensor_mode: int | None = None
    supports_vital_signs: bool | None = None
    supports_normalized_movement: bool | None = None
    supports_default_noisemap: bool | None = None
    supports_periodic_noisemap_store: bool | None = None
    supports_baseband_ap: bool | None = None
    supports_pulse_doppler: bool | None = None
    supports_device_filesystem: bool | None = None
    supports_bulk_spi: bool | None = None
    supports_frame_injection: bool | None = None

    def supports(self, name: str) -> bool:
        value = getattr(self, name)
        return value is True
