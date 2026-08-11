import numpy as np

from telescope_simulator.model.beam_spec import InputBeamSpec
from telescope_simulator.model.optics import Optic
from telescope_simulator.physics.system import OpticalSystem


def test_no_optics_passes_beam_through_unchanged():
    beam_spec = InputBeamSpec(wavelength_nm=632.8, z_ref=0.0, w_ref=0.5, collimated=True)
    result = OpticalSystem(beam_spec, optics=[]).propagate(trailing_length=1000.0)

    assert np.isclose(result.next_waist_z, 0.0)
    assert np.isclose(result.next_waist_diameter, 1.0)
    expected_zR = np.pi * 0.5**2 / (632.8e-6)
    assert np.isclose(result.output_rayleigh_range, expected_zR, rtol=1e-9)


def test_thin_lens_focusing_matches_self_1983_formula():
    # Self, "Focusing of spherical Gaussian beams," Applied Optics 22, 658 (1983):
    # for a thin lens of focal length f with the input waist a distance s in
    # front of it, M = f / sqrt((s-f)^2 + zR^2), w0' = M*w0,
    # s' = f + M^2*(s-f), zR' = M^2*zR (s' measured from the lens).
    wavelength_nm = 632.8
    w0 = 1.0
    zR = np.pi * w0**2 / (wavelength_nm * 1e-6)

    s = 50.0  # lens position (waist is at z=0)
    f = 100.0  # symmetric biconvex, n=1.5, r1=100, r2=-100 -> f=100mm exactly (thin limit)

    lens = Optic(name="L1", diameter_full=25.4, thickness_center=1e-4, r1=100.0, r2=-100.0, n=1.5, z=s)
    beam_spec = InputBeamSpec(wavelength_nm=wavelength_nm, z_ref=0.0, w_ref=w0, collimated=True)

    result = OpticalSystem(beam_spec, optics=[lens]).propagate(trailing_length=2000.0)

    M = f / np.sqrt((s - f) ** 2 + zR**2)
    w0_expected = M * w0
    s_prime_expected = f + M**2 * (s - f)
    zR_expected = M**2 * zR
    waist_z_expected = s + s_prime_expected

    assert np.isclose(result.next_waist_diameter, 2.0 * w0_expected, rtol=1e-3)
    assert np.isclose(result.output_rayleigh_range, zR_expected, rtol=1e-3)
    assert np.isclose(result.next_waist_z, waist_z_expected, atol=1e-2)


def test_optics_must_not_overlap_or_precede_beam():
    lens_a = Optic(name="A", z=10.0, thickness_center=5.0, r1=float("inf"), r2=float("inf"))
    lens_b = Optic(name="B", z=12.0, thickness_center=5.0, r1=float("inf"), r2=float("inf"))
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=True)

    try:
        OpticalSystem(beam_spec, optics=[lens_a, lens_b]).propagate()
        assert False, "expected ValueError for overlapping optics"
    except ValueError:
        pass
