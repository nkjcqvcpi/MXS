import struct

import numpy as np
import pytest

from mxs.constants import (
    CONTENT_ID_BASEBAND_AP,
    CONTENT_ID_NOISEMAP_BYTE,
    CONTENT_ID_NORMALIZED_MOVEMENT,
    CONTENT_ID_RESPIRATION_DETECTION_LIST,
    CONTENT_ID_RESPIRATION_MOVING_LIST,
    CONTENT_ID_RESPIRATION_STATUS,
    CONTENT_ID_VITAL_SIGNS,
)
from mxs.errors import MalformedMessageError
from mxs.messages import decode_message
from mxs.models import (
    BasebandAmplitudePhaseMessage,
    DataByteMessage,
    DataStringMessage,
    DataUserMessage,
    MatrixMessage,
    NormalizedMovementList,
    RespirationDetectionList,
    RespirationMovingList,
    RespirationStatus,
    SystemMessage,
    VitalSigns,
)


def app(content_id: int, data: bytes) -> bytes:
    return b"\x50" + struct.pack("<I", content_id) + data


def test_application_status_and_list_decoders() -> None:
    respiration = decode_message(
        app(CONTENT_ID_RESPIRATION_STATUS, struct.pack("<IIIffI", 1, 2, 12, 3, 4, 5))
    )
    assert isinstance(respiration, RespirationStatus)
    vital = decode_message(app(CONTENT_ID_VITAL_SIGNS, struct.pack("<II10f", 1, 2, *range(10))))
    assert isinstance(vital, VitalSigns)
    moving = decode_message(
        app(CONTENT_ID_RESPIRATION_MOVING_LIST, struct.pack("<II4f", 4, 2, 1, 2, 3, 4))
    )
    assert isinstance(moving, RespirationMovingList)
    detection = decode_message(
        app(
            CONTENT_ID_RESPIRATION_DETECTION_LIST,
            struct.pack("<II6f", 4, 2, 1, 2, 3, 4, 5, 6),
        )
    )
    assert isinstance(detection, RespirationDetectionList)
    normalized = decode_message(
        app(CONTENT_ID_NORMALIZED_MOVEMENT, struct.pack("<IffI4f", 4, 0, 0.5, 2, 1, 2, 3, 4))
    )
    assert isinstance(normalized, NormalizedMovementList)
    with pytest.raises(MalformedMessageError):
        decode_message(app(CONTENT_ID_RESPIRATION_MOVING_LIST, struct.pack("<II", 1, 2)))


def test_baseband_ap_matrix_and_generic_data() -> None:
    ap = decode_message(
        app(CONTENT_ID_BASEBAND_AP, struct.pack("<IIffff4f", 1, 2, 0.1, 1, 2, 3, 4, 5, 6, 7))
    )
    assert isinstance(ap, BasebandAmplitudePhaseMessage)
    np.testing.assert_array_equal(ap.amplitude, [4, 5])
    matrix_header = struct.pack("<6I7f", 1, 2, 0, 3, 2, 0, -10, 0.5, 17, 8.5, 0, 1, 2)
    matrix = decode_message(app(CONTENT_ID_NOISEMAP_BYTE, matrix_header + b"\x01\x02"))
    assert isinstance(matrix, MatrixMessage)
    assert matrix.values.dtype == np.uint8
    assert isinstance(decode_message(b"\x30" + struct.pack("<I", 5) + b"ok"), SystemMessage)
    assert isinstance(
        decode_message(b"\xa0\x10" + struct.pack("<III", 1, 2, 2) + b"ab"), DataByteMessage
    )
    assert isinstance(
        decode_message(b"\xa0\x13" + struct.pack("<III", 1, 2, 2) + b"hi"), DataStringMessage
    )
    assert isinstance(
        decode_message(b"\xa0\x50" + struct.pack("<III", 1, 2, 2) + b"ab"), DataUserMessage
    )
