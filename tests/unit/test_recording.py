from pathlib import Path

import numpy as np

from x4cir.models import CirFrame, X4Config
from x4cir.recording import ChunkedCirRecorder, WireRecorder, replay_wire, save_npz


def frame(counter: int) -> CirFrame:
    return CirFrame(counter, counter * 10, 0, "rf", np.asarray([1, 2], np.float32), (-0.5, 5.0))


def test_wire_round_trip_and_truncation(tmp_path: Path) -> None:
    path = tmp_path / "test.mcpbin"
    with WireRecorder(path, "fake", 115200) as recorder:
        recorder.write_chunk(b"one")
        recorder.write_chunk(b"two")
    assert list(replay_wire(path)) == [b"one", b"two"]
    path.write_bytes(path.read_bytes()[:-1])
    try:
        list(replay_wire(path))
    except ValueError as error:
        assert "truncated" in str(error)
    else:
        raise AssertionError("truncated recording was accepted")


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
