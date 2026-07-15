"""Recording and processing regressions gated by real-device preflight."""

import io
import json
import struct
import threading
import time
from collections.abc import Buffer
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from numpy.typing import NDArray

from mxs.errors import RecordingBackpressureError
from mxs.models import CirFrame, DataByteMessage, X4Config
from mxs.processing import (
    ProcessingPipeline,
    amplitude_phase_to_iq,
    analytic_signal,
    background_subtract,
    find_peaks,
    finite_or_raise,
    iq_to_amplitude_phase,
    normalize_frames,
    power_spectrum,
    range_axis,
    resample,
    unwrap_phase,
    zero_phase_filter,
)
from mxs.recording import (
    ChunkedCirRecorder,
    ParsedMessageRecorder,
    WireRecorder,
    replay_parsed,
    replay_wire,
    replay_wire_records,
    save_npz,
)
from mxs.recording.legacy import read_baseband_ap, read_baseband_iq, read_legacy
from mxs.transport import WireChunk


def _frame(counter: int, values: list[float] | None = None) -> CirFrame:
    samples = np.asarray(values or [1, 2], np.float32)
    return CirFrame(counter, counter * 10, 0, "rf", samples, (-0.5, 5.0))


def test_wire_recording_round_trip_and_truncation_recovery(tmp_path: Path) -> None:
    path = tmp_path / "test.mcpbin"
    with WireRecorder(path, "/dev/tty.usbmodem2101", 115200) as recorder:
        recorder.write_chunk(WireChunk(123, "tx", b"command"))
        recorder.write_chunk(WireChunk(456, "rx", b"two"))
    records = list(replay_wire_records(path))
    assert records == [WireChunk(123, "tx", b"command"), WireChunk(456, "rx", b"two")]
    assert list(replay_wire(path)) == [b"two"]
    assert recorder.bytes_written == 10 and recorder.backlog == 0
    assert recorder.queue_high_water_mark > 0
    path.write_bytes(path.read_bytes()[:-1])
    assert len(list(replay_wire_records(path, recover_truncated=True))) == 2
    with pytest.raises(ValueError, match="truncated"):
        list(replay_wire(path))

    invalid = tmp_path / "invalid.mcpbin"
    invalid.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="not an mxs"):
        list(replay_wire_records(invalid))
    invalid.write_bytes(b"X4MCPBIN")
    with pytest.raises(ValueError, match="header"):
        list(replay_wire_records(invalid))

    unsupported = tmp_path / "unsupported.mcpbin"
    unsupported.write_bytes(b"X4MCPBIN" + struct.pack("<IQI", 99, 0, 0))
    with pytest.raises(ValueError, match="unsupported"):
        list(replay_wire_records(unsupported))
    metadata = tmp_path / "metadata.mcpbin"
    metadata.write_bytes(b"X4MCPBIN" + struct.pack("<IQI", 2, 0, 4) + b"xx")
    with pytest.raises(ValueError, match="metadata"):
        list(replay_wire_records(metadata))
    legacy = tmp_path / "legacy.mcpbin"
    legacy.write_bytes(
        b"X4MCPBIN" + struct.pack("<IQI", 1, 0, 0) + struct.pack("<QI", 7, 3) + b"old"
    )
    assert list(replay_wire_records(legacy)) == [WireChunk(7, "rx", b"old")]

    unopened = WireRecorder(tmp_path / "unopened.mcpbin", "port", 115200)
    with pytest.raises(RuntimeError, match="not open"):
        unopened.write_chunk(b"data")
    with (
        pytest.raises(ValueError, match="direction"),
        WireRecorder(tmp_path / "direction.mcpbin", "port", 115200) as opened,
    ):
        opened.write_chunk(b"data", direction="sideways")


class _FailingBinaryFile(io.BytesIO):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error
        self.was_closed = False

    def write(self, data: Buffer) -> int:
        raise self.error

    def close(self) -> None:
        self.was_closed = True
        super().close()


def test_wire_backpressure_and_writer_failure_are_fatal(tmp_path: Path) -> None:
    failures: list[BaseException] = []
    full = WireRecorder(
        tmp_path / "full.mcpbin",
        "port",
        115200,
        fatal_callback=failures.append,
        queue_capacity=1,
    )
    full._file = io.BytesIO()  # pyright: ignore[reportPrivateUsage]
    full.write_chunk(b"first", timeout=0)
    with pytest.raises(RecordingBackpressureError):
        full.write_chunk(b"second", timeout=0)
    assert failures and isinstance(failures[0], RecordingBackpressureError)
    with pytest.raises(RecordingBackpressureError):
        full.write_chunk(b"third", timeout=0)

    writer_error = OSError("injected writer failure")
    failures.clear()
    recorder = WireRecorder(
        tmp_path / "writer-failure.mcpbin",
        "port",
        115200,
        fatal_callback=failures.append,
        queue_capacity=1,
    )
    recorder.__enter__()
    assert recorder._file is not None  # pyright: ignore[reportPrivateUsage]
    recorder._file.close()  # pyright: ignore[reportPrivateUsage]
    target = _FailingBinaryFile(writer_error)
    recorder._file = target  # pyright: ignore[reportPrivateUsage]
    recorder.write_chunk(b"trigger")
    deadline = time.monotonic() + 1
    while recorder._error is None and time.monotonic() < deadline:  # pyright: ignore[reportPrivateUsage]
        time.sleep(0.001)
    assert recorder._error is writer_error  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(OSError, match="injected writer failure"):
        recorder.__exit__(None, None, None)
    assert failures == [writer_error] and target.was_closed


