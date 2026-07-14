import struct
from pathlib import Path

import numpy as np
import pytest

from mxs.recording.legacy import read_baseband_ap, read_baseband_iq, read_legacy


def legacy_record() -> bytes:
    return struct.pack("<IIffff4f", 1, 2, 0.1, 1.0, 7.29, -0.5, 1, 2, 3, 4)


def test_legacy_baseband_readers_and_rejection(tmp_path: Path) -> None:
    path = tmp_path / "baseband.dat"
    path.write_bytes(legacy_record())
    iq = next(read_baseband_iq(path))
    np.testing.assert_array_equal(iq.samples, [1 + 3j, 2 + 4j])
    ap = next(read_baseband_ap(path))
    np.testing.assert_array_equal(ap.amplitude, [1, 2])
    assert next(read_legacy(path, "baseband-iq")).frame_counter == 1
    with pytest.raises(NotImplementedError):
        read_legacy(path, "respiration")
    path.write_bytes(legacy_record()[:-1])
    with pytest.raises(ValueError):
        list(read_baseband_iq(path))
    with pytest.raises(ValueError):
        list(read_baseband_ap(path))
