import math

import numpy as np
import pytest

from telescope_simulator.model.beam_spec import InputBeamSpec
from telescope_simulator.model.optics import Optic
from telescope_simulator.physics.irradiance import transverse_intensity


def test_collimated_beam_with_no_optics_reproduces_its_own_gaussian_profile():
    """With nothing to bend the rays, every ray arrives at the height it
    launched from, so the profile on a card must be the input beam's own
    Gaussian irradiance -- an independent closed form to check the
    weighting/annulus-area bookkeeping against, not a self-consistency
    check."""
    w0 = 2.0
    beam = InputBeamSpec(z_ref=0.0, w_ref=w0, collimated=True)

    result = transverse_intensity(beam, [], target_z=100.0, ray_count=2001, bin_count=60)

    r = result.radius_mm
    expected = np.exp(-2.0 * r**2 / w0**2)
    expected = expected / expected.max()
    # radius_mm is bin *centres*, which is where the analytic value belongs,
    # so this is a like-for-like comparison rather than one carrying half a
    # bin of systematic offset.
    assert np.allclose(result.intensity_radial, expected, atol=0.03)


def test_irradiance_divides_by_annulus_area_not_bin_width():
    """The bug this guards: dividing binned power by bin *width* makes every
    profile rise toward its outer edge, because an outer annulus collects
    from far more area than an inner one of the same width. A uniformly
    illuminated, unbent fan is the clean case -- its irradiance must come out
    flat."""
    beam = InputBeamSpec(z_ref=0.0, w_ref=1.0e6, collimated=True)  # ~uniform over the fan
    result = transverse_intensity(
        beam, [], target_z=50.0, ray_count=4001, bin_count=40, pupil_radius_mm=10.0,
    )

    # Ignore the innermost bin, which only a handful of rays reach.
    interior = result.intensity_radial[2:]
    assert interior.max() - interior.min() < 0.05
    assert result.spot_radius_mm == pytest.approx(10.0)


def test_vignetted_rays_never_arrive_so_the_spot_is_clipped():
    stop = Optic(name="Stop", diameter_full=4.0, thickness_center=2.0,
                 r1=float("inf"), r2=float("inf"), n=1.5, z=20.0)
    beam = InputBeamSpec(z_ref=0.0, w_ref=4.0, collimated=True)

    result = transverse_intensity(
        beam, [stop], target_z=60.0, ray_count=401, pupil_radius_mm=10.0,
    )

    assert result.n_arriving < result.n_total
    assert result.spot_radius_mm == pytest.approx(2.0, abs=0.05)  # the stop's half-aperture


def test_focusing_lens_concentrates_the_profile_toward_its_focus():
    lens = Optic(name="L1", diameter_full=25.4, thickness_center=4.0,
                 r1=50.0, r2=-50.0, n=1.5168, z=100.0)
    beam = InputBeamSpec(z_ref=0.0, w_ref=3.0, collimated=True)

    near = transverse_intensity(beam, [lens], target_z=110.0, ray_count=801)
    focal = transverse_intensity(beam, [lens], target_z=150.0, ray_count=801)

    assert focal.encircled_50_mm < near.encircled_50_mm
    assert focal.spot_radius_mm < near.spot_radius_mm


def test_profile_is_normalized_and_finite():
    lens = Optic(name="L1", diameter_full=25.4, thickness_center=4.0,
                 r1=50.0, r2=-50.0, n=1.5168, z=100.0)
    beam = InputBeamSpec(z_ref=0.0, w_ref=3.0, collimated=True)

    result = transverse_intensity(beam, [lens], target_z=200.0, ray_count=801)

    assert np.all(np.isfinite(result.intensity))
    assert result.intensity.max() == pytest.approx(1.0)
    assert result.intensity.min() >= 0.0
    assert len(result.radius_mm) == len(result.intensity_radial)
    assert len(result.x_mm) == len(result.intensity) == 2 * len(result.radius_mm)


def test_a_stop_that_passes_only_the_axial_ray_is_reported_as_such():
    """Not the same failure as "everything converged to a point", though both
    end with a zero-width spot: here the aperture has blocked everything
    except the one ray that by construction carries no power. Reporting focus
    would point the user at entirely the wrong control."""
    stop = Optic(name="Blocked", diameter_full=0.002, thickness_center=2.0,
                 r1=float("inf"), r2=float("inf"), n=1.5, z=20.0)
    beam = InputBeamSpec(z_ref=0.0, w_ref=5.0, collimated=True)

    with pytest.raises(ValueError, match="no light reaches"):
        transverse_intensity(beam, [stop], target_z=60.0, ray_count=51, pupil_radius_mm=10.0)


