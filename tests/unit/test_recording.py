import io
import time
from collections.abc import Buffer
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from numpy.typing import NDArray

from mxs.errors import RecordingBackpressureError
from mxs.models import CirFrame, DataByteMessage, X4Config
from mxs.recording import (
    ChunkedCirRecorder,
    ParsedMessageRecorder,
    WireRecorder,
    replay_parsed,
    replay_wire,
    replay_wire_records,
    save_npz,
)
from mxs.transport import WireChunk

# pyright: reportPrivateUsage=false


def frame(counter: int) -> CirFrame:
    return CirFrame(counter, counter * 10, 0, "rf", np.asarray([1, 2], np.float32), (-0.5, 5.0))


def test_wire_round_trip_and_truncation(tmp_path: Path) -> None:
    path = tmp_path / "test.mcpbin"
    with WireRecorder(path, "fake", 115200) as recorder:
        assert recorder.bytes_written == 0
        assert recorder.backlog == 0
        assert recorder.queue_high_water_mark == 0
        recorder.write_chunk(b"one")
        recorder.write_chunk(WireChunk(123, "tx", b"command"))
        recorder.write_chunk(WireChunk(456, "rx", b"two"))
        assert recorder.queue_high_water_mark > 0
    assert list(replay_wire(path)) == [b"one", b"two"]
    records = list(replay_wire_records(path))
    assert records[1] == WireChunk(123, "tx", b"command")
    assert records[2] == WireChunk(456, "rx", b"two")
    assert recorder.bytes_written == 13
    assert recorder.backlog == 0
    path.write_bytes(path.read_bytes()[:-1])
    assert len(list(replay_wire_records(path, recover_truncated=True))) == 3
    try:
        list(replay_wire(path))
    except ValueError as error:
        assert "truncated" in str(error)
    else:
        raise AssertionError("truncated recording was accepted")


def test_wire_validation_and_recovery_paths(tmp_path: Path) -> None:
    recorder = WireRecorder(tmp_path / "closed.mcpbin", "fake", 115200)
    with pytest.raises(RuntimeError, match="not open"):
        recorder.write_chunk(b"data")
    path = tmp_path / "invalid.mcpbin"
    path.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="not an mxs"):
        list(replay_wire_records(path))
    path.write_bytes(b"X4MCPBIN")
    with pytest.raises(ValueError, match="header"):
        list(replay_wire_records(path))

    path = tmp_path / "direction.mcpbin"
    with (
        pytest.raises(ValueError, match="direction"),
        WireRecorder(path, "fake", 115200) as opened,
    ):
        opened.write_chunk(b"data", direction="sideways")


def test_wire_backpressure_is_fatal(tmp_path: Path) -> None:
    failures: list[BaseException] = []
    recorder = WireRecorder(
        tmp_path / "full.mcpbin",
        "fake",
        115200,
        fatal_callback=failures.append,
        queue_capacity=1,
    )
    recorder._file = io.BytesIO()  # pyright: ignore[reportPrivateUsage]
    recorder.write_chunk(b"first", timeout=0)
    with pytest.raises(RecordingBackpressureError):
        recorder.write_chunk(b"second", timeout=0)
    assert isinstance(failures[0], RecordingBackpressureError)
    with pytest.raises(RecordingBackpressureError):
        recorder.write_chunk(b"third", timeout=0)


class FailingBinaryFile(io.BytesIO):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error
        self.was_closed = False

    def write(self, data: Buffer) -> int:
        raise self.error

    def close(self) -> None:
        self.was_closed = True
        super().close()


def test_wire_writer_failure_with_full_queue_closes_without_deadlock(tmp_path: Path) -> None:
    writer_error = OSError("injected writer failure")
    failures: list[BaseException] = []
    recorder = WireRecorder(
        tmp_path / "writer-failure.mcpbin",
        "fake",
        115200,
        fatal_callback=failures.append,
        queue_capacity=1,
    )
    recorder.__enter__()
    assert recorder._file is not None
    recorder._file.close()
    target = FailingBinaryFile(writer_error)
    recorder._file = target
    recorder.write_chunk(b"trigger")
    deadline = time.monotonic() + 1
    while recorder._error is None and time.monotonic() < deadline:
        time.sleep(0.001)
    assert recorder._error is writer_error
    recorder._queue.put_nowait(WireChunk(time.monotonic_ns(), "rx", b"queued"))
    started = time.monotonic()
    with pytest.raises(OSError) as captured:
        recorder.__exit__(None, None, None)
    assert time.monotonic() - started < 1
    assert captured.value is writer_error
    assert failures == [writer_error]
    assert target.was_closed
    with pytest.raises(RuntimeError, match="not open"):
        recorder.write_chunk(b"after-close")


def test_wire_writer_failure_during_close_preserves_error_and_closes_file(
    tmp_path: Path,
) -> None:
    writer_error = OSError("injected clean-marker failure")
    recorder = WireRecorder(tmp_path / "close-failure.mcpbin", "fake", 115200)
    recorder.__enter__()
    assert recorder._file is not None
    recorder._file.close()
    target = FailingBinaryFile(writer_error)
    recorder._file = target
    with pytest.raises(OSError) as captured:
        recorder.__exit__(None, None, None)
    assert captured.value is writer_error
    assert target.was_closed


def test_npz_and_chunked_recording(tmp_path: Path) -> None:
    frames = [frame(1), frame(2)]
    target = tmp_path / "capture.npz"
    save_npz(target, frames, X4Config(), port="fake", baudrate=115200)
    with np.load(target) as data:
        assert data["samples"].shape == (2, 2)
        assert data["frame_counters"].tolist() == [1, 2]
    chunks = ChunkedCirRecorder(tmp_path / "chunks", chunk_frames=1)
    chunks.start()
    for item in frames:
        chunks.append(item)
    chunks.close()
    assert len(list((tmp_path / "chunks").glob("chunk-*.npy"))) == 2


def test_parsed_message_recording_and_recovery(tmp_path: Path) -> None:
    directory = tmp_path / "messages"
    with ParsedMessageRecorder(directory) as recorder:
        recorder.append(DataByteMessage(1, 2, b"abc"))
        recorder.append(frame(3))
    records = list(replay_parsed(directory))
    assert len(records) == 2
    assert records[0]["fields"] == {"content_id": 1, "info": 2, "data": b"abc"}
    values = records[1]["fields"]
    assert isinstance(values, dict)
    assert np.array_equal(
        cast("NDArray[np.float32]", values["samples"]), np.asarray([1, 2], np.float32)
    )
    assert recorder.queue_high_water_mark > 0
    with (directory / "messages.jsonl").open("a") as target:
        target.write("{")
    assert len(list(replay_parsed(directory, recover_truncated=True))) == 2
    with pytest.raises(ValueError):
        list(replay_parsed(directory))


def test_parsed_message_validation(tmp_path: Path) -> None:
    recorder = ParsedMessageRecorder(tmp_path)
    assert recorder._encode(np.float32(1.5), 0, "scalar") == 1.5
    with pytest.raises(TypeError):
        recorder._encode(object(), 0, "bad")
    recorder._error = RuntimeError("writer failed")
    with pytest.raises(RuntimeError, match="writer failed"):
        recorder.append("message")
    (tmp_path / "messages.jsonl").write_text("")
    with pytest.raises(ValueError, match="missing"):
        list(replay_parsed(tmp_path))
    (tmp_path / "messages.jsonl").write_text('{"format":"wrong","version":1}\n')
    with pytest.raises(ValueError, match="unsupported"):
        list(replay_parsed(tmp_path))
