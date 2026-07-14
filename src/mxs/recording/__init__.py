"""Raw wire, NPZ, and crash-resilient chunked CIR recording."""

import json
import queue
import struct
import threading
import time
from base64 import b64decode, b64encode
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import BinaryIO, Literal, TextIO, cast

import numpy as np
from numpy.typing import NDArray

from ..models import CirFrame, X4Config
from ..transport import WireChunk

WIRE_MAGIC = b"X4MCPBIN"
WIRE_VERSION = 2
PARSED_VERSION = 1


class WireRecorder:
    def __init__(
        self,
        path: Path,
        port: str,
        baudrate: int,
        metadata: dict[str, object] | None = None,
        *,
        fatal_callback: Callable[[BaseException], None] | None = None,
        queue_capacity: int = 256,
    ) -> None:
        self.path = path
        self._file: BinaryIO | None = None
        self._port = port
        self._baudrate = baudrate
        self._metadata = metadata or {}
        self._lock = threading.Lock()
        self._queue: queue.Queue[WireChunk | None] = queue.Queue(queue_capacity)
        self._thread = threading.Thread(target=self._run, name="mxs-wire-writer", daemon=False)
        self._error: BaseException | None = None
        self._bytes_written = 0
        self._queue_high_water_mark = 0
        self._fatal_callback = fatal_callback

    def set_fatal_callback(self, callback: Callable[[BaseException], None]) -> None:
        self._fatal_callback = callback

    @property
    def bytes_written(self) -> int:
        return self._bytes_written

    @property
    def backlog(self) -> int:
        return self._queue.qsize()

    @property
    def queue_high_water_mark(self) -> int:
        return self._queue_high_water_mark

    def __enter__(self) -> WireRecorder:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("wb")
        metadata = json.dumps(
            {"port": self._port, "baudrate": self._baudrate, **self._metadata},
            sort_keys=True,
        ).encode()
        self._file.write(WIRE_MAGIC)
        self._file.write(struct.pack("<IQI", WIRE_VERSION, time.time_ns(), len(metadata)))
        self._file.write(metadata)
        self._file.flush()
        self._thread.start()
        return self

    def write_chunk(
        self,
        chunk: WireChunk | bytes,
        *,
        direction: str = "rx",
        timeout: float = 1.0,
    ) -> None:
        if self._file is None:
            raise RuntimeError("wire recorder is not open")
        if self._error is not None:
            raise self._error
        if isinstance(chunk, bytes):
            chunk = WireChunk(time.monotonic_ns(), cast("Literal['rx', 'tx']", direction), chunk)
        if chunk.direction not in ("rx", "tx"):
            raise ValueError("direction must be 'rx' or 'tx'")
        try:
            self._queue.put(chunk, timeout=timeout)
            self._queue_high_water_mark = max(self._queue_high_water_mark, 1, self._queue.qsize())
        except queue.Full as error:
            from ..errors import RecordingBackpressureError

            recording_error = RecordingBackpressureError("raw-wire recording queue is full")
            self._error = recording_error
            if self._fatal_callback is not None:
                self._fatal_callback(recording_error)
            raise recording_error from error

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._file is not None:
            self._queue.put(None)
            self._thread.join(5.0)
            if self._thread.is_alive():
                raise RuntimeError("wire recording worker failed to terminate")
            if self._error is not None:
                raise self._error
            self._file.flush()
            self._file.close()
            self._file = None

    def _run(self) -> None:
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    with self._lock:
                        assert self._file is not None
                        self._file.write(struct.pack("<QBI", time.monotonic_ns(), 0xFF, 0))
                    return
                code = 0 if item.direction == "rx" else 1
                with self._lock:
                    assert self._file is not None
                    self._file.write(
                        struct.pack("<QBI", item.timestamp_monotonic_ns, code, len(item.data))
                    )
                    self._file.write(item.data)
                    self._bytes_written += len(item.data)
        except BaseException as error:
            self._error = error
            if self._fatal_callback is not None:
                self._fatal_callback(error)


