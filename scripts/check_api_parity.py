"""Audit public Legacy-SW headers against the checked-in parity manifest."""

import argparse
import re
from pathlib import Path

from mxs.interfaces.core import (
    FilesystemAdminInterface,
    FilesystemInterface,
    GpioInterface,
    ModuleInterface,
    NoisemapInterface,
    OutputsInterface,
    ParametersInterface,
    ProfileInterface,
    RegisterInterface,
    UnsafeInterface,
    XepInterface,
)

ROOT = Path(__file__).resolve().parents[1]
HEADER_ROOT = ROOT / "Legacy-SW/ModuleConnector/ModuleConnector-osx-1/include"
MANIFEST = ROOT / "docs/x4m200-api-parity.md"
METHOD = re.compile(r"^\s+int\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)
ROW = re.compile(r"^\| (X4M200|XEP) \| `([A-Za-z_]\w*)` \|", re.MULTILINE)

UNSUPPORTED = {
    "set_periodic_noisemap_store",
    "get_periodic_noisemap_store",
    "set_normalization",
    "get_normalization",
    "set_phase_noise_correction",
    "get_phase_noise_correction",
    "set_decimation_factor",
    "get_decimation_factor",
    "set_number_format",
    "get_number_format",
    "set_legacy_output",
    "get_legacy_output",
    "x4driver_write_to_i2c_register",
    "x4driver_read_from_i2c_register",
}
UNSAFE = {
    "reset_to_factory_preset",
    "start_bootloader",
    "inject_frame",
    "prepare_inject_frame",
    "system_run_test",
    "x4driver_set_spi_register",
    "x4driver_set_pif_register",
    "x4driver_write_to_spi_register",
    "x4driver_set_xif_register",
    "create_file",
    "open_file",
    "set_file_data",
    "close_file",
    "delete_file",
    "format_filesystem",
    "set_file",
}

MODULE = {"set_debug_level", "set_baudrate", "ping", "get_system_info", "reset", "module_reset"}
PROFILE = {
    "load_profile",
    "set_sensor_mode",
    "get_sensor_mode",
    "set_sensitivity",
    "get_sensitivity",
    "set_tx_center_frequency",
    "get_tx_center_frequency",
    "set_detection_zone",
    "get_detection_zone",
    "get_detection_zone_limits",
    "set_led_control",
    "get_led_control",
    "get_profileid",
}
OUTPUTS = {
    "set_output_control",
    "get_output_control",
    "set_debug_output_control",
    "get_debug_output_control",
}
GPIO = {"set_iopin_control", "get_iopin_control", "set_iopin_value", "get_iopin_value"}
NOISEMAP = {
    "load_noisemap",
    "store_noisemap",
    "delete_noisemap",
    "set_noisemap_control",
    "get_noisemap_control",
    "set_periodic_noisemap_store",
    "get_periodic_noisemap_store",
}
PARAMETERS = {"get_parameter_file", "set_parameter_file"}
FILESYSTEM = {
    "search_for_file_by_type",
    "find_all_files",
    "get_file_length",
    "get_file_data",
    "get_file",
}
FILESYSTEM_ADMIN = {
    "create_file",
    "open_file",
    "set_file_data",
    "close_file",
    "delete_file",
    "format_filesystem",
    "set_file",
}
REGISTERS = {
    "x4driver_set_spi_register",
    "x4driver_get_spi_register",
    "x4driver_set_pif_register",
    "x4driver_write_to_spi_register",
    "x4driver_read_from_spi_register",
    "x4driver_write_to_i2c_register",
    "x4driver_read_from_i2c_register",
    "x4driver_get_pif_register",
    "x4driver_set_xif_register",
    "x4driver_get_xif_register",
}


def api_path(method: str) -> str:
    if method.startswith(("peek_message_", "read_message_")):
        return "device.messages"
    if method in FILESYSTEM_ADMIN:
        return f"device.unsafe.filesystem_admin.{method}"
    if method in REGISTERS:
        return f"device.unsafe.registers.{method}"
    if method in UNSAFE:
        return f"device.unsafe.{method}"
    for prefix, methods in (
        ("module", MODULE),
        ("profile", PROFILE),
        ("outputs", OUTPUTS),
        ("gpio", GPIO),
        ("noisemap", NOISEMAP),
        ("parameters", PARAMETERS),
        ("filesystem", FILESYSTEM),
    ):
        if method in methods:
            return f"device.{prefix}.{method}"
    return f"device.xep.{method}"


def header_methods(interface: str) -> list[str]:
    text = (HEADER_ROOT / f"{interface}.hpp").read_text(encoding="utf-8", errors="ignore")
    return list(dict.fromkeys(METHOD.findall(text)))


def manifest_methods() -> set[tuple[str, str]]:
    return set(ROW.findall(MANIFEST.read_text(encoding="utf-8")))


def manifest_rows() -> dict[tuple[str, str], tuple[str, str]]:
    rows: dict[tuple[str, str], tuple[str, str]] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 10 or cells[0] not in ("X4M200", "XEP"):
            continue
        rows[(cells[0], cells[1].strip("`"))] = (cells[5].strip("`"), cells[9])
    return rows


API_OWNERS = {
    "device.module": ModuleInterface,
    "device.profile": ProfileInterface,
    "device.outputs": OutputsInterface,
    "device.xep": XepInterface,
    "device.gpio": GpioInterface,
    "device.noisemap": NoisemapInterface,
    "device.parameters": ParametersInterface,
    "device.filesystem": FilesystemInterface,
    "device.unsafe": UnsafeInterface,
    "device.unsafe.registers": RegisterInterface,
    "device.unsafe.filesystem_admin": FilesystemAdminInterface,
}


def expected_status(method: str) -> str:
    if method in UNSUPPORTED:
        return "firmware-unsupported"
    if method in UNSAFE:
        return "implemented-unsafe"
    return "implemented"


def audit() -> list[str]:
    documented = manifest_methods()
    problems = [
        f"{interface}.{method}"
        for interface in ("X4M200", "XEP")
        for method in header_methods(interface)
        if (interface, method) not in documented
    ]
    rows = manifest_rows()
    for interface in ("X4M200", "XEP"):
        for method in header_methods(interface):
            key = (interface, method)
            if key not in rows:
                continue
            path, status = rows[key]
            expected_path = api_path(method)
            if path != expected_path:
                problems.append(f"{interface}.{method}: path {path!r} != {expected_path!r}")
            wanted_status = expected_status(method)
            if status != wanted_status:
                problems.append(f"{interface}.{method}: status {status!r} != {wanted_status!r}")
            if path == "device.messages":
                continue
            owner_path, symbol = path.rsplit(".", 1)
            owner = API_OWNERS.get(owner_path)
            if owner is None or not hasattr(owner, symbol):
                problems.append(f"{interface}.{method}: unresolved API {path!r}")
    return problems


def write_manifest() -> None:
    lines = [
        "# X4M200 and XEP API parity\n",
        (
            "Generated from the local public headers. `firmware-unsupported` means the host "
            "header exists but the target producer has no safe wire command; MXS raises "
            "`UnsupportedFirmwareError`. Message read pairs map to bounded typed topics.\n"
        ),
        (
            "| Interface | Legacy method | Local source | Command or message | Expected "
            "response | MXS API | Offline test | Hardware test | Firmware requirement | Status |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for interface in ("X4M200", "XEP"):
        for method in header_methods(interface):
            status = expected_status(method)
            if method.startswith(("peek_message_", "read_message_")):
                command = "typed inbound message"
                response = "topic model"
                api = "device.messages"
            else:
                command = "source-derived MCP command"
                response = "ACK or strict typed REPLY"
                api = api_path(method)
            source = f"Legacy-SW/ModuleConnector/ModuleConnector-osx-1/include/{interface}.hpp"
            lines.append(
                f"| {interface} | `{method}` | `{source}` | {command} | {response} | `{api}` | "
                f"unit/golden | safe where applicable | see firmware-capabilities | {status} |"
            )
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        write_manifest()
    missing = audit()
    if missing:
        print("Missing parity rows:")
        print("\n".join(missing))
        return 1
    print("All public X4M200.hpp and XEP.hpp methods are classified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
