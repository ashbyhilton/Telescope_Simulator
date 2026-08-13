"""Dependency-free least-squares fit of the input beam's (z_waist, w0) to a
set of measured (z, diameter) data points, for the Fit-to-data tab's "Fit
input beam to data" button. The fit is a *full-system* fit: measurement
points may be anywhere along the beam path, including after optics, so each
trial re-propagates a candidate input beam through the whole OpticalSystem
rather than fitting a bare single-segment hyperbola.

There's no scipy dependency in this project (see requirements.txt). An
earlier version of this module tried alternating coordinate descent built on
physics/optimize.py's 1D `golden_section_minimize`, reusing that tested code
-- but golden-section search assumes its bracket is unimodal, which breaks
down here: a wide bracket for z_waist can straddle the z position of an
optic, beyond which propagate() raises (an infeasible input beam) and the
objective has a hard wall/plateau, not a single dip. That produced wrong
answers on a real through-a-lens fit in testing. This module instead
implements a small 2D Nelder-Mead simplex search directly (no bracket
required, tolerates the inf-penalty wall/plateau from invalid trial states
gracefully via ordinary float comparisons), which is standard for smooth,
low-dimensional problems like this one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, List, Sequence, Tuple

import numpy as np

from ..model.beam_spec import InputBeamSpec
from ..model.fit_data import FitDataPoint
from ..model.optics import Optic
from .system import OpticalSystem, segment_covering

_MIN_VALID_POINTS = 3


class FitUnavailable(Exception):
    """No fit can be attempted, or the search never found a finite
    objective. The message is user-facing."""


@dataclass
class FitResult:
    z_waist_mm: float
    w0_mm: float
    objective_value: float
    iterations: int


def _nelder_mead_2d(
    f: Callable[[np.ndarray], float], x0: Sequence[float], steps: Sequence[float],
    tol: float = 1e-10, max_iter: int = 400,
) -> Tuple[np.ndarray, float, int]:
    """Minimal 2-parameter Nelder-Mead simplex search. Defensive rather than
    crashing/hanging: iteration is hard-capped, and `f` returning `inf` for
    infeasible points is handled by ordinary float comparisons (no special
    casing needed -- `inf < inf` is False, `x < inf` is True for finite x)."""
    x0 = np.asarray(x0, dtype=float)
    simplex = [x0]
    for i, step in enumerate(steps):
        pt = x0.copy()
        pt[i] += step
        simplex.append(pt)
    simplex = np.array(simplex)
    fvals = np.array([f(pt) for pt in simplex])

    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5
    iterations = 0
    for _ in range(max_iter):
        iterations += 1
        order = np.argsort(fvals)
        simplex, fvals = simplex[order], fvals[order]
        if not math.isfinite(fvals[0]):
            break
        if abs(fvals[-1] - fvals[0]) <= tol:
            break

        centroid = simplex[:-1].mean(axis=0)
        worst = simplex[-1]
        xr = centroid + alpha * (centroid - worst)
        fr = f(xr)

        if fvals[0] <= fr < fvals[-2]:
            simplex[-1], fvals[-1] = xr, fr
        elif fr < fvals[0]:
            xe = centroid + gamma * (xr - centroid)
            fe = f(xe)
            simplex[-1], fvals[-1] = (xe, fe) if fe < fr else (xr, fr)
        else:
            xc = centroid + rho * (worst - centroid)
            fc = f(xc)
            if fc < fvals[-1]:
                simplex[-1], fvals[-1] = xc, fc
            else:
                for i in range(1, len(simplex)):
                    simplex[i] = simplex[0] + sigma * (simplex[i] - simplex[0])
                    fvals[i] = f(simplex[i])

    order = np.argsort(fvals)
    return simplex[order[0]], float(fvals[order[0]]), iterations


def _residual_sum_sq(beam_spec: InputBeamSpec, optics: List[Optic], points: List[FitDataPoint],
                      z_waist: float, w0: float) -> float:
    if w0 <= 0.0:
        return float("inf")
    trial_beam = replace(beam_spec, z_ref=z_waist, w_ref=w0, collimated=True, r_ref=None)
    try:
        result = OpticalSystem(trial_beam, optics).propagate()
    except ValueError:
        return float("inf")
    total = 0.0
    for p in points:
        if not p.is_valid():
            continue
        predicted_w = segment_covering(result, p.z_mm).beam.w(p.z_mm)
        measured_w = p.diameter_mm / 2.0
        total += (predicted_w - measured_w) ** 2
    return total


def fit_beam_to_data(
    beam_spec: InputBeamSpec,
    optics: List[Optic],
    points: List[FitDataPoint],
    max_iter: int = 600,
    tol: float = 1e-14,
) -> FitResult:
    valid = [p for p in points if p.is_valid()]
    if len(valid) < _MIN_VALID_POINTS:
        raise FitUnavailable(
            f"Need at least {_MIN_VALID_POINTS} complete data points to fit (have {len(valid)})."
        )

    z_values = [p.z_mm for p in valid]
    w_values = [p.diameter_mm / 2.0 for p in valid]
    z_span = max(max(z_values) - min(z_values), 1.0)

    def objective(x: np.ndarray) -> float:
        return _residual_sum_sq(beam_spec, optics, valid, x[0], x[1])

    # Multi-start: a single simplex run can settle in a local minimum when
    # the search has to cross an optic's "invalid beam" wall to reach the
    # true optimum (see module docstring), so try a few seeds spread across
    # the data's z-range and keep whichever run lands on the lowest
    # residual -- still just repeated calls to the same tested search, not a
    # new algorithm.
    seed_candidates = {min(valid, key=lambda p: p.diameter_mm).z_mm, beam_spec.z_ref}
    seed_candidates.update(z_values)
    w0_guess = max(min(w_values), 1e-6)

    best_point, best_val, best_iters = None, float("inf"), 0
    for z_guess in seed_candidates:
        point = np.array([z_guess, w0_guess])
        step_z, step_w = 0.25 * z_span, 0.5 * w0_guess
        total_iters = 0
        # Restart from the previous result with a shrinking simplex a few
        # times: a single Nelder-Mead run can report "converged" while
        # stalled along a narrow, correlated (z_waist, w0) ridge (the
        # simplex collapses in one direction before the other has fully
        # settled) -- restarting with a fresh, smaller simplex centered on
        # the current best point reliably polishes past that stall.
        for _ in range(4):
            point, val, iters = _nelder_mead_2d(
                objective, point, (step_z, step_w), tol=tol, max_iter=max_iter,
            )
            total_iters += iters
            step_z *= 0.1
            step_w *= 0.1
        if val < best_val:
            best_point, best_val, best_iters = point, val, total_iters

    if best_point is None or not math.isfinite(best_val):
        raise FitUnavailable("Could not find a valid input beam matching the provided data.")

    return FitResult(
        z_waist_mm=float(best_point[0]), w0_mm=float(best_point[1]),
        objective_value=best_val, iterations=best_iters,
    )