def test_axial_ray_carries_the_power_of_the_disc_it_represents():
    """The `|rho|` weight is right for every ray except the axial one.

    Every off-axis ray shares its annulus with its partner at `-rho`, so
    `I*|rho|` is its share. The axial ray has no partner: it stands for the
    central *disc* of radius `drho/2`, whose power is not zero. Weighting it
    as a zero-radius annulus drops that disc entirely, and the innermost bin
    comes out low by roughly `(drho/2 / bin width)^2` -- which draws as a
    dimple sitting exactly on the axis of every spot.

    A uniformly illuminated fan is the clean case: its irradiance must be
    flat right through the centre bin, neither dimpled nor spiked.
    """
    beam = InputBeamSpec(z_ref=0.0, w_ref=1.0e6, collimated=True)
    result = transverse_intensity(
        beam, [], target_z=10.0, ray_count=401, bin_count=120, pupil_radius_mm=10.0,
    )

    assert math.isfinite(result.intensity_radial[0])
    interior_mean = float(np.mean(result.intensity_radial[1:100]))
    assert result.intensity_radial[0] == pytest.approx(interior_mean, rel=0.01)


def test_no_dimple_or_spike_where_the_plot_crosses_the_axis():
    """The artifact this pins was plainly visible: a 15% notch at x = 0 in
    every profile.

    Two causes, and the second was masking the first. The kernel spread each
    ray's power evenly in radius rather than in proportion to it, which
    shifts a near-axis ray's deposit outward by about `sigma^2/mu` -- a whole
    bin for the rays closest to the axis; and the axial ray was given zero
    power (see above). Checked against the analytic Gaussian rather than
    against the profile's own smoothness, so a scheme that is smooth and
    wrong cannot pass.
    """
    w0 = 2.0
    beam = InputBeamSpec(z_ref=0.0, w_ref=w0, collimated=True)
    result = transverse_intensity(beam, [], target_z=100.0, ray_count=401, bin_count=120)

    r, intensity = result.radius_mm, result.intensity_radial
    analytic = np.exp(-2.0 * r**2 / w0**2)
    scale = float(np.median(intensity[1:40] / analytic[1:40]))
    # Every one of the innermost bins, not just the profile as a whole: a
    # notch is a single-bin defect that a whole-profile tolerance hides.
    assert np.allclose(intensity[:8] / (scale * analytic[:8]), 1.0, atol=0.01)

    # ...and the full slice really is single-peaked across x = 0, with no
    # step at the join between the two mirrored halves.
    x, slice_i = result.x_mm, result.intensity
    mid = len(slice_i) // 2
    step = abs(slice_i[mid] - slice_i[mid - 1])
    typical = float(np.median(np.abs(np.diff(slice_i))))
    assert step <= 2.0 * typical


def _energy_fraction_inside(result, radius_mm: float) -> float:
    """Fraction of the profile's power inside `radius_mm`, integrating the
    irradiance over annulus area rather than over radius."""
    centres = result.radius_mm
    half_width = 0.5 * (centres[1] - centres[0])
    edges = np.concatenate(([0.0], centres + half_width))
    area = np.pi * (edges[1:] ** 2 - edges[:-1] ** 2)
    power = result.intensity_radial * area
    return float(power[centres <= radius_mm].sum() / power.sum())


def test_giving_rays_a_width_smooths_a_sparse_fan_instead_of_spiking():
    """With fewer rays than bins, depositing each ray at a single radius
    leaves most bins empty and the plot becomes a row of spikes -- an
    artifact of the ray count, not of the optics. Each ray is instead spread
    over the width of the tube it stands for."""
    lens = Optic(name="L1", diameter_full=25.4, thickness_center=4.0,
                 r1=50.0, r2=-50.0, n=1.5168, z=100.0)
    beam = InputBeamSpec(z_ref=0.0, w_ref=3.0, collimated=True)
    common = dict(target_z=250.0, ray_count=41, bin_count=120)

    spiky = transverse_intensity(beam, [lens], smoothing=0.0, **common)
    smooth = transverse_intensity(beam, [lens], smoothing=1.0, **common)

    inside = smooth.radius_mm <= smooth.spot_radius_mm
    assert np.count_nonzero(spiky.intensity_radial[inside] == 0.0) > 40  # mostly gaps
    assert np.count_nonzero(smooth.intensity_radial[inside] == 0.0) == 0

    # ...and the result is genuinely smoother, not merely non-zero.
    assert (np.abs(np.diff(smooth.intensity_radial)).max()
            < np.abs(np.diff(spiky.intensity_radial)).max())


