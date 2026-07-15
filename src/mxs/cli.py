"""Command-line interface for discovery, diagnostics, capture, and recording."""

import argparse
import json
import logging
import signal
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .constants import (
    IoPinFeature,
    IoPinSetup,
    OutputControl,
    OutputFeature,
    SensorMode,
    SystemInfoCode,
)
from .device import X4M200
from .discovery import list_serial_ports
from .errors import MxsError
from .message_hub import MessageHub
from .models import CirFrame, X4Config
from .recording import ParsedMessageRecorder, WireRecorder, replay_parsed, replay_wire, save_npz
from .session import DeviceSession


def _baud(value: str) -> str | int:
    if value == "auto":
        return value
    parsed = int(value)
    if parsed not in (115200, 921600):
        raise argparse.ArgumentTypeError("baud must be auto, 115200, or 921600")
    return parsed


def _base_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mxs")
    parser.add_argument("--debug", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ports")
    for name in ("sniff", "probe", "info", "capabilities", "doctor"):
        child = sub.add_parser(name)
        child.add_argument("--port", default="/dev/tty.usbmodem2101")
        child.add_argument("--baud", type=_baud, default="auto")
        if name == "sniff":
            child.add_argument("--seconds", type=float, default=5.0)
            child.add_argument("--hex", action="store_true", dest="show_hex")
    replay = sub.add_parser("replay-wire")
    replay.add_argument("path", type=Path)
    benchmark = sub.add_parser("benchmark")
    benchmark.add_argument("path", type=Path)
    benchmark.add_argument("--iterations", type=int, default=100)
    profile = sub.add_parser("profile")
    profile.add_argument("action", choices=("load",))
    profile.add_argument("profile_id", type=lambda value: int(value, 0))
    _device_options(profile)
    sensor_mode = sub.add_parser("sensor-mode")
    sensor_mode.add_argument("mode", choices=("run", "idle", "manual", "stop"))
    _device_options(sensor_mode)
    getter = sub.add_parser("get")
    getter.add_argument(
        "setting",
        choices=("xep.fps", "xep.iterations", "xep.frame-area", "profile-id", "sensor-mode"),
    )
    _device_options(getter)
    setter = sub.add_parser("set")
    setter.add_argument("setting", choices=("xep.fps", "xep.iterations", "profile-id"))
    setter.add_argument("value")
    _device_options(setter)
    outputs = sub.add_parser("outputs")
    outputs.add_argument("action", choices=("get", "set"))
    outputs.add_argument("feature", type=lambda value: int(value, 0))
    outputs.add_argument("control", nargs="?", type=lambda value: int(value, 0))
    _device_options(outputs)
    messages = sub.add_parser("messages")
    messages.add_argument("topic", choices=MessageHub.TOPICS)
    messages.add_argument("--count", type=int, default=1)
    _device_options(messages)
    noisemap = sub.add_parser("noisemap")
    noisemap.add_argument("action", choices=("load", "get-control", "set-control"))
    noisemap.add_argument("value", nargs="?", type=lambda value: int(value, 0))
    _device_options(noisemap)
    gpio = sub.add_parser("gpio")
    gpio.add_argument("action", choices=("get-control", "get-value", "set-control", "set-value"))
    gpio.add_argument("pin", type=lambda value: int(value, 0))
    gpio.add_argument("values", nargs="*", type=lambda value: int(value, 0))
    _device_options(gpio)
    unsafe = sub.add_parser(
        "unsafe",
        description=(
            "Destructive operations require their documented MXS_ENABLE_* environment gate."
        ),
    )
    unsafe.add_argument(
        "action",
        choices=("store-noisemap", "delete-noisemap", "factory-reset", "format-filesystem"),
    )
    unsafe.add_argument("--key", type=lambda value: int(value, 0), default=0)
    unsafe.add_argument("--confirm", action="store_true")
    _device_options(unsafe)
    files = sub.add_parser("files")
    files.add_argument("action", choices=("list",))
    _device_options(files)
    capture = sub.add_parser("capture")
    _capture_options(capture)
    stream = sub.add_parser("stream")
    _capture_options(stream, output=False, frames=False)
    stream.add_argument("--stats", action="store_true")
    wire = sub.add_parser("record-wire")
    wire.add_argument("--port", default="/dev/tty.usbmodem2101")
    wire.add_argument("--baud", type=_baud, default="auto")
    wire.add_argument("--duration", type=float, required=True)
    wire.add_argument("--output", type=Path, required=True)
    messages = sub.add_parser("record-messages")
    _device_options(messages)
    messages.add_argument("--duration", type=float, required=True)
    messages.add_argument("--output", type=Path, required=True)
    replay_messages = sub.add_parser("replay-messages")
    replay_messages.add_argument("path", type=Path)
    return parser


def _device_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", default="/dev/tty.usbmodem2101")
    parser.add_argument("--baud", type=_baud, default="auto")


def _capture_options(
    parser: argparse.ArgumentParser, *, output: bool = True, frames: bool = True
) -> None:
    parser.add_argument("--port", default="/dev/tty.usbmodem2101")
    parser.add_argument("--baud", type=_baud, default="auto")
    parser.add_argument("--mode", choices=("rf", "iq"), default="rf")
    parser.add_argument("--fps", type=float, default=17.0)
    if frames:
        parser.add_argument("--frames", type=int, default=1000)
    if output:
        parser.add_argument("--output", type=Path, required=True)


def _passive(args: argparse.Namespace, show: bool) -> int:
    chunks: list[bytes] = []
    session = DeviceSession(args.port, args.baud, raw_chunk_callback=chunks.append)
    try:
        session.open()
        time.sleep(args.seconds if show else 1.0)
        stats = session.statistics()
        if show and args.show_hex:
            for chunk in chunks:
                print(chunk.hex(" "))
        print(f"port: {args.port}")
        print(f"detected baud: {session.detected_baudrate}")
        print(f"valid packet count: {session.router.valid_packet_count}")
        print(f"CRC error count: {stats.crc_errors}")
        print(f"message types: {', '.join(sorted(session.router.message_types)) or '-'}")
        content = ", ".join(f"0x{value:08x}" for value in sorted(session.router.content_ids))
        print(f"content IDs: {content or '-'}")
        print(f"latest frame counter: {session.router.last_counter}")
        return 0
    finally:
        session.close_passive()


def _capture(args: argparse.Namespace) -> int:
    config = X4Config(downconversion=args.mode == "iq", fps=args.fps)
    captured: list[CirFrame] = []
    with X4M200(port=args.port, baudrate=args.baud) as radar:
        radar.configure(config)
        radar.start()
        for _ in range(args.frames):
            captured.append(radar.read_frame(timeout=2.0))
        baudrate = radar.detected_baudrate
    if baudrate is None:
        raise RuntimeError("baud detection result unavailable")
    save_npz(args.output, captured, config, port=args.port, baudrate=baudrate)
    print(f"saved {len(captured)} {args.mode} frames to {args.output}")
    return 0


def _stream(  # pragma: no cover - intentionally unbounded interactive command
    args: argparse.Namespace,
) -> int:
    config = X4Config(downconversion=args.mode == "iq", fps=args.fps)
    with X4M200(
        port=args.port,
        baudrate=args.baud,
        overflow_policy="drop_oldest",
        frame_queue_size=16,
    ) as radar:
        radar.configure(config)
        radar.start()
        for frame in radar.frames():
            if args.stats:
                finite = int(np.isfinite(frame.samples).sum())
                print(
                    f"counter={frame.frame_counter} bins={frame.samples.size} "
                    f"finite={finite} gap={frame.sequence_gap}"
                )
    return 0


def _record_wire(args: argparse.Namespace) -> int:
    probe = DeviceSession(args.port, args.baud)
    probe.open()
    baudrate = probe.detected_baudrate
    probe.close_passive()
    if baudrate is None:
        raise RuntimeError("baud detection result unavailable")
    with WireRecorder(args.output, args.port, baudrate) as recorder:
        session = DeviceSession(
            args.port,
            baudrate,
            wire_chunk_callback=recorder.write_chunk,
        )
        failure_handler = getattr(session, "recording_failed", None)
        if failure_handler is not None:
            recorder.set_fatal_callback(failure_handler)
        try:
            session.open()
            time.sleep(args.duration)
        finally:
            session.close_passive()
    print(f"recorded raw serial traffic to {args.output}")
    return 0


def _record_messages(args: argparse.Namespace) -> int:
    with (
        ParsedMessageRecorder(args.output) as recorder,
        X4M200(port=args.port, baudrate=args.baud) as device,
    ):
        subscription = device.messages.all.subscribe(512, "error")
        deadline = time.monotonic() + args.duration
        count = 0
        while time.monotonic() < deadline:
            try:
                timeout = max(0.0, min(0.25, deadline - time.monotonic()))
                recorder.append(subscription.read(timeout=timeout))
                count += 1
            except TimeoutError:
                continue
    print(f"recorded {count} parsed messages to {args.output}")
    return 0


def _info(args: argparse.Namespace, capabilities: bool = False) -> int:
    with X4M200(port=args.port, baudrate=args.baud) as device:
        if capabilities:
            print(json.dumps(asdict(device.probe_capabilities()), sort_keys=True))
        else:
            for code in SystemInfoCode:
                try:
                    print(f"{code.name.lower()}: {device.module.get_system_info(code)}")
                except Exception as error:
                    print(f"{code.name.lower()}: unsupported ({error})")
    return 0


def _benchmark(args: argparse.Namespace) -> int:
    from .framing import McpStreamDecoder

    chunks = list(replay_wire(args.path))
    byte_count = sum(map(len, chunks)) * args.iterations
    started = time.perf_counter()
    for _ in range(args.iterations):
        decoder = McpStreamDecoder()
        for chunk in chunks:
            decoder.feed(chunk)
    elapsed = time.perf_counter() - started
    print(
        json.dumps(
            {"bytes": byte_count, "seconds": elapsed, "bytes_per_second": byte_count / elapsed}
        )
    )
    return 0


def _configured_action(args: argparse.Namespace) -> int:
    with X4M200(port=args.port, baudrate=args.baud) as device:
        if args.command == "profile":
            device.profile.load_profile(args.profile_id)
        elif args.command == "sensor-mode":
            mode = {
                "run": SensorMode.RUN,
                "idle": SensorMode.IDLE,
                "manual": SensorMode.MANUAL,
                "stop": SensorMode.STOP,
            }[args.mode]
            device.profile.set_sensor_mode(mode)
        elif args.command == "files":
            for item in device.filesystem.find_all_files():
                print(f"0x{item.file_type:08x}\t0x{item.identifier:08x}")
        elif args.command == "get":
            getters = {
                "xep.fps": device.xep.x4driver_get_fps,
                "xep.iterations": device.xep.x4driver_get_iterations,
                "xep.frame-area": device.xep.x4driver_get_frame_area,
                "profile-id": device.profile.get_profileid,
                "sensor-mode": device.profile.get_sensor_mode,
            }
            print(getters[args.setting]())
        elif args.command == "set":
            setters = {
                "xep.fps": lambda: device.xep.x4driver_set_fps(float(args.value)),
                "xep.iterations": lambda: device.xep.x4driver_set_iterations(int(args.value, 0)),
                "profile-id": lambda: device.profile.load_profile(int(args.value, 0)),
            }
            setters[args.setting]()
        elif args.command == "outputs":
            feature = OutputFeature(args.feature)
            if args.action == "get":
                print(
                    json.dumps(
                        {
                            "feature": feature.name,
                            "control": int(device.outputs.get_output_control(feature)),
                        }
                    )
                )
            else:
                if args.control is None:
                    raise ValueError("outputs set requires CONTROL")
                device.outputs.set_output_control(feature, OutputControl(args.control))
        elif args.command == "messages":
            subscription = getattr(device.messages, args.topic).subscribe(
                max(1, args.count), "error"
            )
            for _ in range(args.count):
                message = subscription.read(timeout=5.0)
                print(
                    json.dumps(
                        asdict(message)
                        if hasattr(message, "__dataclass_fields__")
                        else {"value": str(message)},
                        default=str,
                    )
                )
        elif args.command == "noisemap":
            if args.action == "load":
                device.noisemap.load_noisemap()
            elif args.action == "get-control":
                print(json.dumps({"control": device.noisemap.get_noisemap_control()}))
            else:
                if args.value is None:
                    raise ValueError("noisemap set-control requires VALUE")
                device.noisemap.set_noisemap_control(args.value)
        elif args.command == "gpio":
            if args.action == "get-control":
                setup, feature = device.gpio.get_iopin_control(args.pin)
                print(json.dumps({"pin": args.pin, "setup": int(setup), "feature": int(feature)}))
            elif args.action == "get-value":
                print(json.dumps({"pin": args.pin, "value": device.gpio.get_iopin_value(args.pin)}))
            elif args.action == "set-value" and len(args.values) == 1:
                device.gpio.set_iopin_value(args.pin, args.values[0])
            elif args.action == "set-control" and len(args.values) == 2:
                device.gpio.set_iopin_control(
                    args.pin, IoPinSetup(args.values[0]), IoPinFeature(args.values[1])
                )
            else:
                raise ValueError(f"invalid values for gpio {args.action}")
        elif args.command == "unsafe":
            if args.action == "store-noisemap":
                device.noisemap.store_noisemap()
            elif args.action == "delete-noisemap":
                device.noisemap.delete_noisemap()
            elif args.action == "factory-reset":
                device.unsafe.reset_to_factory_preset(confirm=args.confirm)
            else:
                device.unsafe.filesystem_admin.format_filesystem(key=args.key)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _base_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(130))
    try:
        if args.command == "ports":
            for port in list_serial_ports():
                print(f"{port.device}\t{port.description}\t{port.manufacturer or ''}")
            return 0
        if args.command == "sniff":
            return _passive(args, True)
        if args.command == "probe":
            return _passive(args, False)
        if args.command == "info":
            return _info(args)
        if args.command == "capabilities":
            return _info(args, True)
        if args.command == "doctor":
            return _passive(args, False)
        if args.command == "capture":
            return _capture(args)
        if args.command == "stream":
            return _stream(args)
        if args.command == "record-wire":
            return _record_wire(args)
        if args.command == "record-messages":
            return _record_messages(args)
        if args.command == "replay-messages":
            for record in replay_parsed(args.path, recover_truncated=True):
                summary = {key: value for key, value in record.items() if key != "fields"}
                print(json.dumps(summary, sort_keys=True))
            return 0
        if args.command == "replay-wire":
            chunks = list(replay_wire(args.path, recover_truncated=True))
            print(json.dumps({"chunks": len(chunks), "bytes": sum(map(len, chunks))}))
            return 0
        if args.command == "benchmark":
            return _benchmark(args)
        if args.command in (
            "profile",
            "sensor-mode",
            "get",
            "set",
            "outputs",
            "messages",
            "noisemap",
            "gpio",
            "unsafe",
            "files",
        ):
            return _configured_action(args)
        parser.error("unknown command")
    except KeyboardInterrupt:
        return 130
    except (MxsError, ValueError, TimeoutError) as error:
        command = getattr(args, "command", "mxs")
        print(
            f"mxs {command} failed: {error}. Close and reopen the device; call recover() "
            "after a command timeout.",
            file=sys.stderr,
        )
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
