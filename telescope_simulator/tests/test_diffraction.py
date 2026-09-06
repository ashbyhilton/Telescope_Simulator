import math

import numpy as np
import pytest

from telescope_simulator.physics.diffraction import MAX_GRID_SIZE, psf_radial_profile


def _first_local_minimum_radius(radius_mm: np.ndarray, intensity: np.ndarray) -> float:
    d = np.diff(intensity)
    idx = np.where((d[:-1] < 0) & (d[1:] >= 0))[0]
    assert len(idx) > 0, "expected at least one local minimum (an Airy null) in the profile"
    return float(radius_mm[idx[0] + 1])


def _core_energy_fraction(result) -> float:
    """Fraction of the pattern's energy falling inside the first Airy null.

    Encircled energy (the profile weighted by 2*pi*r) rather than a
    peak-relative width: a badly defocused pattern is a broad ring structure
    whose profile dips below half its peak almost immediately, so any
    half-maximum measure reports it as *narrow*. This measure also survives
    the two runs being sampled on different grids, which the Nyquist
    refinement below makes unavoidable."""
    r = result.radius_mm_at_target
    weighted = result.intensity * r
    return float(np.sum(weighted[r <= result.airy_first_null_mm]) / np.sum(weighted))


def test_unaberrated_circular_pupil_matches_airy_first_null():
    # Independent textbook formula: an unaberrated circular aperture's
    # diffraction pattern has its first null at 1.22 * lambda * z / D.
    # Tolerance is one grid pitch, not two: the input pixel pitch is now
    # 2R/(n-1) matching linspace's endpoint-inclusive spacing (2R/n was a
    # systematic n/(n-1) stretch of the whole radius axis), and the profile
    # is a real azimuthal average rather than one noisy row.
    result = psf_radial_profile(
        coefficients_mm={}, pupil_radius_mm=5.0, wavelength_nm=632.8,
        distance_to_target_mm=2000.0, grid_size=256, pad_factor=4,
    )
    numeric_null = _first_local_minimum_radius(result.radius_mm_at_target, result.intensity)
    grid_pitch = result.radius_mm_at_target[1] - result.radius_mm_at_target[0]
    assert numeric_null == pytest.approx(result.airy_first_null_mm, abs=grid_pitch)


def test_defocus_broadens_the_central_peak():
    # A defocused pupil (Noll 4) must be less sharply concentrated than the
    # unaberrated case. 0.005mm is ~8 waves -- deliberately inside what a
    # 256-point pupil grid samples without aliasing, so both runs use the
    # same grid and the comparison is like for like.
    common = dict(pupil_radius_mm=5.0, wavelength_nm=632.8, distance_to_target_mm=2000.0,
                  grid_size=256, pad_factor=4)
    sharp = psf_radial_profile(coefficients_mm={}, **common)
    defocused = psf_radial_profile(coefficients_mm={4: 0.005}, **common)

    assert sharp.grid_size_used == defocused.grid_size_used == 256
    assert _core_energy_fraction(defocused) < _core_energy_fraction(sharp)


def test_steep_wavefront_refines_the_pupil_grid_instead_of_aliasing():
    """~32 waves of defocus needs a finer pupil grid than the 256-point
    default: past a phase step of pi between neighbouring samples the FFT
    wraps around silently, and a badly defocused pupil comes back looking
    near-diffraction-limited again."""
    result = psf_radial_profile(
        coefficients_mm={4: 0.02}, pupil_radius_mm=5.0, wavelength_nm=632.8,
        distance_to_target_mm=2000.0, grid_size=256, pad_factor=4,
    )
    assert result.grid_size_used > 256
    assert result.grid_size_used * result.pad_factor_used <= 1024  # FFT stays bounded

    # And the energy really has left the core, rather than the pattern
    # having wrapped back around into a narrow, deceptively
    # diffraction-limited-looking peak (the symptom of the aliasing).
    milder = psf_radial_profile(
        coefficients_mm={4: 0.005}, pupil_radius_mm=5.0, wavelength_nm=632.8,
        distance_to_target_mm=2000.0, grid_size=256, pad_factor=4,
    )
    assert _core_energy_fraction(result) < _core_energy_fraction(milder)


def test_wavefront_too_steep_to_sample_is_refused_rather_than_aliased():
    # Hundreds of waves of defocus -- routine for a target pinned well off
    # best focus. There is no honest PSF to draw at this point, and drawing
    # the aliased one is worse than saying so.
    with pytest.raises(ValueError, match="too large"):
        psf_radial_profile(
            coefficients_mm={4: 0.2}, pupil_radius_mm=5.0, wavelength_nm=632.8,
            distance_to_target_mm=2000.0, grid_size=256, pad_factor=4,
        )


def test_non_positive_propagation_distance_is_refused():
    # A target pinned at or in front of the exit plane: the Fraunhofer
    # relation has no distance to work over. Previously clamped to 1e-6mm,
    # which silently produced a meaningless profile.
    with pytest.raises(ValueError, match="exit plane"):
        psf_radial_profile(
            coefficients_mm={}, pupil_radius_mm=5.0, wavelength_nm=632.8,
            distance_to_target_mm=0.0,
        )


