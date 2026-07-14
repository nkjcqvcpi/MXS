"""Command-line interface for discovery, diagnostics, capture, and recording."""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

import numpy as np

from .device import X4M200
from .discovery import list_serial_ports
from .models import CirFrame, X4Config
from .recording import WireRecorder, save_npz
from .session import DeviceSession


def _baud(value: str) -> str | int:
    if value == "auto":
        return value
    parsed = int(value)
    if parsed not in (115200, 921600):
        raise argparse.ArgumentTypeError("baud must be auto, 115200, or 921600")
    return parsed


def _base_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="x4cir")
    parser.add_argument("--debug", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ports")
    for name in ("sniff", "probe"):
        child = sub.add_parser(name)
        child.add_argument("--port", default="/dev/tty.usbmodem2101")
        child.add_argument("--baud", type=_baud, default="auto")
        if name == "sniff":
            child.add_argument("--seconds", type=float, default=5.0)
            child.add_argument("--hex", action="store_true", dest="show_hex")
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
    return parser


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


def _stream(args: argparse.Namespace) -> int:
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
            raw_chunk_callback=recorder.write_chunk,
        )
        try:
            session.open()
            time.sleep(args.duration)
        finally:
            session.close_passive()
    print(f"recorded raw serial traffic to {args.output}")
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
        if args.command == "capture":
            return _capture(args)
        if args.command == "stream":
            return _stream(args)
        if args.command == "record-wire":
            return _record_wire(args)
        parser.error("unknown command")
    except KeyboardInterrupt:
        return 130
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
