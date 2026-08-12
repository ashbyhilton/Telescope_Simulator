import numpy as np
import pytest

from telescope_simulator.model.beam_spec import InputBeamSpec
from telescope_simulator.model.optics import Optic
from telescope_simulator.physics.optimize import (
    OptimizeUnavailable,
    find_governing_optic,
    golden_section_minimize,
    optimize_for_flatness,
    optimize_for_focus,
)

WAVELENGTH_NM = 632.8
W0 = 1.0
ZR = np.pi * W0**2 / (WAVELENGTH_NM * 1e-6)
F = 100.0  # thin biconvex, n=1.5, r1=100, r2=-100 -> f=100mm exactly


def _self_1983(s: float):
    """Self (1983) thin-lens Gaussian focusing formulas (independent
    closed-form reference, matching test_system.py's own validation)."""
    m = F / np.sqrt((s - F) ** 2 + ZR**2)
    s_prime = F + m**2 * (s - F)
    waist_z = s + s_prime
    return m, waist_z


def _thin_biconvex(z: float) -> Optic:
    return Optic(name="L1", diameter_full=25.4, thickness_center=1e-4, r1=100.0, r2=-100.0, n=1.5, z=z)


def _beam_spec() -> InputBeamSpec:
    return InputBeamSpec(wavelength_nm=WAVELENGTH_NM, z_ref=0.0, w_ref=W0, collimated=True)


def test_golden_section_converges_on_parabola():
    x, fx, _ = golden_section_minimize(lambda x: (x - 3.0) ** 2, 0.0, 10.0, tol=1e-6)
    assert x == pytest.approx(3.0, abs=1e-4)
    assert fx == pytest.approx(0.0, abs=1e-6)


def test_golden_section_handles_degenerate_bracket_without_raising():
    x, fx, iters = golden_section_minimize(lambda x: x, 5.0, 5.0, tol=1e-6)
    assert x == 5.0
    assert iters == 0


def test_golden_section_never_hangs_on_bad_tol():
    x, fx, iters = golden_section_minimize(lambda x: (x - 3.0) ** 2, 0.0, 10.0, tol=-1.0, max_iter=50)
    assert iters <= 50


def test_optimize_for_flatness_matches_analytic_optimum():
    # M(s) = f / sqrt((s-f)^2 + zR^2) is maximized (divergence minimized)
    # exactly at s=f, independent of target_z, for any target past the lens.
    lens = _thin_biconvex(z=50.0)
    result = optimize_for_flatness(_beam_spec(), [lens], target_z=500.0, precision_mm=0.01)

    assert result.z == pytest.approx(F, abs=0.05)
    assert result.clamped is False


def test_optimize_for_focus_matches_analytic_optimum():
    s0 = 50.0
    _, waist_z_at_s0 = _self_1983(s0)

    lens = _thin_biconvex(z=80.0)  # start somewhere else
    result = optimize_for_focus(_beam_spec(), [lens], target_z=waist_z_at_s0, precision_mm=0.01)

    assert result.z == pytest.approx(s0, abs=0.05)
    assert result.clamped is False


def test_optimize_for_flatness_clamps_at_neighboring_lens():
    lens = _thin_biconvex(z=50.0)  # unconstrained optimum is z=100
    neighbor = Optic(name="Window", diameter_full=25.4, thickness_center=1.0, z=100.005)
    # Target sits in the air gap *before* the neighbor, so the neighbor
    # itself is not "the optic before the target" -- only its position
    # constrains how far the lens can move.
    target_z = 100.004

    result = optimize_for_flatness(
        _beam_spec(), [lens, neighbor], target_z=target_z, precision_mm=0.01,
    )

    assert result.clamped is True
    expected_upper = target_z - 0.01 - lens.thickness_center
    assert result.z == pytest.approx(expected_upper, abs=1e-3)
    assert result.z < 100.0  # never crossed into the neighbor


def test_no_governing_optic_before_target():
    lens = _thin_biconvex(z=50.0)
    with pytest.raises(OptimizeUnavailable, match="No optic precedes"):
        optimize_for_flatness(_beam_spec(), [lens], target_z=10.0, precision_mm=0.01)

    info, reason = find_governing_optic([lens], beam_z_ref=0.0, target_z=10.0, separation_mm=0.01)
    assert info is None
    assert "No optic precedes" in reason


def test_locked_governing_optic_is_unavailable():
    lens = _thin_biconvex(z=50.0)
    lens.lock_z = True
    with pytest.raises(OptimizeUnavailable, match="locked"):
        optimize_for_focus(_beam_spec(), [lens], target_z=500.0, precision_mm=0.01)


def test_infeasible_bounds_raises_unavailable():
    prev = Optic(name="Prev", diameter_full=25.4, thickness_center=5.0, z=0.0)
    governing = Optic(name="Governing", diameter_full=25.4, thickness_center=1.0, z=5.0)
    target_z = 6.005  # only 5um past governing's own back vertex

    info, reason = find_governing_optic(
        [prev, governing], beam_z_ref=0.0, target_z=target_z, separation_mm=0.01,
    )
    assert info is None
    assert "No room" in reason

    with pytest.raises(OptimizeUnavailable, match="No room"):
        optimize_for_flatness(_beam_spec(), [prev, governing], target_z=target_z, precision_mm=0.01)
