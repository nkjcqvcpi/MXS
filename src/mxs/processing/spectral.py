"""Explicit SciPy-backed filtering and spectral helpers."""

# SciPy 1.18 leaves several signal APIs partially unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportArgumentType=false

from typing import Any, cast

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import signal


def power_spectrum(
    values: ArrayLike,
    sample_rate: float,
    *,
    axis: int = -1,
    window: str = "hann",
    detrend: str = "constant",
) -> tuple[NDArray[np.float64], NDArray[np.floating]]:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    data = np.asarray(values)
    frequencies, spectrum = signal.periodogram(
        data, fs=sample_rate, window=window, detrend=detrend, axis=axis
    )
    return frequencies, spectrum


def zero_phase_filter(
    values: ArrayLike, b: ArrayLike, a: ArrayLike = (1.0,), *, axis: int = -1
) -> NDArray[Any]:
    return signal.filtfilt(np.asarray(b), np.asarray(a), np.asarray(values), axis=axis)


def resample(values: ArrayLike, count: int, *, axis: int = -1) -> NDArray[Any]:
    if count <= 0:
        raise ValueError("count must be positive")
    return cast(NDArray[Any], signal.resample(np.asarray(values), count, axis=axis))


def find_peaks(
    values: ArrayLike, **kwargs: Any
) -> tuple[NDArray[np.intp], dict[str, NDArray[Any]]]:
    return signal.find_peaks(np.asarray(values), **kwargs)


def analytic_signal(values: ArrayLike, *, axis: int = -1) -> NDArray[np.complexfloating]:
    return cast(NDArray[np.complexfloating], signal.hilbert(np.asarray(values), axis=axis))