def replay_wire_records(path: Path, *, recover_truncated: bool = False) -> Iterator[WireChunk]:
    with path.open("rb") as source:
        if source.read(len(WIRE_MAGIC)) != WIRE_MAGIC:
            raise ValueError("not an mxs wire recording")
        header = source.read(struct.calcsize("<IQI"))
        if len(header) != struct.calcsize("<IQI"):
            raise ValueError("truncated wire header")
        version, _created, metadata_length = struct.unpack("<IQI", header)
        if version not in (1, WIRE_VERSION):
            raise ValueError(f"unsupported wire version {version}")
        if len(source.read(metadata_length)) != metadata_length:
            raise ValueError("truncated wire metadata")
        record_format = "<QI" if version == 1 else "<QBI"
        record_size = struct.calcsize(record_format)
        while header := source.read(record_size):
            if len(header) != record_size:
                if recover_truncated:
                    return
                raise ValueError("truncated wire record header")
            if version == 1:
                timestamp, length = struct.unpack(record_format, header)
                direction = 0
            else:
                timestamp, direction, length = struct.unpack(record_format, header)
                if direction == 0xFF and length == 0:
                    return
            chunk = source.read(length)
            if len(chunk) != length:
                if recover_truncated:
                    return
                raise ValueError("truncated wire record")
            yield WireChunk(timestamp, "rx" if direction == 0 else "tx", chunk)


def replay_wire(path: Path, *, recover_truncated: bool = False) -> Iterator[bytes]:
    for record in replay_wire_records(path, recover_truncated=recover_truncated):
        if record.direction == "rx":
            yield record.data


def save_npz(
    path: Path,
    frames: Iterable[CirFrame],
    config: X4Config,
    *,
    port: str,
    baudrate: int,
) -> None:
    captured = list(frames)
    if not captured:
        raise ValueError("cannot save an empty capture")
    shapes = {frame.samples.shape for frame in captured}
    if len(shapes) != 1:
        raise ValueError("NPZ capture requires fixed-size frames")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        samples=np.stack([frame.samples for frame in captured]),
        frame_counters=np.asarray([frame.frame_counter for frame in captured], dtype=np.uint32),
        monotonic_timestamps=np.asarray(
            [frame.timestamp_monotonic_ns for frame in captured], dtype=np.uint64
        ),
        sequence_gaps=np.asarray([frame.sequence_gap for frame in captured], dtype=np.uint32),
        mode=np.asarray(captured[0].mode),
        config=np.asarray(json.dumps(asdict(config), sort_keys=True)),
        port=np.asarray(port),
        baudrate=np.asarray(baudrate, dtype=np.uint32),
    )


class ChunkedCirRecorder:
    """Write independent .npy chunks and one JSONL index on a writer thread."""

    def __init__(self, directory: Path, chunk_frames: int = 256, queue_size: int = 512) -> None:
        self.directory = directory
        self.chunk_frames = chunk_frames
        self._queue: queue.Queue[CirFrame | None] = queue.Queue(queue_size)
        self._thread = threading.Thread(target=self._run, name="mxs-recorder", daemon=False)
        self._error: BaseException | None = None

    def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._thread.start()

    def append(self, frame: CirFrame, timeout: float = 1.0) -> None:
        if self._error is not None:
            raise self._error
        self._queue.put(frame, timeout=timeout)

    def close(self, timeout: float = 5.0) -> None:
        self._queue.put(None, timeout=timeout)
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise RuntimeError("recording worker failed to terminate")
        if self._error is not None:
            raise self._error

    def _run(self) -> None:
        chunk: list[CirFrame] = []
        index = 0
        try:
            with (self.directory / "metadata.jsonl").open("a", encoding="utf-8") as metadata:
                while True:
                    item = self._queue.get()
                    if item is None:
                        if chunk:
                            self._flush_chunk(chunk, index, metadata)
                        return
                    chunk.append(item)
                    if len(chunk) >= self.chunk_frames:
                        self._flush_chunk(chunk, index, metadata)
                        metadata.flush()
                        chunk.clear()
                        index += 1
        except BaseException as error:
            self._error = error

    def _flush_chunk(self, chunk: list[CirFrame], index: int, metadata: TextIO) -> None:
        filename = f"chunk-{index:06d}.npy"
        np.save(self.directory / filename, np.stack([frame.samples for frame in chunk]))
        record = {
            "file": filename,
            "frame_counters": [frame.frame_counter for frame in chunk],
            "timestamps": [frame.timestamp_monotonic_ns for frame in chunk],
            "sequence_gaps": [frame.sequence_gap for frame in chunk],
            "mode": chunk[0].mode,
        }
        metadata.write(json.dumps(record) + "\n")