def test_npz_chunked_and_parsed_recording(tmp_path: Path) -> None:
    frames = [_frame(1), _frame(2)]
    target = tmp_path / "capture.npz"
    save_npz(target, frames, X4Config(), port="/dev/tty.usbmodem2101", baudrate=115200)
    with np.load(target) as data:
        assert data["samples"].shape == (2, 2)
        assert data["frame_counters"].tolist() == [1, 2]
    with pytest.raises(ValueError, match="empty"):
        save_npz(tmp_path / "empty.npz", [], X4Config(), port="p", baudrate=115200)
    with pytest.raises(ValueError, match="fixed-size"):
        save_npz(
            tmp_path / "shape.npz",
            [_frame(1), _frame(2, [1, 2, 3])],
            X4Config(),
            port="p",
            baudrate=115200,
        )

    chunks = ChunkedCirRecorder(tmp_path / "chunks", chunk_frames=1)
    chunks.start()
    for frame in frames:
        chunks.append(frame)
    chunks.close()
    assert len(list((tmp_path / "chunks").glob("chunk-*.npy"))) == 2

    directory = tmp_path / "messages"
    with ParsedMessageRecorder(directory) as recorder:
        recorder.append(DataByteMessage(1, 2, b"abc"))
        recorder.append(_frame(3))
    records = list(replay_parsed(directory))
    assert records[0]["fields"] == {"content_id": 1, "info": 2, "data": b"abc"}
    values = cast("dict[str, object]", records[1]["fields"])
    assert np.array_equal(
        cast("NDArray[np.float32]", values["samples"]), np.asarray([1, 2], np.float32)
    )
    with (directory / "messages.jsonl").open("a") as target_file:
        target_file.write("{")
    assert len(list(replay_parsed(directory, recover_truncated=True))) == 2
    with pytest.raises(ValueError):
        list(replay_parsed(directory))

    stopped_chunks = ChunkedCirRecorder(tmp_path / "stopped-chunks")
    stopped_chunks._stop.set()  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError, match="closing"):
        stopped_chunks.append(_frame(1))
    chunk_error = RuntimeError("chunk writer failed")
    stopped_chunks._error = chunk_error  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError, match="chunk writer failed"):
        stopped_chunks.append(_frame(1))

    stopped_parsed = ParsedMessageRecorder(tmp_path / "stopped-parsed")
    stopped_parsed._stop.set()  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError, match="closing"):
        stopped_parsed.append("message")
    parsed_error = RuntimeError("parsed writer failed")
    stopped_parsed._error = parsed_error  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError, match="parsed writer failed"):
        stopped_parsed.append("message")


def test_background_recorders_propagate_encoding_failures(tmp_path: Path) -> None:
    chunked = ChunkedCirRecorder(tmp_path / "bad-chunks", chunk_frames=2)
    chunked.start()
    chunked.append(_frame(1, [1, 2]))
    chunked.append(_frame(2, [1, 2, 3]))
    deadline = time.monotonic() + 1
    while chunked._error is None and time.monotonic() < deadline:  # pyright: ignore[reportPrivateUsage]
        time.sleep(0.001)
    with pytest.raises(ValueError):
        chunked.close()

    parsed = ParsedMessageRecorder(tmp_path / "bad-parsed")
    parsed.start()
    parsed.append(object())
    deadline = time.monotonic() + 1
    while parsed._error is None and time.monotonic() < deadline:  # pyright: ignore[reportPrivateUsage]
        time.sleep(0.001)
    with pytest.raises(TypeError, match="unsupported"):
        parsed.close()

    full = ParsedMessageRecorder(tmp_path / "full-parsed", queue_size=1)
    full._queue.put_nowait("first")  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RecordingBackpressureError):
        full.append("second", timeout=0)


