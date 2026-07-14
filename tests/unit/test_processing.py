import numpy as np
import pytest

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


def test_baseband_vector_utilities() -> None:
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


def test_scipy_utilities_on_analytic_signal() -> None:
    sample_rate = 64.0
    time = np.arange(128) / sample_rate
    values = np.sin(2 * np.pi * 8 * time)
    frequency, power = power_spectrum(values, sample_rate)
    assert frequency[np.argmax(power)] == pytest.approx(8.0)
    filtered = zero_phase_filter(values, [1.0])
    np.testing.assert_allclose(filtered, values)
    assert resample(values, 64).shape == (64,)
    peaks, _ = find_peaks(values, height=0.9)
    assert peaks.size > 0
    assert analytic_signal(values).shape == values.shape
    with pytest.raises(ValueError):
        power_spectrum(values, 0)
    with pytest.raises(ValueError):
        resample(values, 0)


def test_processing_pipeline_order_errors_and_backends() -> None:
    with ProcessingPipeline[int, int](
        lambda value: value * 2, backend="thread", max_workers=2
    ) as pipe:
        assert pipe.submit(2) == 0
        assert pipe.submit(3) == 1
        assert [pipe.read(), pipe.read()] == [4, 6]
    with ProcessingPipeline[int, int](lambda value: value + 1, backend="inline") as pipe:
        pipe.submit(1)
        assert pipe.read() == 2
    with ProcessingPipeline[int, int](
        lambda value: (_ for _ in ()).throw(ValueError(str(value))), backend="inline"
    ) as pipe:
        pipe.submit(7)
        with pytest.raises(ValueError, match="7"):
            pipe.read()
    with pytest.raises(ValueError):
        ProcessingPipeline(lambda value: value, queue_size=0)
    with pytest.raises(ValueError):
        ProcessingPipeline(lambda value: value, backend="invalid")  # type: ignore[arg-type]
