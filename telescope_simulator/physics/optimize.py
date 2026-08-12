"""Dependency-free 1D optimisation for the Beam tab's "Optimise lens for
flatness"/"Optimise lens for focus" actions. Per the feature spec, the
objective is assumed unimodal between the governing optic's current
position and the true optimum -- a plain golden-section search is used
instead of a global search. Every trial evaluates `OpticalSystem.propagate()`
on a throwaway copy of the optics list (only the governing optic's `z`
differs); this module never re-derives ABCD/q-parameter propagation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, List, Optional, Tuple

from ..model.beam_spec import InputBeamSpec
from ..model.optics import Optic
from .system import BeamSegment, OpticalSystem, SystemResult

_GOLDEN = (5.0 ** 0.5 - 1.0) / 2.0  # ~0.618


class OptimizeUnavailable(Exception):
    """No search can be attempted: no governing optic, its z is locked, or
    there is no feasible room to search. The message is user-facing."""


@dataclass
class FeasibleBounds:
    lower: float
    upper: float

    @property
    def feasible(self) -> bool:
        return (self.upper - self.lower) > 1e-9


@dataclass
class GoverningOptic:
    index: int  # index into the z-sorted optics list
    optic: Optic
    bounds: FeasibleBounds


@dataclass
class OptimizeResult:
    optic_id: int
    z: float
    clamped: bool
    objective_value: float
    iterations: int


def golden_section_minimize(
    f: Callable[[float], float], lo: float, hi: float, tol: float, max_iter: int = 200,
) -> Tuple[float, float, int]:
    """Bracketed search assuming `f` is unimodal on [lo, hi]. Returns
    (best_x, best_f, iterations). Defensive rather than crashing/hanging:
    `hi <= lo` returns immediately, and iteration is hard-capped."""
    if hi <= lo:
        return lo, f(lo), 0
    tol = max(tol, 1e-9)
    a, b = lo, hi
    c = b - _GOLDEN * (b - a)
    d = a + _GOLDEN * (b - a)
    fc, fd = f(c), f(d)
    iterations = 0
    while (b - a) > tol and iterations < max_iter:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - _GOLDEN * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + _GOLDEN * (b - a)
            fd = f(d)
        iterations += 1
    return (c, fc, iterations) if fc < fd else (d, fd, iterations)


def find_governing_optic_index(optics_sorted: List[Optic], target_z: float) -> Optional[int]:
    """Index of the last optic (in z-ascending `optics_sorted`) whose back
    vertex (z + thickness_center) is at or before target_z -- "the optic
    immediately before the target location". This single filter already
    excludes an optic whose own glass contains target_z (its back vertex is
    then after target_z, so it fails), falling back to the one before it.
    None if no optic qualifies."""
    idx = None
    eps = 1e-9
    for i, optic in enumerate(optics_sorted):
        if optic.z + optic.thickness_center <= target_z + eps:
            idx = i
    return idx


def compute_feasible_bounds(
    optics_sorted: List[Optic], index: int, beam_z_ref: float, target_z: float, separation_mm: float,
) -> FeasibleBounds:
    """Legal front-vertex z range for optics_sorted[index]: at least
    `separation_mm` after the previous optic's back vertex (or the beam's
    own z_ref if there is none), and at least `separation_mm` before
    *whichever is closer* of the next optic's front vertex or target_z
    itself -- so the governing lens's back surface can never cross either."""
    governing = optics_sorted[index]
    if index > 0:
        prev = optics_sorted[index - 1]
        lower = prev.z + prev.thickness_center + separation_mm
    else:
        lower = beam_z_ref
    if index + 1 < len(optics_sorted):
        surface_limit = min(optics_sorted[index + 1].z, target_z)
    else:
        surface_limit = target_z
    upper = surface_limit - separation_mm - governing.thickness_center
    return FeasibleBounds(lower=lower, upper=upper)


