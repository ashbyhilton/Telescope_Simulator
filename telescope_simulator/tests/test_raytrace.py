import math

import numpy as np
import pytest

from telescope_simulator.model.beam_spec import InputBeamSpec
from telescope_simulator.model.optics import Optic
from telescope_simulator.physics.matrices import thick_lens
from telescope_simulator.physics.raytrace import (
    _intersect_surface,
    trace_fan,
    trace_ray,
    wavefront_at,
)
from telescope_simulator.physics.system import OpticalSystem


def _axis_crossing_z(path):
    """Where the ray's final (trailing) segment crosses r=0 -- used only by
    tests, as the geometric-ray analog of the ABCD system's back focal
    length, to check against an independent formula."""
    seg = path.segments[-1]
    dz, dr = seg.direction
    if abs(dr) < 1e-15:
        return None
    t = -seg.r0 / dr
    return seg.z0 + t * dz


def test_near_paraxial_ray_matches_thick_lens_back_focal_length():
    # A ray launched at a tiny height, parallel to the axis (collimated
    # input), through a real spherical lens must cross the axis at the same
    # back focal distance the tested ABCD thick-lens matrix predicts
    # (BFL = -A/C, per README's "ABCD ray-transfer matrices" note) -- an
    # independent check against already-validated code, not a
    # self-consistency check against this module's own geometry.
    lens = Optic(name="L1", diameter_full=25.4, thickness_center=4.0, r1=50.0, r2=-50.0, n=1.5168, z=100.0)
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=True)

    tiny_h = 1e-5
    path = trace_ray(tiny_h, beam_spec, [lens], ambient_index=1.0)
    assert path.status == "ok"
    crossing = _axis_crossing_z(path)

    m = thick_lens(lens.thickness_center, lens.n, lens.r1, lens.r2)
    bfl = -m[0, 0] / m[1, 0]
    z_back_vertex = lens.z + lens.thickness_center
    assert crossing == pytest.approx(z_back_vertex + bfl, rel=1e-4)


def test_ray_beyond_clear_aperture_is_vignetted_at_optic_z():
    lens = Optic(name="Small", diameter_full=2.0, thickness_center=4.0, r1=50.0, r2=-50.0, n=1.5, z=100.0)
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=True)

    path = trace_ray(5.0, beam_spec, [lens], ambient_index=1.0)  # well past the 1mm half-aperture

    assert path.status == "vignetted"
    assert path.stop_z == pytest.approx(lens.z)


def test_total_internal_reflection_is_detected_and_stops_the_ray():
    # A steep, strongly converging back surface on a high-index element: pick
    # a ray angle/geometry engineered to exceed the critical angle
    # asin(n2/n1) at the back (glass -> air) surface.
    n_glass = 1.9
    r2 = -10.0  # short radius (but > the 9mm launch height) -> steep surface
    # thickness_center must be large enough that the back surface's edge sag
    # doesn't push it in front of the flat front surface (a self-intersecting,
    # physically invalid lens) at the 9mm launch height used below.
    lens = Optic(name="Steep", diameter_full=25.4, thickness_center=8.0, r1=float("inf"), r2=r2, n=n_glass, z=50.0)
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=True)

    critical_angle = math.asin(1.0 / n_glass)

    path = trace_ray(9.0, beam_spec, [lens], ambient_index=1.0)

    assert path.status == "tir"
    assert path.stop_label == "Steep"
    # Sanity: the incidence angle implied by hitting height 9mm on a 6mm-ROC
    # surface indeed exceeds the critical angle (confirms the test case is
    # actually exercising TIR, not something else going wrong upstream).
    approx_incidence = math.asin(min(1.0, 9.0 / abs(r2)))
    assert approx_incidence > critical_angle