class ParsedMessageRecorder:
    """Record heterogeneous immutable messages without blocking the decoder."""

    def __init__(self, directory: Path, queue_size: int = 512) -> None:
        self.directory = directory
        self._queue: queue.Queue[object | None] = queue.Queue(queue_size)
        self._thread = threading.Thread(target=self._run, name="mxs-message-writer", daemon=False)
        self._error: BaseException | None = None
        self.queue_high_water_mark = 0

    def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "arrays").mkdir(exist_ok=True)
        self._thread.start()

    def append(self, message: object, timeout: float = 1.0) -> None:
        if self._error is not None:
            raise self._error
        try:
            self._queue.put(message, timeout=timeout)
            self.queue_high_water_mark = max(self.queue_high_water_mark, 1, self._queue.qsize())
        except queue.Full as error:
            from ..errors import RecordingBackpressureError

            raise RecordingBackpressureError("parsed-message recording queue is full") from error

    def close(self, timeout: float = 5.0) -> None:
        self._queue.put(None, timeout=timeout)
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise RuntimeError("parsed-message recording worker failed to terminate")
        if self._error is not None:
            raise self._error

    def __enter__(self) -> ParsedMessageRecorder:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def _run(self) -> None:
        try:
            path = self.directory / "messages.jsonl"
            with path.open("a+", encoding="utf-8") as target:
                target.seek(0)
                existing = sum(1 for _ in target)
                if existing == 0:
                    target.write(
                        json.dumps({"format": "mxs-parsed", "version": PARSED_VERSION}) + "\n"
                    )
                    target.flush()
                    existing = 1
                index = existing - 1
                while True:
                    message = self._queue.get()
                    if message is None:
                        return
                    record = {
                        "index": index,
                        "timestamp_monotonic_ns": time.monotonic_ns(),
                        "type": f"{type(message).__module__}.{type(message).__qualname__}",
                        "fields": self._encode(message, index, "message"),
                    }
                    target.write(json.dumps(record, sort_keys=True) + "\n")
                    target.flush()
                    index += 1
        except BaseException as error:
            self._error = error

    def _encode(self, value: object, index: int, name: str) -> object:
        if isinstance(value, np.ndarray):
            relative = Path("arrays") / f"{index:08d}-{name}.npy"
            np.save(
                self.directory / relative,
                cast("NDArray[np.generic]", value),
                allow_pickle=False,
            )
            return {"npy": relative.as_posix()}
        if isinstance(value, bytes):
            return {"base64": b64encode(value).decode("ascii")}
        if is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: self._encode(
                    cast(object, getattr(value, field.name)), index, field.name
                )
                for field in fields(value)
            }
        if isinstance(value, (tuple, list)):
            return [
                self._encode(item, index, f"{name}-{position}")
                for position, item in enumerate(cast("tuple[object, ...] | list[object]", value))
            ]
        if isinstance(value, np.generic):
            return cast(object, value.item())
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise TypeError(f"unsupported parsed-message value {type(value).__name__}")


def replay_parsed(
    directory: Path, *, recover_truncated: bool = False
) -> Iterator[dict[str, object]]:
    path = directory / "messages.jsonl"
    with path.open(encoding="utf-8") as source:
        try:
            header = cast(object, json.loads(next(source)))
        except (StopIteration, json.JSONDecodeError) as error:
            raise ValueError("missing parsed-message recording header") from error
        if header != {"format": "mxs-parsed", "version": PARSED_VERSION}:
            raise ValueError("unsupported parsed-message recording")
        for line in source:
            try:
                record = cast("dict[str, object]", json.loads(line))
                record["fields"] = _decode_parsed_value(directory, record["fields"])
            except json.JSONDecodeError, KeyError, OSError, ValueError:
                if recover_truncated:
                    return
                raise ValueError("damaged parsed-message record") from None
            yield record


def _decode_parsed_value(directory: Path, value: object) -> object:
    if isinstance(value, list):
        return [_decode_parsed_value(directory, item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        mapping = cast("dict[str, object]", value)
        if set(mapping) == {"npy"}:
            return np.load(directory / str(mapping["npy"]), allow_pickle=False)
        if set(mapping) == {"base64"}:
            return b64decode(str(mapping["base64"]), validate=True)
        return {key: _decode_parsed_value(directory, item) for key, item in mapping.items()}
    return value