def find_governing_optic(
    optics: List[Optic], beam_z_ref: float, target_z: float, separation_mm: float,
) -> Tuple[Optional[GoverningOptic], str]:
    """Single source of truth for "can an optimize button run right now",
    reused by both the optimizers below and the Beam tab's button-enable
    check, so the two can never disagree. Returns (info, reason); info is
    None and reason is a user-facing explanation whenever unavailable."""
    sorted_optics = sorted(optics, key=lambda o: o.z)
    idx = find_governing_optic_index(sorted_optics, target_z)
    if idx is None:
        return None, "No optic precedes the target location."
    optic = sorted_optics[idx]
    if optic.lock_z:
        return None, f"'{optic.name}' governs this target but its z position is locked."
    bounds = compute_feasible_bounds(sorted_optics, idx, beam_z_ref, target_z, separation_mm)
    if not bounds.feasible:
        return None, (
            f"No room to move '{optic.name}' without crossing a neighboring lens "
            f"or the target location."
        )
    return GoverningOptic(index=idx, optic=optic, bounds=bounds), ""


def _segment_covering(result: SystemResult, z: float) -> BeamSegment:
    for seg in result.segments:
        if seg.z_start - 1e-9 <= z <= seg.z_end + 1e-9:
            return seg
    return result.segments[-1]


def _flatness_objective(result: SystemResult, target_z: float) -> float:
    return _segment_covering(result, target_z).beam.divergence_half_angle


def _focus_objective(result: SystemResult, target_z: float) -> float:
    return abs(_segment_covering(result, target_z).beam.z_waist - target_z)


def _optimize(
    beam_spec: InputBeamSpec,
    optics: List[Optic],
    target_z: float,
    precision_mm: float,
    objective: Callable[[SystemResult, float], float],
) -> OptimizeResult:
    precision_mm = max(precision_mm, 1e-6)
    governing, reason = find_governing_optic(optics, beam_spec.z_ref, target_z, precision_mm)
    if governing is None:
        raise OptimizeUnavailable(reason)

    sorted_optics = sorted(optics, key=lambda o: o.z)
    optic = governing.optic
    thickness = optic.thickness_center

    def trial(z: float) -> float:
        trial_optics = list(sorted_optics)
        trial_optics[governing.index] = replace(optic, z=z)
        trailing = max(target_z - z - thickness, 0.0) + 1.0
        try:
            result = OpticalSystem(beam_spec, trial_optics).propagate(trailing_length=trailing)
        except ValueError:
            return float("inf")
        return objective(result, target_z)

    best_z, best_val, iterations = golden_section_minimize(
        trial, governing.bounds.lower, governing.bounds.upper, precision_mm,
    )
    if math.isinf(best_val):
        raise OptimizeUnavailable(
            f"Could not find a valid position for '{optic.name}' in the available range."
        )

    near_lower = bool(abs(best_z - governing.bounds.lower) <= precision_mm)
    near_upper = bool(abs(best_z - governing.bounds.upper) <= precision_mm)
    if near_lower:
        final_z = governing.bounds.lower
    elif near_upper:
        final_z = governing.bounds.upper
    else:
        final_z = best_z

    return OptimizeResult(
        optic_id=optic.id,
        z=float(final_z),
        clamped=near_lower or near_upper,
        objective_value=float(best_val),
        iterations=iterations,
    )


def optimize_for_flatness(
    beam_spec: InputBeamSpec, optics: List[Optic], target_z: float, precision_mm: float,
) -> OptimizeResult:
    """Move the governing optic's z to minimise the divergence half-angle
    of the beam segment covering target_z."""
    return _optimize(beam_spec, optics, target_z, precision_mm, _flatness_objective)


def optimize_for_focus(
    beam_spec: InputBeamSpec, optics: List[Optic], target_z: float, precision_mm: float,
) -> OptimizeResult:
    """Move the governing optic's z so that segment's next waist lands
    exactly at target_z."""
    return _optimize(beam_spec, optics, target_z, precision_mm, _focus_objective)