def test_parsed_recording_validation(tmp_path: Path) -> None:
    recorder = ParsedMessageRecorder(tmp_path)
    assert recorder._encode(np.float32(1.5), 0, "scalar") == 1.5  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(TypeError):
        recorder._encode(object(), 0, "bad")  # pyright: ignore[reportPrivateUsage]
    (tmp_path / "messages.jsonl").write_text("")
    with pytest.raises(ValueError, match="missing"):
        list(replay_parsed(tmp_path))
    (tmp_path / "messages.jsonl").write_text(json.dumps({"format": "wrong", "version": 1}) + "\n")
    with pytest.raises(ValueError, match="unsupported"):
        list(replay_parsed(tmp_path))


def test_legacy_baseband_readers_and_rejection(tmp_path: Path) -> None:
    import struct

    record = struct.pack("<IIffff4f", 1, 2, 0.1, 1.0, 7.29, -0.5, 1, 2, 3, 4)
    path = tmp_path / "baseband.dat"
    path.write_bytes(record)
    np.testing.assert_array_equal(next(read_baseband_iq(path)).samples, [1 + 3j, 2 + 4j])
    np.testing.assert_array_equal(next(read_baseband_ap(path)).amplitude, [1, 2])
    assert next(read_legacy(path, "baseband-iq")).frame_counter == 1
    with pytest.raises(NotImplementedError):
        read_legacy(path, "respiration")
    path.write_bytes(record[:-1])
    with pytest.raises(ValueError):
        list(read_baseband_iq(path))


def test_baseband_and_scipy_processing_utilities() -> None:
    iq = np.asarray([1 + 1j, -1j], np.complex64)
    amplitude, phase = iq_to_amplitude_phase(iq)
    np.testing.assert_allclose(amplitude_phase_to_iq(amplitude, phase), iq, atol=1e-6)
    np.testing.assert_allclose(unwrap_phase([0, 3.5]), [0, 3.5 - 2 * np.pi])
    np.testing.assert_allclose(range_axis(3, 0.5, -0.5), [-0.5, 0.0, 0.5])
    np.testing.assert_allclose(normalize_frames([[3.0, 4.0], [0.0, 0.0]]), [[0.6, 0.8], [0, 0]])
    np.testing.assert_array_equal(background_subtract([2, 3], [1, 1]), [1, 2])
    np.testing.assert_array_equal(finite_or_raise([1, 2]), [1, 2])
    with pytest.raises(TypeError):
        iq_to_amplitude_phase([1.0])
    with pytest.raises(ValueError):
        amplitude_phase_to_iq([-1], [0])
    with pytest.raises(ValueError):
        range_axis(2, 0)
    with pytest.raises(ValueError):
        finite_or_raise([np.nan])

    sample_rate = 64.0
    samples = np.sin(2 * np.pi * 8 * np.arange(128) / sample_rate)
    frequency, power = power_spectrum(samples, sample_rate)
    assert frequency[np.argmax(power)] == pytest.approx(8.0)
    np.testing.assert_allclose(zero_phase_filter(samples, [1.0]), samples)
    assert resample(samples, 64).shape == (64,)
    assert find_peaks(samples, height=0.9)[0].size > 0
    assert analytic_signal(samples).shape == samples.shape
    with pytest.raises(ValueError):
        power_spectrum(samples, 0)
    with pytest.raises(ValueError):
        resample(samples, 0)


def test_processing_pipeline_order_errors_and_bounds() -> None:
    with ProcessingPipeline[int, int](lambda value: value * 2, max_workers=2) as pipeline:
        pipeline.submit(2)
        pipeline.submit(3)
        assert [pipeline.read(), pipeline.read()] == [4, 6]
    with ProcessingPipeline[int, int](lambda value: value + 1, backend="inline") as pipeline:
        pipeline.submit(1)
        assert pipeline.read() == 2
    with ProcessingPipeline[int, int](
        lambda value: (_ for _ in ()).throw(ValueError(str(value))), backend="inline"
    ) as pipeline:
        pipeline.submit(7)
        with pytest.raises(ValueError, match="7"):
            pipeline.read()
    with pytest.raises(ValueError):
        ProcessingPipeline(lambda value: value, queue_size=0)
    with pytest.raises(ValueError):
        ProcessingPipeline(lambda value: value, backend="invalid")  # type: ignore[arg-type]

    def reordered(value: int) -> int:
        if value == 0:
            time.sleep(0.02)
        return value

    with ProcessingPipeline[int, int](reordered, max_workers=2) as pipeline:
        pipeline.submit(0)
        pipeline.submit(1)
        assert pipeline.read() == 0
        assert pipeline.read() == 1

    release = threading.Event()
    with ProcessingPipeline[int, int](
        lambda value: release.wait() or value, queue_size=1
    ) as pipeline:
        pipeline.submit(1)
        with pytest.raises(TimeoutError):
            pipeline.submit(2, timeout=0.001)
        release.set()
        assert pipeline.read() == 1
