import numpy as np
import pytest

from telescope_simulator.physics.beam import GaussianBeam


def test_collimated_measurement_is_at_the_waist():
    beam = GaussianBeam.from_measurement(z_ref=10.0, w_ref=0.5, wavelength_nm=632.8, n=1.0, r_ref=None)
    assert np.isclose(beam.z_waist, 10.0)
    assert np.isclose(beam.w0, 0.5)


def test_w_of_z_matches_standard_formula():
    beam = GaussianBeam.from_measurement(z_ref=0.0, w_ref=0.4, wavelength_nm=1064.0, n=1.0, r_ref=None)
    zR = beam.rayleigh_range
    for z in (-30.0, -5.0, 0.0, 17.0, 250.0):
        expected = beam.w0 * np.sqrt(1.0 + (z / zR) ** 2)
        assert np.isclose(beam.w(z), expected, rtol=1e-9)


def test_arbitrary_input_plane_recovers_known_waist():
    # Build a beam analytically from a known waist, sample it off-waist,
    # then confirm from_measurement() back-calculates the same waist.
    w0_true = 0.3
    z_waist_true = 5.0
    wavelength_nm = 1064.0
    zR = np.pi * w0_true**2 / (wavelength_nm * 1e-6)

    d = 20.0  # distance from waist to the measurement plane
    z_ref = z_waist_true + d
    w_ref = w0_true * np.sqrt(1.0 + (d / zR) ** 2)
    r_ref = d * (1.0 + (zR / d) ** 2)

    beam = GaussianBeam.from_measurement(z_ref=z_ref, w_ref=w_ref, wavelength_nm=wavelength_nm, n=1.0, r_ref=r_ref)

    assert np.isclose(beam.z_waist, z_waist_true, atol=1e-9)
    assert np.isclose(beam.w0, w0_true, rtol=1e-9)
    assert np.isclose(beam.rayleigh_range, zR, rtol=1e-9)
    assert np.isclose(beam.w(z_ref), w_ref, rtol=1e-9)
    assert np.isclose(beam.radius_of_curvature(z_ref), r_ref, rtol=1e-9)


def test_divergence_half_angle_far_field():
    beam = GaussianBeam.from_measurement(z_ref=0.0, w_ref=0.2, wavelength_nm=632.8, n=1.0, r_ref=None)
    expected = (632.8e-6) / (np.pi * 0.2)
    assert np.isclose(beam.divergence_half_angle, expected, rtol=1e-9)


def test_zero_r_ref_raises_clear_value_error_not_zero_division_error():
    # r_ref=0.0 is a mathematical singularity (a zero-radius wavefront has no
    # physical meaning) -- must fail loudly and specifically at the source,
    # same precedent as physics/matrices.interface()'s radius==0 check, not
    # leak a bare ZeroDivisionError that callers won't be catching.
    with pytest.raises(ValueError):
        GaussianBeam.from_measurement(z_ref=0.0, w_ref=0.5, wavelength_nm=632.8, n=1.0, r_ref=0.0)
