"""Geometric transverse irradiance at a target plane -- "what you would see
on a card held there", as distinct from `physics/diffraction.py`'s
diffraction PSF.

The two are complementary, and neither subsumes the other:

- The diffraction PSF is the correct profile when the system is at or near
  best focus, where the spot size is set by the wavelength and the aperture
  and geometric optics predicts a physically impossible point. It says
  nothing useful once the wavefront error is large, and `psf_radial_profile`
  refuses to compute one at all past the point where it could be sampled.
- This module is the correct profile in exactly that other regime: a
  defocused or strongly aberrated beam, where the visible spot is orders of
  magnitude larger than the diffraction limit and its shape is set purely by
  where the rays land. It is wrong near focus, where it collapses toward a
  singularity that diffraction actually prevents.

Method: each ray of a dense meridional fan carries the power of the annulus
it represents. For an input beam of 1/e^2 radius w at the launch plane, the
ray launched at height rho carries dP proportional to
`exp(-2 rho^2 / w^2) * |rho| * drho` -- the Gaussian irradiance times the
annulus circumference. That power arrives at the target at radius
|r(target)|, so accumulating it into radial bins and dividing each bin by
its *annulus* area (not its width) gives irradiance. The singularity this
method does have is at the target, where many annuli can pile into one bin
at focus.

The `|rho|` weight is exactly right for every ray *except* the axial one,
which is the one place it has no partner to share an annulus with -- see
`_launch_weights` below. Left at zero it puts a dimple on the axis of every
spot.

A ray is not a point, though, and depositing its power at a single radius
draws a staircase whose steps are an artifact of how many rays were traced
rather than anything optical. Each ray is therefore spread over the *ray
tube it stands for* -- the target-plane interval reaching halfway to its
neighbours on each side -- with its power distributed across that tube in
proportion to radius, since `dP/dr = I(rho) * rho * drho/dr` and only the
`rho` factor varies appreciably across one tube. Tubes tile the radius axis
exactly, so this is the honest piecewise reconstruction of `dP/dr` rather
than a smoothing filter: it leaves no gaps, invents no energy, narrows to
nothing where rays crowd at a caustic, and is *exact* for a uniformly
illuminated fan at any ray count.

Vignetted and TIR rays simply never arrive, so aperture clipping shows up in
the profile for free.

What comes out is irradiance I(x, 0) -- power per unit area on the card --
returned both as the computed radial half and as a full mirrored slice. It is
deliberately not the radial power distribution 2*pi*r*I(r): that quantity
integrates to the total power over dr and is the right thing to plot when
asking "how much light is at this radius", but it is zero on axis and peaks
in a ring even for a perfectly ordinary Gaussian spot, which is not what a
card shows. Dividing each bin by its annulus area rather than its width is
the single step that separates the two.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from ..model.beam_spec import InputBeamSpec
from ..model.optics import Optic
from .raytrace import trace_fan

# Rays traced for this profile, independent of the Config tab's fan count.
# That count controls how finely the *wavefront* is sampled for the Zernike
# fit, where 21 rays is plenty; an irradiance profile needs more before it
# stops looking like a histogram of the ray list. Giving each ray the width
# of its own tube is what keeps this number modest -- without it, a smooth
# curve needs several rays per bin and the count has to go up by an order of
# magnitude, which is what the closed-form bin integral in _deposit() is
# paying for.
DEFAULT_RAY_COUNT = 401
DEFAULT_BIN_COUNT = 120


def _tube_half_widths(signed_r: np.ndarray, spot_radius: float, smoothing: float) -> np.ndarray:
    """Half the target-plane width of the ray tube each ray stands for.

    `signed_r` must be in launch order (the fan is built that way), so
    neighbouring entries really are neighbouring rays and their separation at
    the target is the tube width. Signed, not folded to |r|: two rays either
    side of the axis are neighbours in the fan but land on opposite sides, and
    differencing the folded radii would report a spurious zero-width tube for
    every pair straddling the axis.

    The width is deliberately tied to the rays and *not* to the bin grid.
    Where rays crowd together the tube narrows to nothing and the result
    falls back to the plain histogram, which is right: crowding means the fan
    is resolving real structure there and widening the tube would destroy
    detail that is actually present. The floor only keeps the width off
    zero (`smoothing=0` collapses to a point deposit)."""
    floor = max(spot_radius * 1e-4, 1e-12)
    if len(signed_r) < 2:
        return np.full(len(signed_r), max(floor, spot_radius))
    tube = np.abs(np.gradient(signed_r))
    return np.maximum(0.5 * tube * smoothing, floor)


def _launch_weights(rho: np.ndarray, spacing: float) -> np.ndarray:
    """The radial factor of each ray's power: `|rho|`, except on the axis.

    Every off-axis ray shares its annulus with its mirror-image partner at
    `-rho`, so each carries half of `I * 2*pi*rho*drho` -- proportional to
    `I * |rho|`, which is where the familiar weight comes from. The axial ray
    has no partner. It stands for the whole central *disc* of radius
    `drho/2`, whose power is `I * pi * (drho/2)^2`; in the same units that is
    `I * drho/4`, not zero.

    Leaving it at zero looks harmless -- a zero-radius annulus really does
    carry no power -- but the disc it actually represents is then simply
    missing, and the innermost bin comes out low by roughly
    `(drho/2 / bin width)^2`. That draws as a dimple sitting exactly on the
    axis of every spot, which is precisely where the eye goes."""
    weights = np.abs(rho)
    if spacing > 0.0:
        weights = np.where(weights < 0.5 * spacing, 0.25 * spacing, weights)
    return weights


def _deposit(r_abs: np.ndarray, power: np.ndarray, half_width: np.ndarray,
             edges: np.ndarray, annulus_area: np.ndarray) -> np.ndarray:
    """Spread each ray's power across its own tube and return *irradiance*
    per bin.

    Within a tube the power is distributed in proportion to radius, so a
    bin's share of a tube is the share of the tube's *area* it covers --
    `(hi^2 - lo^2)` over the overlap, which `np.clip` on the bin edges gives
    directly. That is not a smoothing choice, it is what `dP/dr` does: only
    the `rho` factor of `I(rho) * rho * drho/dr` varies appreciably across one
    tube, and near the axis it varies by a lot (the tube at `rho = 2*drho`
    spans radii differing by 50%). Distributing evenly in radius instead
    leaves the innermost bins several percent out; a Gaussian of the tube's
    width additionally smooths the `|r|` cusp at the axis and puts a few
    percent *too much* there. Integrating the real tube exactly does neither,
    and costs an erf-free clip rather than four erf evaluations per ray.

    Two further details:
    - The tube is *mirrored about r = 0*. Radius is a folded coordinate, so a
      ray landing within its own tube width of the axis has part of that tube
      on the far side; without the mirror that part is lost. For the axial
      ray both branches coincide, which the per-ray normalization absorbs.
    - Each ray's shares are normalized to sum to one, so it deposits exactly
      its own power however wide its tube is and however much of the grid it
      covers. Energy conservation is structural here, not approximate.
    """
    mu, h = r_abs[:, None], half_width[:, None]
    edges_row = edges[None, :]
    share = np.zeros((len(r_abs), len(edges) - 1))
    for centre in (mu, -mu):
        clipped = np.clip(edges_row, centre - h, centre + h)
        share += np.diff(clipped * clipped, axis=1)
    np.clip(share, 0.0, None, out=share)  # analytically non-negative; guard rounding
    totals = share.sum(axis=1, keepdims=True)
    np.divide(share, totals, out=share, where=totals > 0.0)
    return (power[:, None] * share).sum(axis=0) / annulus_area


@dataclass
class TransverseIntensityResult:
    # The slice a card actually shows: I(x, 0) against a signed transverse
    # coordinate running from -x_max through 0 to +x_max. This is irradiance
    # (power per unit area), *not* the radial power distribution
    # 2*pi*r*I(r) -- the two differ by exactly that factor, and plotting the
    # latter puts a spurious zero at the centre of every profile and moves
    # the apparent peak out to a ring.
    x_mm: np.ndarray
    intensity: np.ndarray  # I(x, 0), normalized to peak 1
    # The same data as the r >= 0 half only, at bin centres: what the binning
    # actually computed, before mirroring. Kept because encircled-energy and
    # any integral over the profile want the radial form, where the annulus
    # areas are the natural weights.
    radius_mm: np.ndarray
    intensity_radial: np.ndarray
    spot_radius_mm: float  # largest radius any ray reaches -- the geometric spot edge
    encircled_50_mm: float  # radius containing half the arriving power
    n_arriving: int
    n_total: int


def transverse_intensity(
    beam_spec: InputBeamSpec,
    optics: List[Optic],
    target_z: float,
    ambient_index: float = 1.0,
    ray_count: int = DEFAULT_RAY_COUNT,
    bin_count: int = DEFAULT_BIN_COUNT,
    pupil_radius_mm: Optional[float] = None,
    smoothing: float = 1.0,
) -> TransverseIntensityResult:
    """Radial irradiance profile at `target_z` from a dense ray fan, each ray
    weighted by the input beam's Gaussian irradiance at its launch height and
    spread over the width of the ray tube it represents.

    `smoothing` scales that tube width: 1.0 means each ray covers exactly the
    gap to its neighbours, 0 collapses back to a point-deposit histogram."""
    fan = trace_fan(
        beam_spec, optics, ambient_index=ambient_index,
        ray_count=ray_count, pupil_radius_mm=pupil_radius_mm,
    )

    w_ref = beam_spec.w_ref
    if not w_ref > 0.0:
        raise ValueError(f"The input beam radius must be positive (got {w_ref}).")

    radii: List[float] = []
    signed_radii: List[float] = []
    launch: List[float] = []
    for path in fan.paths:
        if not path.reaches(target_z):
            continue
        launch.append(path.r_launch)
        r_here = path.r_at(target_z)
        signed_radii.append(r_here)
        radii.append(abs(r_here))

    if not radii:
        raise ValueError(f"No ray reaches z={target_z}; there is nothing to land on a card there.")

    r_arrive = np.asarray(radii)
    rho = np.asarray(launch)
    # Gaussian irradiance at the launch height, times the radial extent of
    # the annulus (or, on the axis, the disc) that height stands for.
    # Spacing comes from the fan as launched, not from the survivors: a stop
    # can leave two survivors far apart, and their separation is not the
    # annulus width either of them stands for.
    spacing = (2.0 * fan.pupil_radius_mm / (len(fan.paths) - 1)) if len(fan.paths) > 1 else 0.0
    power = np.exp(-2.0 * rho * rho / (w_ref * w_ref)) * _launch_weights(rho, spacing)
    spot_radius = float(r_arrive.max())
    if float(power.sum()) <= 0.0 or spot_radius <= 0.0 or not np.isfinite(spot_radius):
        # Two very different situations both end with a zero-width spot, and
        # naming the wrong one points the user at entirely the wrong control.
        # If rays went missing on the way here, an aperture is the cause; if
        # every ray arrived and they all landed on the axis, it is focus.
        if len(radii) < len(fan.paths):
            raise ValueError(
                f"Essentially no light reaches z={target_z}: the apertures between here and "
                "there pass little more than the central ray. Widen an optic or move the target."
            )
        raise ValueError(
            "Every ray converges to a point at this plane, so the geometric spot has no width to "
            "plot -- at best focus the real profile is set by diffraction, and the PSF above is "
            "the meaningful one."
        )

    half_width = _tube_half_widths(np.asarray(signed_radii), spot_radius, smoothing)
    # Run the bins a little past the geometric edge so the outermost rays'
    # tubes are captured whole; without the headroom they would be
    # renormalized against a truncated grid and pile up at the last bin.
    # Sized off a high percentile rather than the maximum: near a caustic a
    # single ray's neighbours can be most of the spot away, and letting that
    # one tube set the headroom would spend most of the bins on empty space.
    outer = spot_radius + 3.0 * float(np.percentile(half_width, 98))
    edges = np.linspace(0.0, outer, int(bin_count) + 1)
    # Irradiance is power per unit *area*, and an outer bin covers far more
    # area than an inner one of the same width -- treating a bin as its width
    # would make every profile falsely rise toward its outer edge.
    annulus_area = np.pi * (edges[1:] ** 2 - edges[:-1] ** 2)
    irradiance = _deposit(r_arrive, power, half_width, edges, annulus_area)

    binned = irradiance * annulus_area  # power per bin, for the encircled figure
    peak = float(irradiance.max())
    if peak > 0.0:
        irradiance = irradiance / peak

    cumulative = np.cumsum(binned)
    total = float(cumulative[-1])
    encircled_50 = float(edges[1:][np.searchsorted(cumulative, 0.5 * total)]) if total > 0.0 else 0.0

    # Bin *centres*, not outer edges: each bin's value is the mean irradiance
    # over the annulus, which belongs at its middle. Reporting the outer edge
    # shifts the whole profile out by half a bin, which is a visible offset
    # on a spot only a few bins wide.
    centres = 0.5 * (edges[:-1] + edges[1:])
    # Mirror to a full slice. The pupil and every surface in this app are
    # rotationally symmetric (see raytrace.py), so I(-x, 0) = I(+x, 0)
    # identically -- the negative half carries no independent information,
    # but a card does not show you a half-plane, and reading a spot's width
    # off a one-sided plot invites halving errors.
    x_mm = np.concatenate((-centres[::-1], centres))
    intensity_slice = np.concatenate((irradiance[::-1], irradiance))

    return TransverseIntensityResult(
        x_mm=x_mm,
        intensity=intensity_slice,
        radius_mm=centres,
        intensity_radial=irradiance,
        spot_radius_mm=spot_radius,
        encircled_50_mm=encircled_50,
        n_arriving=len(radii),
        n_total=len(fan.paths),
    )
