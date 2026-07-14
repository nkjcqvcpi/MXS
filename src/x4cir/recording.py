"""Raw wire, NPZ, and crash-resilient chunked CIR recording."""

import json
import queue
import struct
import threading
import time
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from pathlib import Path
from typing import BinaryIO, TextIO

import numpy as np

from .models import CirFrame, X4Config

WIRE_MAGIC = b"X4MCPBIN"
WIRE_VERSION = 1


class WireRecorder:
    def __init__(
        self, path: Path, port: str, baudrate: int, metadata: dict[str, object] | None = None
    ) -> None:
        self.path = path
        self._file: BinaryIO | None = None
        self._port = port
        self._baudrate = baudrate
        self._metadata = metadata or {}
        self._lock = threading.Lock()

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
        return self

    def write_chunk(self, chunk: bytes) -> None:
        if self._file is None:
            raise RuntimeError("wire recorder is not open")
        with self._lock:
            self._file.write(struct.pack("<QI", time.monotonic_ns(), len(chunk)))
            self._file.write(chunk)

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None


def replay_wire(path: Path) -> Iterator[bytes]:
    with path.open("rb") as source:
        if source.read(len(WIRE_MAGIC)) != WIRE_MAGIC:
            raise ValueError("not an x4cir wire recording")
        header = source.read(struct.calcsize("<IQI"))
        if len(header) != struct.calcsize("<IQI"):
            raise ValueError("truncated wire header")
        version, _created, metadata_length = struct.unpack("<IQI", header)
        if version != WIRE_VERSION:
            raise ValueError(f"unsupported wire version {version}")
        if len(source.read(metadata_length)) != metadata_length:
            raise ValueError("truncated wire metadata")
        record_size = struct.calcsize("<QI")
        while header := source.read(record_size):
            if len(header) != record_size:
                raise ValueError("truncated wire record header")
            _timestamp, length = struct.unpack("<QI", header)
            chunk = source.read(length)
            if len(chunk) != length:
                raise ValueError("truncated wire record")
            yield chunk


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
        self._thread = threading.Thread(target=self._run, name="x4cir-recorder", daemon=False)
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
