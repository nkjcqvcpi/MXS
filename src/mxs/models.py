"""Public immutable data models."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray


@dataclass(slots=True, frozen=True)
class X4Config:
    downconversion: bool = False
    dac_min: int = 949
    dac_max: int = 1100
    iterations: int = 16
    tx_center_frequency: int = 3
    tx_power: int = 2
    pulses_per_step: int = 300
    frame_area_offset: float = 0.18
    frame_area: tuple[float, float] = (-0.5, 5.0)
    fps: float = 17.0

    def __post_init__(self) -> None:
        if not 0 <= self.dac_min <= self.dac_max <= 2047:
            raise ValueError("DAC values must satisfy 0 <= min <= max <= 2047")
        if self.iterations <= 0 or self.pulses_per_step <= 0:
            raise ValueError("iterations and pulses_per_step must be positive")
        if self.tx_center_frequency not in (3, 4):
            raise ValueError("tx_center_frequency must be 3 or 4")
        if not 0 <= self.tx_power <= 3:
            raise ValueError("tx_power must be between 0 and 3")
        if not self.frame_area[0] < self.frame_area[1]:
            raise ValueError("frame_area start must precede end")
        if self.fps <= 0:
            raise ValueError("fps must be positive")


@dataclass(slots=True, frozen=True)
class DetectionZone:
    start: float
    end: float


@dataclass(slots=True, frozen=True)
class DetectionZoneLimits:
    minimum: float
    maximum: float
    step: float


@dataclass(slots=True, frozen=True)
class LedControl:
    mode: int
    intensity: int | None = None


@dataclass(slots=True, frozen=True)
class FrameArea:
    start: float
    end: float


@dataclass(slots=True, frozen=True)
class FileIdentifier:
    file_type: int
    identifier: int


@dataclass(slots=True, frozen=True)
class FileMetadata:
    identifier: FileIdentifier
    length: int


@dataclass(slots=True, frozen=True)
class DeviceFile:
    metadata: FileMetadata
    data: bytes


@dataclass(slots=True, frozen=True)
class CirFrame:
    frame_counter: int
    timestamp_monotonic_ns: int
    content_id: int
    mode: Literal["rf", "iq"]
    samples: NDArray[np.float32] | NDArray[np.complex64]
    configured_frame_area: tuple[float, float]
    sequence_gap: int = 0


@dataclass(slots=True, frozen=True)
class Ack:
    pass


@dataclass(slots=True, frozen=True)
class Pong:
    value: int
    ready: bool


@dataclass(slots=True, frozen=True)
class ErrorResponse:
    error_code: int


@dataclass(slots=True, frozen=True)
class Reply:
    content_id: int
    info: int
    element_count: int
    element_size: int


@dataclass(slots=True, frozen=True)
class EmptyReply(Reply):
    pass


@dataclass(slots=True, frozen=True)
class ByteReply(Reply):
    values: bytes


@dataclass(slots=True, frozen=True)
class IntReply(Reply):
    values: NDArray[np.int32]


@dataclass(slots=True, frozen=True)
class FloatReply(Reply):
    values: NDArray[np.float32]


@dataclass(slots=True, frozen=True)
class StringReply(Reply):
    value: str


@dataclass(slots=True, frozen=True)
class UserReply(Reply):
    value: bytes


@dataclass(slots=True, frozen=True)
class DataFloatMessage:
    content_id: int
    frame_counter: int
    samples: NDArray[np.float32]


@dataclass(slots=True, frozen=True)
class DataByteMessage:
    content_id: int
    info: int
    data: bytes


@dataclass(slots=True, frozen=True)
class DataStringMessage:
    content_id: int
    info: int
    value: str


@dataclass(slots=True, frozen=True)
class DataUserMessage:
    content_id: int
    info: int
    data: bytes


@dataclass(slots=True, frozen=True)
class SystemMessage:
    content_id: int
    data: bytes = b""


@dataclass(slots=True, frozen=True)
class SleepStatus:
    frame_counter: int
    sensor_state: int
    respiration_rate: float
    distance: float
    signal_quality: int
    movement_slow: float
    movement_fast: float


@dataclass(slots=True, frozen=True)
class BasebandIqMessage:
    content_id: int
    frame_counter: int
    num_bins: int
    bin_length: float
    sample_frequency: float
    carrier_frequency: float
    range_offset: float
    samples: NDArray[np.complex64]


@dataclass(slots=True, frozen=True)
class BasebandAmplitudePhaseMessage:
    content_id: int
    frame_counter: int
    num_bins: int
    bin_length: float
    sample_frequency: float
    carrier_frequency: float
    range_offset: float
    amplitude: NDArray[np.float32]
    phase: NDArray[np.float32]


@dataclass(slots=True, frozen=True)
class RespirationStatus:
    frame_counter: int
    sensor_state: int
    respiration_rate: int
    distance: float
    movement: float
    signal_quality: int


@dataclass(slots=True, frozen=True)
class VitalSigns:
    frame_counter: int
    sensor_state: int
    respiration_rate: float
    respiration_distance: float
    respiration_confidence: float
    heart_rate: float
    heart_distance: float
    heart_confidence: float
    normalized_movement_slow: float
    normalized_movement_fast: float
    normalized_movement_start: float
    normalized_movement_end: float


@dataclass(slots=True, frozen=True)
class RespirationMovingList:
    frame_counter: int
    movement_slow: NDArray[np.float32]
    movement_fast: NDArray[np.float32]


@dataclass(slots=True, frozen=True)
class RespirationDetectionList:
    frame_counter: int
    distance: NDArray[np.float32]
    radar_cross_section: NDArray[np.float32]
    velocity: NDArray[np.float32]


@dataclass(slots=True, frozen=True)
class NormalizedMovementList:
    frame_counter: int
    start: float
    bin_length: float
    movement_slow: NDArray[np.float32]
    movement_fast: NDArray[np.float32]


@dataclass(slots=True, frozen=True)
class MatrixMessage:
    content_id: int
    frame_counter: int
    matrix_counter: int
    range_index: int
    range_bins: int
    frequency_count: int
    instance: int
    fps: float
    decimated_fps: float
    frequency_start: float
    frequency_step: float
    range: float
    values: NDArray[np.float32] | NDArray[np.uint8]
    step_start: float | None = None
    step_size: float | None = None


@dataclass(slots=True, frozen=True)
class UnknownMessage:
    response_type: int
    payload: bytes


Message = (
    Ack
    | Pong
    | ErrorResponse
    | Reply
    | DataFloatMessage
    | DataByteMessage
    | DataStringMessage
    | DataUserMessage
    | SystemMessage
    | SleepStatus
    | BasebandIqMessage
    | BasebandAmplitudePhaseMessage
    | RespirationStatus
    | VitalSigns
    | RespirationMovingList
    | RespirationDetectionList
    | NormalizedMovementList
    | MatrixMessage
    | UnknownMessage
)


@dataclass(slots=True, frozen=True)
class SessionStatistics:
    bytes_received: int = 0
    bytes_transmitted: int = 0
    classic_packets: int = 0
    noescape_packets: int = 0
    crc_errors: int = 0
    malformed_packets: int = 0
    unknown_packets: int = 0
    commands_sent: int = 0
    ack_count: int = 0
    firmware_errors: int = 0
    command_timeouts: int = 0
    frames_received: int = 0
    frame_counter_gaps: int = 0
    consumer_drops: int = 0
    queue_overflows: int = 0
    queue_high_water_mark: int = 0
    decoder_control_high_water_mark: int = 0
    decoder_stream_high_water_mark: int = 0
    raw_callback_high_water_mark: int = 0
    maximum_command_latency_seconds: float = 0.0
