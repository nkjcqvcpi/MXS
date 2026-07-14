"""Vectorized baseband transformations."""

import numpy as np
from numpy.typing import ArrayLike, NDArray


def iq_to_amplitude_phase(iq: ArrayLike) -> tuple[NDArray[np.floating], NDArray[np.floating]]:
    values = np.asarray(iq)
    if not np.issubdtype(values.dtype, np.complexfloating):
        raise TypeError("IQ input must have a complex dtype")
    return np.abs(values), np.angle(values)


def amplitude_phase_to_iq(amplitude: ArrayLike, phase: ArrayLike) -> NDArray[np.complexfloating]:
    amplitude_values, phase_values = np.broadcast_arrays(amplitude, phase)
    if np.any(amplitude_values < 0):
        raise ValueError("amplitude must be nonnegative")
    return np.asarray(amplitude_values * np.exp(1j * phase_values))


def unwrap_phase(phase: ArrayLike, *, axis: int = -1) -> NDArray[np.floating]:
    return np.unwrap(np.asarray(phase), axis=axis)


def range_axis(num_bins: int, bin_length: float, range_offset: float = 0.0) -> NDArray[np.float64]:
    if num_bins < 0 or not np.isfinite(bin_length) or bin_length <= 0:
        raise ValueError("num_bins must be nonnegative and bin_length positive")
    return range_offset + np.arange(num_bins, dtype=np.float64) * bin_length


def finite_or_raise(values: ArrayLike) -> NDArray[np.generic]:
    result = np.asarray(values)
    if not np.all(np.isfinite(result)):
        raise ValueError("array contains NaN or infinity")
    return result


def normalize_frames(values: ArrayLike, *, axis: int = -1) -> NDArray[np.floating]:
    array = np.asarray(values)
    scale = np.linalg.norm(array, axis=axis, keepdims=True)
    return np.divide(array, scale, out=np.zeros_like(array), where=scale != 0)


def background_subtract(values: ArrayLike, background: ArrayLike) -> NDArray[np.generic]:
    return np.asarray(values) - np.asarray(background)