def test_wavefront_is_symmetric_about_the_axis():
    # No tilt/decenter anywhere in this app -- the system is rotationally
    # symmetric, so a ray launched at +h and one launched at -h must reach
    # the same optical path length at any downstream plane.
    lens = Optic(name="L1", diameter_full=25.4, thickness_center=4.0, r1=30.0, r2=-30.0, n=1.6, z=50.0)
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=1.0, collimated=True)
    fan = trace_fan(beam_spec, [lens], ambient_index=1.0, ray_count=11, pupil_radius_mm=8.0)

    sample = wavefront_at(fan, target_z=200.0)
    by_rho = dict(zip(sample.rho_mm, sample.opd_mm))
    for rho in sample.rho_mm:
        if rho > 0 and -rho in by_rho:
            assert by_rho[rho] == pytest.approx(by_rho[-rho], abs=1e-9)


def test_axial_ray_has_zero_wavefront_error_by_construction():
    lens = Optic(name="L1", diameter_full=25.4, thickness_center=4.0, r1=30.0, r2=-30.0, n=1.6, z=50.0)
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=1.0, collimated=True)
    fan = trace_fan(beam_spec, [lens], ambient_index=1.0, ray_count=9, pupil_radius_mm=8.0)

    sample = wavefront_at(fan, target_z=150.0)
    axial_index = sample.rho_mm.index(min(sample.rho_mm, key=abs))
    assert sample.opd_mm[axial_index] == pytest.approx(0.0, abs=1e-12)


def test_zero_radius_raises_instead_of_dividing_by_zero():
    # A momentary r1/r2 == 0.0 (e.g. a GUI spin box mid-edit) must fail
    # loudly and catchably here too -- same precedent as
    # physics.matrices.interface()'s identical check. Left unguarded, this
    # degrades into an opaque ZeroDivisionError inside _surface_normal
    # instead (the actual bug reported against v2.0's first cut).
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=True)
    bad_front = Optic(name="BadFront", diameter_full=25.4, thickness_center=4.0, r1=0.0, r2=-50.0, n=1.5, z=50.0)
    bad_back = Optic(name="BadBack", diameter_full=25.4, thickness_center=4.0, r1=50.0, r2=0.0, n=1.5, z=50.0)

    with pytest.raises(ValueError):
        trace_ray(1.0, beam_spec, [bad_front], ambient_index=1.0)
    with pytest.raises(ValueError):
        trace_ray(1.0, beam_spec, [bad_back], ambient_index=1.0)


def test_no_optics_all_rays_survive_and_diverge_from_a_diverging_beam():
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=False, r_ref=100.0)
    fan = trace_fan(beam_spec, [], ambient_index=1.0, ray_count=5, pupil_radius_mm=1.0)
    for path in fan.paths:
        assert path.status == "ok"
        assert path.reaches(500.0)


def test_negative_radius_surface_is_hit_at_its_vertex_not_the_phantom_hemisphere():
    """A surface is only the cap of its sphere that contains the vertex. For
    R < 0 that sphere spans [vertex - 2|R|, vertex], so simply taking the
    nearest forward root -- correct for R > 0 -- lands on the phantom rear
    hemisphere for any ray starting more than 2|R| upstream, refracting up to
    2|R| in front of the glass."""
    hit = _intersect_surface(0.0, 1.0, (1.0, 0.0), vertex_z=200.0, radius=-50.0)
    assert hit is not None
    assert hit[0] == pytest.approx(200.0, abs=0.02)  # not ~100, the far side of the sphere

    # The R > 0 case, which the nearest-root rule already got right, must not
    # have regressed.
    hit_positive = _intersect_surface(0.0, 1.0, (1.0, 0.0), vertex_z=200.0, radius=50.0)
    assert hit_positive is not None
    assert hit_positive[0] == pytest.approx(200.0, abs=0.02)


def test_plano_concave_lens_diverges_a_collimated_ray():
    # End-to-end consequence of the hemisphere bug: traced through the
    # phantom rear hemisphere, this lens *converged* the beam instead.
    lens = Optic(name="PlanoConcave", diameter_full=20.0, thickness_center=2.0,
                 r1=-12.4, r2=float("inf"), n=1.5, z=200.0)
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=True)

    path = trace_ray(2.0, beam_spec, [lens], ambient_index=1.0)

    assert path.status == "ok"
    # The front surface must be met at its vertex plane, not ~25mm upstream.
    first_hit_z = path.segments[0].z1
    assert first_hit_z == pytest.approx(200.0, abs=1.0)
    # Concave front on a positive launch height -> the ray must bend away
    # from the axis, i.e. r keeps growing downstream.
    assert path.segments[-1].direction[1] > 0.0
    assert path.r_at(400.0) > 2.0