def test_profile_is_an_azimuthal_average_not_a_single_row():
    """The docstring promised an azimuthal average; the first cut sliced one
    row out of the FFT. The pupil is sampled on a square grid, so the output
    has only 4-fold symmetry and a single row carries the grid's sampling
    noise undiminished -- averaging the annulus is what removes it."""
    result = psf_radial_profile(
        coefficients_mm={}, pupil_radius_mm=5.0, wavelength_nm=632.8,
        distance_to_target_mm=2000.0, grid_size=128, pad_factor=4,
    )
    # An Airy pattern's successive maxima must decay monotonically. A single
    # row through a square-gridded FFT does not reliably do so; the annulus
    # average does.
    intensity = result.intensity
    d = np.diff(intensity)
    peak_idx = np.flatnonzero((d[:-1] > 0) & (d[1:] <= 0)) + 1
    peaks = intensity[peak_idx][:4]
    assert len(peaks) >= 3
    assert np.all(np.diff(peaks) < 0)


def test_grid_refinement_is_bounded_by_max_grid_size():
    # The refusal threshold and the grid cap must agree: anything accepted
    # must fit inside MAX_GRID_SIZE.
    result = psf_radial_profile(
        coefficients_mm={4: 0.04}, pupil_radius_mm=5.0, wavelength_nm=632.8,
        distance_to_target_mm=2000.0,
    )
    assert result.grid_size_used <= MAX_GRID_SIZE


def test_gaussian_apodized_pupil_matches_the_analytic_gaussian_far_field():
    """The bug this pins: the pupil used to be a uniform disk out to the
    *traced fan's* radius, which by default runs to 2.5 w. A Gaussian beam
    illuminating that disk is nothing like uniform, and the difference is not
    subtle -- the uniform-disk answer came out roughly half the true width,
    with Airy rings a Gaussian does not have.

    Independent closed form: a collimated Gaussian of 1/e^2 radius w has a
    far-field 1/e^2 radius of lambda*L/(pi*w) at distance L.
    """
    lam_nm, distance, pupil = 632.8, 2000.0, 5.0
    w_norm = 0.4  # i.e. the fan traced out to 2.5 w, the module default
    analytic = (lam_nm * 1e-6) * distance / (math.pi * w_norm * pupil)

    apodized = psf_radial_profile(
        coefficients_mm={}, pupil_radius_mm=pupil, wavelength_nm=lam_nm,
        distance_to_target_mm=distance, gaussian_w_norm=w_norm,
    )
    assert apodized.core_radius_mm == pytest.approx(analytic, rel=0.02)

    # A Gaussian pupil has no null, so nothing here should be reporting the
    # hard-aperture Airy radius as the spot size.
    assert apodized.core_radius_mm > apodized.airy_first_null_mm

    uniform = psf_radial_profile(
        coefficients_mm={}, pupil_radius_mm=pupil, wavelength_nm=lam_nm,
        distance_to_target_mm=distance,
    )
    assert uniform.core_radius_mm < 0.6 * analytic  # the size of the old error


def test_display_radius_frames_the_core_rather_than_the_whole_fft_window():
    """The FFT's radius array runs out to the full half-window, which for a
    typical project is ~100x the spot -- on a linear axis that draws the
    entire pattern as one pixel-wide spike at the origin."""
    result = psf_radial_profile(
        coefficients_mm={}, pupil_radius_mm=5.0, wavelength_nm=632.8,
        distance_to_target_mm=2000.0,
    )
    assert result.display_radius_mm >= 2.0 * result.airy_first_null_mm
    assert result.display_radius_mm < 0.2 * result.radius_mm_at_target[-1]


def test_azimuthal_bins_are_reported_at_their_mean_radius():
    """Binning by `rint(hypot(...))` puts pixels 1.0 and 1.414 pixels from
    the centre into the same annulus, whose mean radius is 1.21 -- so
    labelling that bin "1" reports a value sampled further out than it
    claims. On a PSF core that is a several-percent error growing toward the
    centre, and it draws as a too-tall, too-narrow spike on the axis.
    """
    lam_nm, distance, pupil, w_norm = 632.8, 2000.0, 5.0, 0.4
    result = psf_radial_profile(
        coefficients_mm={}, pupil_radius_mm=pupil, wavelength_nm=lam_nm,
        distance_to_target_mm=distance, gaussian_w_norm=w_norm,
    )
    r = result.radius_mm_at_target

    # The centre holds exactly one pixel, so it keeps radius 0 and the peak.
    assert r[0] == 0.0
    assert result.intensity[0] == pytest.approx(1.0)
    # The first annulus sits at ~1.21 pixels, not 1.0 -- i.e. the spacing is
    # not uniform, which is precisely the correction.
    pitch = r[2] - r[1]
    assert r[1] > 1.15 * pitch

    # With the radii honest, the core matches the analytic Gaussian far field
    # bin by bin instead of wobbling several percent.
    analytic = np.exp(-2.0 * r[:8] ** 2 / ((lam_nm * 1e-6) * distance / (math.pi * w_norm * pupil)) ** 2)
    assert np.allclose(result.intensity[:8] / analytic, 1.0, atol=0.02)
