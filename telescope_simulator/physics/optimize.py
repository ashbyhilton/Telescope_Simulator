"""Dependency-free 1D optimisation for the Beam tab's "Optimise lens for
flatness"/"Optimise lens for focus" actions. Per the feature spec, the
objective is assumed unimodal between the governing optic's current
position and the true optimum -- a plain golden-section search is used
instead of a global search. Every trial evaluates `OpticalSystem.propagate()`
on a throwaway copy of the optics list (only the governing unit's member(s)
`z` differ); this module never re-derives ABCD/q-parameter propagation.

"Governing unit" -- a standalone optic, or (since composite lenses were
added) an entire composite group moved together as one rigid block, exactly
mirroring `PlotView._on_item_dragged`'s canvas-drag behavior: every member
sharing the same `group_key` shifts by the same z delta, so a group's
internal spacing is never disturbed by an optimize run.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, List, Optional, Tuple

from ..model.beam_spec import InputBeamSpec
from ..model.optics import Optic, group_key
from .system import OpticalSystem, SystemResult, segment_covering


def _display_name(optic: Optic) -> str:
    return optic.group_name if optic.group_id is not None else optic.name

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
    index: int  # index into sorted_optics of the representative (frontmost) member
    optic: Optic  # the representative (frontmost) member -- for a standalone optic, itself
    member_indices: List[int]  # indices into sorted_optics of every optic that moves together
    bounds: FeasibleBounds  # feasible range for the representative member's own z
    sorted_optics: List[Optic]


@dataclass
class OptimizeResult:
    optic_id: int  # representative (frontmost) member's id
    z: float  # representative member's new z
    moved: List[Tuple[int, float]]  # (optic_id, new_z) for every optic that actually moved --
    # all group members for a composite, or just [(optic_id, z)] for a standalone optic
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
    sorted_optics: List[Optic], member_indices: List[int], beam_z_ref: float, target_z: float, separation_mm: float,
) -> FeasibleBounds:
    """Legal front-vertex z range for the *anchor* (frontmost member,
    `member_indices[0]`) of the governing unit -- a standalone optic, or
    every member of a composite group shifted together as one rigid block.
    At least `separation_mm` after the previous non-member optic's back
    vertex (or the beam's own z_ref if there is none), and at least
    `separation_mm` before *whichever is closer* of the next non-member
    optic's front vertex or target_z itself -- so the block's rear can never
    cross either. Assumes `member_indices` are contiguous in z-order, true
    for any group as actually created/edited/dragged (see
    PlotView._on_item_dragged and the Add-optic dialog's chained layout)."""
    first_idx = member_indices[0]
    last_idx = member_indices[-1]
    group_front = sorted_optics[first_idx].z
    group_back = max(sorted_optics[i].z + sorted_optics[i].thickness_center for i in member_indices)
    group_span = group_back - group_front

    if first_idx > 0:
        prev = sorted_optics[first_idx - 1]
        lower = prev.z + prev.thickness_center + separation_mm
    else:
        lower = beam_z_ref
    if last_idx + 1 < len(sorted_optics):
        surface_limit = min(sorted_optics[last_idx + 1].z, target_z)
    else:
        surface_limit = target_z
    upper = surface_limit - separation_mm - group_span
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
    key = group_key(optic)
    member_indices = [i for i, o in enumerate(sorted_optics) if group_key(o) == key]
    if any(sorted_optics[i].lock_z for i in member_indices):
        return None, f"'{_display_name(optic)}' governs this target but its z position is locked."
    representative_index = member_indices[0]
    representative = sorted_optics[representative_index]
    bounds = compute_feasible_bounds(sorted_optics, member_indices, beam_z_ref, target_z, separation_mm)
    if not bounds.feasible:
        return None, (
            f"No room to move '{_display_name(representative)}' without crossing a neighboring "
            f"lens or the target location."
        )
    return GoverningOptic(
        index=representative_index, optic=representative, member_indices=member_indices,
        bounds=bounds, sorted_optics=sorted_optics,
    ), ""


def _flatness_objective(result: SystemResult, target_z: float) -> float:
    return segment_covering(result, target_z).beam.divergence_half_angle


def _focus_objective(result: SystemResult, target_z: float) -> float:
    return abs(segment_covering(result, target_z).beam.z_waist - target_z)


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

    sorted_optics = governing.sorted_optics
    optic = governing.optic  # representative (frontmost) member
    member_indices = governing.member_indices
    original_front_z = optic.z
    # Group span (front vertex of the frontmost member to the back vertex of
    # whichever member extends furthest): the multi-member generalization of
    # "the governing optic's own thickness" used below for trailing padding
    # -- reduces to exactly the old single-optic behavior when there's only
    # one member.
    group_span = max(sorted_optics[i].z + sorted_optics[i].thickness_center for i in member_indices) - original_front_z

    def trial(anchor_z: float) -> float:
        delta = anchor_z - original_front_z
        trial_optics = list(sorted_optics)
        for i in member_indices:
            trial_optics[i] = replace(sorted_optics[i], z=sorted_optics[i].z + delta)
        trailing = max(target_z - anchor_z - group_span, 0.0) + 1.0
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
            f"Could not find a valid position for '{_display_name(optic)}' in the available range."
        )

    dist_lower = abs(best_z - governing.bounds.lower)
    dist_upper = abs(best_z - governing.bounds.upper)
    near_lower = bool(dist_lower <= precision_mm)
    near_upper = bool(dist_upper <= precision_mm)
    if near_lower and near_upper:
        # Feasible interval narrower than the search tolerance: both bounds
        # register as "near", so snap to whichever the search actually
        # converged closer to instead of always favoring the lower bound.
        final_z = governing.bounds.lower if dist_lower <= dist_upper else governing.bounds.upper
    elif near_lower:
        final_z = governing.bounds.lower
    elif near_upper:
        final_z = governing.bounds.upper
    else:
        final_z = best_z

    final_delta = float(final_z) - original_front_z
    moved = [(sorted_optics[i].id, sorted_optics[i].z + final_delta) for i in member_indices]

    return OptimizeResult(
        optic_id=optic.id,
        z=float(final_z),
        moved=moved,
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
