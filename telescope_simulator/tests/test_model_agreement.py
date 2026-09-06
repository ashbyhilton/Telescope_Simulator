"""Cross-checks between the three independent ways this app computes a beam
size, on a system where all three must agree.

The Gaussian/ABCD model (physics/system.py), the geometric ray fan
(physics/raytrace.py -> physics/irradiance.py) and the Fraunhofer PSF
(physics/raytrace.py -> physics/zernike.py -> physics/diffraction.py) share
almost no code. Each module's own tests check it against its own closed form;
what these tests check is that the three answers are the *same physical
number* on a system slow enough that geometric and wave optics have to agree.

The system below is a weak (f/~19), thick biconvex singlet fed by a clean
collimated Gaussian: spherical aberration is small enough that the ray fan
and the Gaussian model describe the same beam, and the aperture is many beam
radii wide so nothing is clipped.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from telescope_simulator.model.beam_spec import InputBeamSpec
from telescope_simulator.model.optics import Optic
from telescope_simulator.physics.diffraction import psf_radial_profile
from telescope_simulator.physics.irradiance import transverse_intensity
from telescope_simulator.physics.raytrace import trace_fan, wavefront_at
from telescope_simulator.physics.system import OpticalSystem
from telescope_simulator.physics.zernike import fit_zernike_rotational

W_REF_MM = 2.0


def _system():
    beam = InputBeamSpec(z_ref=0.0, w_ref=W_REF_MM, collimated=True, wavelength_nm=632.8)
    lens = Optic(name="L", diameter_full=50.0, thickness_center=3.0,
                 r1=1000.0, r2=-1000.0, n=1.5168, z=50.0)
    return beam, [lens]


def _one_over_e_squared_radius(radius_mm: np.ndarray, intensity: np.ndarray) -> float:
    """Radius where a peak-normalized profile first falls to 1/e^2 -- the
    same definition of "beam radius" the Gaussian model uses, so the two are
    directly comparable."""
    below = np.flatnonzero(intensity < math.exp(-2.0))
    assert len(below) > 0, "profile never falls to 1/e^2 of its peak"
    return float(radius_mm[below[0]])


@pytest.mark.parametrize("target_z", [200.0, 500.0, 800.0, 1400.0, 2000.0])
def test_geometric_profile_width_matches_the_gaussian_model(target_z):
    """The card profile's 1/e^2 radius against w(z) from the ABCD model, on
    both sides of focus.

    This is what pins the profile's *normalization*, not just its shape: the
    radial power distribution 2*pi*r*I(r) has the same peak-normalized shape
    family but a completely different width, so an accidental factor of r in
    the binning shows up here as a systematic disagreement rather than as
    anything visibly wrong on the plot.
    """
    beam, optics = _system()
    gaussian = OpticalSystem(beam, optics).propagate().segments[-1].beam

    card = transverse_intensity(beam, optics, target_z=target_z, ray_count=1201, bin_count=200)
    geometric_w = _one_over_e_squared_radius(card.radius_mm, card.intensity_radial)

    assert geometric_w == pytest.approx(gaussian.w(target_z), rel=0.03)


def test_psf_core_at_focus_reproduces_the_gaussian_waist():
    """Ray trace -> Zernike fit -> Fraunhofer FFT, ending at the same waist
    radius the ABCD model gets analytically.

    The bug this pins is worth stating: the pupil was a *uniform* disk out to
    the traced fan's radius, and trace_fan deliberately runs the fan out to
    2.5 w so the wavefront is sampled past the useful beam. Treating that
    whole disk as filled is a 2.5x-too-wide aperture, and it reported a waist
    roughly half the true one -- with Airy rings that a clean Gaussian beam
    does not have. Carrying the beam's own Gaussian illumination into the
    pupil is what makes the two models agree.
    """
    beam, optics = _system()
    gaussian = OpticalSystem(beam, optics).propagate().segments[-1].beam
    focus_z = gaussian.z_waist

    fan = trace_fan(beam, optics, ray_count=21)
    sample = wavefront_at(fan, focus_z)
    fit = fit_zernike_rotational(sample.rho_mm, sample.opd_mm, sample.pupil_radius_mm)
    common = dict(
        coefficients_mm=fit.coefficients_mm,
        pupil_radius_mm=sample.exit_pupil_radius_mm,
        wavelength_nm=fan.wavelength_nm,
        distance_to_target_mm=focus_z - sample.exit_pupil_z,
    )

    apodized = psf_radial_profile(gaussian_w_norm=W_REF_MM / fit.pupil_radius_mm, **common)
    assert apodized.core_radius_mm == pytest.approx(gaussian.w0, rel=0.02)

    uniform = psf_radial_profile(**common)
    assert uniform.core_radius_mm < 0.7 * gaussian.w0  # the size of the old error


def _psf_at(beam, optics, target_z):
    fan = trace_fan(beam, optics, ray_count=41)
    sample = wavefront_at(fan, target_z)
    fit = fit_zernike_rotational(sample.rho_mm, sample.opd_mm, sample.pupil_radius_mm)
    return psf_radial_profile(
        fit.coefficients_mm, sample.exit_pupil_radius_mm, fan.wavelength_nm,
        target_z - sample.exit_pupil_z,
        gaussian_w_norm=W_REF_MM / fit.pupil_radius_mm,
    )


@pytest.mark.parametrize("rayleigh_ranges", [0.0, 1.0, 3.0, 5.0, 10.0, 20.0])
def test_psf_tracks_the_gaussian_model_all_the_way_out_of_focus(rayleigh_ranges):
    """The reference-sphere bug this pins was invisible at focus and grew
    steadily with defocus -- a factor of two too wide by ten Rayleigh ranges,
    and still drawing a perfectly plausible-looking pattern the whole way.

    The wavefront was referenced to the target *plane* rather than to a
    sphere centred on the target point. Those agree exactly at focus (the
    rays are all at r = 0 there), which is precisely why a single
    at-focus check passed and hid it. See wavefront_at()'s docstring.
    """
    beam, optics = _system()
    gaussian = OpticalSystem(beam, optics).propagate().segments[-1].beam
    target_z = gaussian.z_waist + rayleigh_ranges * gaussian.rayleigh_range

    psf = _psf_at(beam, optics, target_z)
    assert psf.core_radius_mm == pytest.approx(gaussian.w(target_z), rel=0.02)


def test_the_two_profiles_meet_once_geometry_has_caught_up():
    """Where the handover between the two plots actually is.

    Far from focus geometric optics is the physical answer and the PSF must
    agree with it. Near focus it is not: a ray cone grows linearly with
    distance while a real beam grows as sqrt(1 + (z/zR)^2), so at three
    Rayleigh ranges the geometric profile is a few percent narrow *by
    construction*. Asserting agreement there would be asserting a bug into
    place, so this pins both halves: the gap near focus, and its closing
    further out.
    """
    beam, optics = _system()
    gaussian = OpticalSystem(beam, optics).propagate().segments[-1].beam

    def geometric_w(target_z):
        card = transverse_intensity(beam, optics, target_z=target_z, ray_count=1201, bin_count=200)
        return _one_over_e_squared_radius(card.radius_mm, card.intensity_radial)

    near = gaussian.z_waist + 3.0 * gaussian.rayleigh_range
    far = gaussian.z_waist + 20.0 * gaussian.rayleigh_range

    # Near: geometric is low, and low by about the amount the cone-versus-
    # hyperbola difference predicts (3 / sqrt(10) = 0.949).
    assert geometric_w(near) / gaussian.w(near) == pytest.approx(3.0 / math.sqrt(10.0), rel=0.02)

    # Far: the two independent calculations land on the same number.
    assert geometric_w(far) == pytest.approx(_psf_at(beam, optics, far).core_radius_mm, rel=0.03)
