import math

import numpy as np
import pytest

from telescope_simulator.physics.zernike import (
    fit_zernike_rotational,
    wavefront_polynomial,
    zernike_radial_m0,
)


def test_zernike_radial_m0_matches_known_boundary_values():
    # Standard Zernike normalization: R_n^m(1) = 1 for every valid (n, m),
    # and R_n^0(0) = (-1)^(n/2) -- independent textbook facts, not derived
    # from this module's own code.
    for n in (0, 2, 4, 6, 8):
        assert zernike_radial_m0(n, np.array([1.0]))[0] == pytest.approx(1.0)
        assert zernike_radial_m0(n, np.array([0.0]))[0] == pytest.approx((-1.0) ** (n // 2))


def test_fit_recovers_known_defocus_and_spherical_coefficients():
    pupil_radius_mm = 8.0
    rho = np.linspace(-pupil_radius_mm, pupil_radius_mm, 41)
    rho_norm = np.abs(rho) / pupil_radius_mm

    true_defocus = 0.0020  # mm
    true_spherical = -0.0006  # mm
    opd = true_defocus * zernike_radial_m0(2, rho_norm) + true_spherical * zernike_radial_m0(4, rho_norm)

    result = fit_zernike_rotational(rho.tolist(), opd.tolist(), pupil_radius_mm)

    assert result.coefficients_mm[4] == pytest.approx(true_defocus, abs=1e-9)
    assert result.coefficients_mm[11] == pytest.approx(true_spherical, abs=1e-9)
    assert result.coefficients_mm[1] == pytest.approx(0.0, abs=1e-9)
    assert result.coefficients_mm[22] == pytest.approx(0.0, abs=1e-9)
    assert result.coefficients_mm[37] == pytest.approx(0.0, abs=1e-9)
    assert result.residual_rms_mm == pytest.approx(0.0, abs=1e-9)  # the fit is exact


def test_fit_requires_enough_surviving_rays():
    with pytest.raises(ValueError):
        fit_zernike_rotational([0.0, 1.0], [0.0, 0.0], pupil_radius_mm=5.0)


def test_wavefront_polynomial_round_trips_through_a_fit():
    pupil_radius_mm = 5.0
    rho = np.linspace(-pupil_radius_mm, pupil_radius_mm, 25)
    rho_norm = np.abs(rho) / pupil_radius_mm
    opd = 0.001 * zernike_radial_m0(4, rho_norm)

    result = fit_zernike_rotational(rho.tolist(), opd.tolist(), pupil_radius_mm)
    reconstructed = wavefront_polynomial(result.coefficients_mm, rho_norm)

    assert np.allclose(reconstructed, opd, atol=1e-9)


def test_rms_wavefront_error_is_the_wavefront_not_the_fit_residual():
    """These are wildly different numbers and only one of them is what
    "RMS wavefront error" means. Five m=0 terms describe a smooth traced
    wavefront almost exactly, so the residual is ~1e-8 waves for a system
    with tens of waves of real error -- reporting it under that name said
    every system was perfect.

    Checked against a direct area-weighted integral of the same wavefront,
    which is the definition, rather than against the quadrature shortcut the
    implementation uses.
    """
    pupil_radius_mm = 8.0
    rho = np.linspace(-pupil_radius_mm, pupil_radius_mm, 41)
    rho_norm = np.abs(rho) / pupil_radius_mm
    coefficients = {4: 0.0020, 11: -0.0006}
    opd = sum(c * zernike_radial_m0(n, rho_norm)
              for c, n in ((coefficients[4], 2), (coefficients[11], 4)))

    result = fit_zernike_rotational(rho.tolist(), opd.tolist(), pupil_radius_mm)

    r = np.linspace(0.0, 1.0, 20001)
    w = wavefront_polynomial(result.coefficients_mm, r)
    mean = np.trapezoid(w * 2.0 * r, r)  # area weight over the unit disk
    mean_square = np.trapezoid(w * w * 2.0 * r, r)
    assert result.rms_mm == pytest.approx(math.sqrt(mean_square - mean**2), rel=1e-6)
    assert result.rms_mm > 1e5 * result.residual_rms_mm


def test_piston_does_not_count_toward_the_rms_wavefront_error():
    """A uniform phase offset is a reference shift, not an aberration -- and
    with the OPD referenced to the axial ray it is arbitrary anyway."""
    pupil_radius_mm = 5.0
    rho = np.linspace(-pupil_radius_mm, pupil_radius_mm, 41)
    rho_norm = np.abs(rho) / pupil_radius_mm
    opd = 0.001 * zernike_radial_m0(2, rho_norm)

    plain = fit_zernike_rotational(rho.tolist(), opd.tolist(), pupil_radius_mm)
    shifted = fit_zernike_rotational(rho.tolist(), (opd + 0.05).tolist(), pupil_radius_mm)

    assert shifted.coefficients_mm[1] == pytest.approx(0.05, abs=1e-9)
    assert shifted.rms_mm == pytest.approx(plain.rms_mm, rel=1e-9)
