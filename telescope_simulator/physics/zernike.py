"""Zernike decomposition of the wavefront error map produced by
`physics/raytrace.py`.

Because the app is strictly axis-aligned (no tilt/decenter -- see
`raytrace.py`'s docstring), the wavefront error is a function of pupil
radius only, never azimuth. That means only the rotationally-symmetric
("m=0") Zernike terms -- piston, defocus, and primary/secondary/tertiary
spherical aberration -- can possibly be non-zero; every other standard
Zernike term (coma, astigmatism, trefoil, ...) is *exactly* zero by the
symmetry argument, not just small.

This module deliberately fits **only** the m=0 terms directly against the
real (rho, W) samples `physics.raytrace.wavefront_at` produces (pooling both
the +rho and -rho branches of the meridional fan into one 1D least-squares
problem). An earlier draft of this plan considered fabricating synthetic
azimuth samples so a full 2D Zernike fit could be run and "confirm" the
non-symmetric terms come back near zero -- that was rejected during
implementation: manufacturing azimuth samples we already know the answer for
isn't a real validation, it's just re-asserting the assumption into the
input data. The genuine, cheap sanity check this module *does* offer instead
is `physics.raytrace`'s own `test_wavefront_is_symmetric_about_the_axis`
test, which checks the +rho/-rho agreement on real traced data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence

import numpy as np

# (Noll index, radial order n, name, one-line description). Noll indices for
# the m=0 family follow the standard sequence 1, 4, 11, 22, 37, ... (piston,
# then every other even n from there); see Noll (1976), J. Opt. Soc. Am. 66.
ZERNIKE_TERMS: List[tuple] = [
    (1, 0, "Piston", "A uniform phase offset across the pupil -- no effect on image quality, just a reference shift."),
    (4, 2, "Defocus", "A uniform quadratic phase error -- the target plane isn't exactly at best focus; move it along z to null this term."),
    (11, 4, "Primary spherical aberration", "Outer (marginal) rays focus at a different plane than paraxial rays -- the classic single-lens aberration; larger for shorter focal ratios."),
    (22, 6, "Secondary spherical aberration", "A higher-order correction to the marginal-vs-paraxial focus mismatch, significant mainly for fast/high-aperture systems."),
    (37, 8, "Tertiary spherical aberration", "A further higher-order refinement of the same marginal-focus effect; usually negligible unless the system is very fast or the pupil is sampled with many rays."),
]

ZERNIKE_DESCRIPTIONS: Dict[int, str] = {noll: desc for noll, _n, _name, desc in ZERNIKE_TERMS}
ZERNIKE_NAMES: Dict[int, str] = {noll: name for noll, _n, name, _desc in ZERNIKE_TERMS}


def zernike_radial_m0(n: int, rho: np.ndarray) -> np.ndarray:
    """The m=0 radial Zernike polynomial R_n^0(rho), for the specific even
    orders this module needs (0, 2, 4, 6, 8) -- hardcoded standard forms
    rather than the general recursive formula, since there are only five of
    them and hand-verifying five short polynomials is easier than trusting a
    generic implementation with binomial coefficients no test here would
    catch a sign error in."""
    rho = np.asarray(rho, dtype=float)
    if n == 0:
        return np.ones_like(rho)
    if n == 2:
        return 2.0 * rho**2 - 1.0
    if n == 4:
        return 6.0 * rho**4 - 6.0 * rho**2 + 1.0
    if n == 6:
        return 20.0 * rho**6 - 30.0 * rho**4 + 12.0 * rho**2 - 1.0
    if n == 8:
        return 70.0 * rho**8 - 140.0 * rho**6 + 90.0 * rho**4 - 20.0 * rho**2 + 1.0
    raise ValueError(f"zernike_radial_m0 only supports n in (0, 2, 4, 6, 8), got {n}")


@dataclass
class ZernikeFitResult:
    coefficients_mm: Dict[int, float]  # Noll index -> coefficient, same length units as the input W
    # RMS wavefront error: the area-weighted RMS of the fitted wavefront over
    # the pupil, with piston removed. This is the standard quality figure
    # (the Marechal criterion puts "diffraction-limited" at lambda/14 RMS),
    # and it is emphatically *not* residual_rms_mm below -- an early cut
    # reported the residual under this name, which meant a system with 25
    # waves of peak-to-valley error advertised an RMS of 1e-8 waves, because
    # five terms happen to describe a smooth wavefront almost exactly.
    rms_mm: float
    # How well those five terms actually fit the traced samples. Near zero
    # for any well-behaved system; large only if the wavefront has structure
    # the m=0 family cannot represent, which for this app's strictly
    # symmetric model would mean something is wrong upstream.
    residual_rms_mm: float
    peak_to_valley_mm: float
    pupil_radius_mm: float
    n_points: int


def fit_zernike_rotational(rho_mm: Sequence[float], opd_mm: Sequence[float],
                            pupil_radius_mm: float) -> ZernikeFitResult:
    """Least-squares fit of the m=0 Zernike terms in `ZERNIKE_TERMS` to
    (rho_mm, opd_mm) samples -- both branches of a signed meridional fan are
    used together (rho is normalized by its absolute value, matching the
    rotational symmetry the samples themselves must obey)."""
    rho = np.asarray(rho_mm, dtype=float)
    opd = np.asarray(opd_mm, dtype=float)
    if len(rho) < len(ZERNIKE_TERMS):
        raise ValueError(
            f"Need at least {len(ZERNIKE_TERMS)} surviving rays to fit {len(ZERNIKE_TERMS)} Zernike "
            f"terms (have {len(rho)})."
        )
    if not pupil_radius_mm > 0.0:
        raise ValueError(
            f"The pupil radius to normalize by must be positive (got {pupil_radius_mm}); "
            "with every surviving ray on the axis there is no pupil to fit across."
        )
    rho_norm = np.abs(rho) / pupil_radius_mm

    design = np.stack([zernike_radial_m0(n, rho_norm) for _noll, n, _name, _desc in ZERNIKE_TERMS], axis=1)
    coeffs, *_ = np.linalg.lstsq(design, opd, rcond=None)

    fitted = design @ coeffs
    residual = opd - fitted
    residual_rms = float(np.sqrt(np.mean(residual**2))) if len(residual) else 0.0

    coefficients = {noll: float(c) for (noll, *_rest), c in zip(ZERNIKE_TERMS, coeffs)}
    peak_to_valley = float(np.max(opd) - np.min(opd)) if len(opd) else 0.0

    return ZernikeFitResult(
        coefficients_mm=coefficients,
        rms_mm=rms_from_coefficients(coefficients),
        residual_rms_mm=residual_rms,
        peak_to_valley_mm=peak_to_valley,
        pupil_radius_mm=pupil_radius_mm,
        n_points=len(rho),
    )


def rms_from_coefficients(coefficients_mm: Dict[int, float]) -> float:
    """Area-weighted RMS of the wavefront over the pupil, piston excluded.

    Cheaper and steadier than integrating the polynomial: the orthonormal
    (Noll) form of an m=0 term is sqrt(n+1)*R_n^0, and orthonormal
    coefficients add in quadrature to the RMS, so a fit expressed against
    the plain R_n^0 used here needs only the 1/sqrt(n+1) rescaling first.
    Doing it from the coefficients rather than from the ray samples also
    keeps the figure independent of how the fan happens to be sampled -- the
    samples are uniform in radius, so averaging them directly would weight
    the pupil centre far too heavily."""
    n_by_noll = {noll: n for noll, n, _name, _desc in ZERNIKE_TERMS}
    total = 0.0
    for noll, coeff in coefficients_mm.items():
        if noll == 1:  # piston: a reference shift, not an error
            continue
        total += coeff * coeff / (n_by_noll[noll] + 1)
    return math.sqrt(total)


def wavefront_polynomial(coefficients_mm: Dict[int, float], rho_norm: np.ndarray) -> np.ndarray:
    """Evaluate the fitted W(rho) polynomial at arbitrary normalized radii
    (0..1) -- used by `physics/diffraction.py` to build a smooth, noise-free
    pupil phase map from the (necessarily discrete) ray-fan samples."""
    n_by_noll = {noll: n for noll, n, _name, _desc in ZERNIKE_TERMS}
    total = np.zeros_like(np.asarray(rho_norm, dtype=float))
    for noll, coeff in coefficients_mm.items():
        total = total + coeff * zernike_radial_m0(n_by_noll[noll], rho_norm)
    return total