def test_zero_thickness_optic_reports_the_geometry_not_a_vignetting_symptom():
    # thickness_spin's minimum is 0.0, so this is reachable from the GUI.
    # Every ray (the axial one included) fails to find the back surface, and
    # the old message blamed the axial ray rather than the lens.
    lens = Optic(name="Flat", diameter_full=25.4, thickness_center=0.0, r1=50.0, r2=-50.0, n=1.5, z=50.0)
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=True)

    with pytest.raises(ValueError, match="center thickness"):
        trace_ray(1.0, beam_spec, [lens], ambient_index=1.0)


def test_zero_wavefront_radius_raises_valueerror_not_zerodivisionerror():
    # The Beam tab's spin box repairs 0 on entry, but InputBeamSpec.from_dict
    # does not -- a hand-edited or older project file reaches the tracer with
    # r_ref == 0.0, and MainWindow only catches ValueError.
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=False, r_ref=0.0)

    with pytest.raises(ValueError, match="radius of curvature"):
        trace_ray(1.0, beam_spec, [], ambient_index=1.0)


def test_even_ray_count_is_rounded_up_so_the_axial_ray_is_always_traced():
    # The Config spin box steps by 2 but still accepts a typed even value,
    # and wavefront_at() references every OPD to the rho = 0 ray.
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=True)
    fan = trace_fan(beam_spec, [], ambient_index=1.0, ray_count=20, pupil_radius_mm=5.0)

    assert len(fan.paths) == 21
    assert any(p.r_launch == pytest.approx(0.0, abs=1e-12) for p in fan.paths)


def test_vignetted_fan_reports_the_surviving_pupil_not_the_launched_one():
    """A downstream stop cuts the bundle down; the wavefront samples then
    only cover the surviving radii, so that -- not the fan's launched
    half-width -- is what a Zernike fit may normalize by and what the PSF may
    diffract from."""
    big = Optic(name="Big", diameter_full=50.0, thickness_center=2.0,
                r1=float("inf"), r2=float("inf"), n=1.5, z=10.0)
    stop = Optic(name="Stop", diameter_full=4.0, thickness_center=2.0,
                 r1=float("inf"), r2=float("inf"), n=1.5, z=50.0)
    beam_spec = InputBeamSpec(z_ref=0.0, w_ref=0.5, collimated=True)

    fan = trace_fan(beam_spec, [big, stop], ambient_index=1.0, ray_count=21, pupil_radius_mm=10.0)
    sample = wavefront_at(fan, target_z=100.0)

    assert fan.pupil_radius_mm == 10.0  # what was launched
    assert sample.n_surviving < sample.n_total
    assert sample.pupil_radius_mm == pytest.approx(2.0)  # what survived
    assert sample.exit_pupil_z == pytest.approx(52.0)  # the last optic's back vertex
    assert sample.exit_pupil_radius_mm == pytest.approx(2.0, abs=1e-9)


def _cemented_doublet(spacing_mm: float = 0.0):
    """Crown + flint sharing an interface radius, laid out the way
    model.optics.layout_group_z lays out a composite group."""
    crown = Optic(name="Crown", diameter_full=25.4, thickness_center=6.0,
                  r1=60.0, r2=-40.0, n=1.5168, z=50.0, group_id=1, group_name="Doublet")
    flint = Optic(name="Flint", diameter_full=25.4, thickness_center=3.0,
                  r1=-40.0, r2=200.0, n=1.6200,
                  z=50.0 + 6.0 + spacing_mm, group_id=1, group_name="Doublet")
    return [crown, flint]