def test_giving_rays_a_width_moves_energy_around_without_creating_any():
    """The whole point of normalizing each ray's kernel is that widening it
    redistributes power rather than inventing or losing it, so the energy
    distribution is left essentially unchanged for an already-smooth beam."""
    lens = Optic(name="L1", diameter_full=25.4, thickness_center=4.0,
                 r1=50.0, r2=-50.0, n=1.5168, z=100.0)
    beam = InputBeamSpec(z_ref=0.0, w_ref=3.0, collimated=True)
    common = dict(target_z=250.0, ray_count=801, bin_count=120)

    unsmoothed = transverse_intensity(beam, [lens], smoothing=0.0, **common)
    smoothed = transverse_intensity(beam, [lens], smoothing=1.0, **common)

    half = 0.5 * unsmoothed.spot_radius_mm
    assert _energy_fraction_inside(smoothed, half) == pytest.approx(
        _energy_fraction_inside(unsmoothed, half), abs=0.02
    )
    assert smoothed.encircled_50_mm == pytest.approx(unsmoothed.encircled_50_mm, rel=0.05)


def test_kernel_narrower_than_a_bin_still_lands_the_right_power():
    """The kernel is integrated over each bin in closed form rather than
    point-sampled at bin centres, so a tube far narrower than a bin -- the
    normal case with a dense fan -- reduces cleanly to the plain histogram
    instead of picking up a normalization error that a point sample would."""
    w0 = 2.0
    beam = InputBeamSpec(z_ref=0.0, w_ref=w0, collimated=True)

    # 4001 rays into 30 bins: every tube is orders of magnitude narrower than
    # a bin, so the answer must still be the input beam's own Gaussian.
    result = transverse_intensity(beam, [], target_z=100.0, ray_count=4001, bin_count=30)

    expected = np.exp(-2.0 * result.radius_mm**2 / w0**2)
    expected = expected / expected.max()
    assert np.allclose(result.intensity_radial, expected, atol=0.03)


def test_slice_is_irradiance_not_the_radial_power_distribution():
    """The distinction the plot lives or dies on: I(x, 0) is power per unit
    *area*, while 2*pi*r*I(r) is power per unit radius. They differ by
    exactly 2*pi*r, and the second is zero on axis and peaks in a ring even
    for an ordinary Gaussian spot -- so getting it wrong does not look like a
    scaling error, it looks like a doughnut.

    An unbent Gaussian beam is the case with a closed form for both, so this
    pins which of the two the module returns."""
    w0 = 2.0
    beam = InputBeamSpec(z_ref=0.0, w_ref=w0, collimated=True)
    result = transverse_intensity(beam, [], target_z=100.0, ray_count=2001, bin_count=60)

    irradiance = np.exp(-2.0 * result.radius_mm**2 / w0**2)
    irradiance = irradiance / irradiance.max()
    radial_power = 2.0 * np.pi * result.radius_mm * irradiance
    radial_power = radial_power / radial_power.max()

    assert np.allclose(result.intensity_radial, irradiance, atol=0.03)
    assert not np.allclose(result.intensity_radial, radial_power, atol=0.2)
    # The peak is on axis, where a 2*pi*r-weighted profile would be zero.
    assert result.intensity_radial[0] > 0.9


def test_full_slice_is_symmetric_about_the_axis_and_signed():
    """A card shows both sides of the axis. Rotational symmetry makes the
    negative half redundant physically, but reading a spot's width off a
    one-sided plot is where factor-of-two mistakes come from."""
    lens = Optic(name="L1", diameter_full=25.4, thickness_center=4.0,
                 r1=50.0, r2=-50.0, n=1.5168, z=100.0)
    beam = InputBeamSpec(z_ref=0.0, w_ref=3.0, collimated=True)

    result = transverse_intensity(beam, [lens], target_z=250.0, ray_count=401)

    assert result.x_mm[0] < 0.0 < result.x_mm[-1]
    assert np.all(np.diff(result.x_mm) > 0.0)  # monotonic, plottable as-is
    assert result.x_mm[0] == pytest.approx(-result.x_mm[-1])
    assert np.allclose(result.intensity, result.intensity[::-1])
