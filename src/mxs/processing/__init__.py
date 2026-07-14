"""Optional NumPy/SciPy host-side processing utilities."""

from .baseband import (
    amplitude_phase_to_iq,
    background_subtract,
    finite_or_raise,
    iq_to_amplitude_phase,
    normalize_frames,
    range_axis,
    unwrap_phase,
)
from .pipeline import ProcessingPipeline
from .spectral import analytic_signal, find_peaks, power_spectrum, resample, zero_phase_filter

__all__ = [
    "ProcessingPipeline",
    "amplitude_phase_to_iq",
    "analytic_signal",
    "background_subtract",
    "find_peaks",
    "finite_or_raise",
    "iq_to_amplitude_phase",
    "normalize_frames",
    "power_spectrum",
    "range_axis",
    "resample",
    "unwrap_phase",
    "zero_phase_filter",
]