def test_zero_spacing_elements_trace_through_instead_of_stopping_at_the_joint():
    """A composite lens with zero spacing between its elements: the previous
    element's back surface and the next one's front surface are then the
    *same sphere*, so the ray is already sitting on the surface it is about
    to meet and the intersection parameter comes out at exactly 0.

    Requiring `t > 1e-9` discarded that root, and every ray in the fan --
    the axial one included -- was reported vignetted at the cemented
    interface. Nothing needs protecting against re-finding the surface just
    left: the trace is strictly sequential and never asks for the same
    surface twice.
    """
    beam = InputBeamSpec(z_ref=0.0, w_ref=3.0, collimated=True, wavelength_nm=632.8)
    fan = trace_fan(beam, _cemented_doublet(spacing_mm=0.0), ray_count=11)

    assert all(p.status == "ok" for p in fan.paths)
    assert all(p.stop_label == "" for p in fan.paths)
    # ...and the result is the same beam a hair of air would have given.
    airy = trace_fan(beam, _cemented_doublet(spacing_mm=1e-4), ray_count=11)
    for touching, apart in zip(fan.paths, airy.paths):
        assert touching.r_at(400.0) == pytest.approx(apart.r_at(400.0), abs=2e-3)


def test_a_zero_gap_refracts_glass_to_glass_rather_than_out_through_air():
    """Snell's law composes, so detouring through the ambient index gives the
    same direction as a direct glass-to-glass refraction -- but it can
    total-internally-reflect at an angle a real cemented joint passes without
    trouble, stopping the ray at an air surface that does not exist."""
    beam = InputBeamSpec(z_ref=0.0, w_ref=3.0, collimated=True, wavelength_nm=632.8)
    fan = trace_fan(beam, _cemented_doublet(spacing_mm=0.0), ray_count=11)

    path = next(p for p in fan.paths if p.r_launch > 0)
    joint = next(s for s in path.segments if abs(s.z1 - s.z0) < 1e-6 and s.z0 > 50.0)
    assert joint.n_medium == pytest.approx(1.6200)  # the flint, not air


def test_a_steep_cemented_joint_does_not_total_internally_reflect():
    """The failure the glass-to-glass fix removes, made to bite: a fast,
    high-index element whose marginal rays meet the joint well past the
    critical angle for glass-to-air (32.7 deg here) but nowhere near the one
    for glass-to-glass (76.7 deg). Routed out through the ambient index they
    are stopped dead at a surface that does not physically exist.
    """
    fast = Optic(name="Dense", diameter_full=40.0, thickness_center=12.0,
                 r1=22.0, r2=-22.0, n=1.85, z=30.0)
    second = Optic(name="Mate", diameter_full=40.0, thickness_center=6.0,
                   r1=-22.0, r2=float("inf"), n=1.80, z=42.0)
    beam = InputBeamSpec(z_ref=0.0, w_ref=8.0, collimated=True, wavelength_nm=632.8)

    cemented = trace_fan(beam, [fast, second], ray_count=21, pupil_radius_mm=18.0)
    assert not any(p.status == "tir" for p in cemented.paths)

    # Not vacuous: rays really do reach the joint past the glass-to-air
    # critical angle. Pulling the elements a micron apart -- a gap far too
    # small to matter optically -- brings the spurious TIR straight back.
    apart = Optic(name="Mate", diameter_full=40.0, thickness_center=6.0,
                  r1=-22.0, r2=float("inf"), n=1.80, z=42.0 + 1.0e-6)
    with_gap = trace_fan(beam, [fast, apart], ray_count=21, pupil_radius_mm=18.0)
    assert any(p.status == "tir" for p in with_gap.paths)
    assert sum(p.status == "ok" for p in cemented.paths) > sum(p.status == "ok" for p in with_gap.paths)


def test_cemented_doublet_focus_agrees_with_the_paraxial_model():
    """Cross-check against physics/system.py, which composes the same joint
    as ABCD matrices and has no notion of surfaces touching at all."""
    beam = InputBeamSpec(z_ref=0.0, w_ref=3.0, collimated=True, wavelength_nm=632.8)
    optics = _cemented_doublet(spacing_mm=0.0)
    paraxial_waist = OpticalSystem(beam, optics).propagate().segments[-1].beam.z_waist

    fan = trace_fan(beam, optics, ray_count=201)
    near_axis = next(p for p in fan.paths if p.r_launch > 0)
    last = near_axis.segments[-1]
    crossing = last.z0 - last.r0 * last.direction[0] / last.direction[1]

    assert crossing == pytest.approx(paraxial_waist, rel=1e-3)
