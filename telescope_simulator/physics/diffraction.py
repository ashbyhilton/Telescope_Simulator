"""Diffraction point-spread function from the fitted wavefront map --
physically correct for a near-diffraction-limited beam (this app's normal
operating regime), unlike a geometric spot-diagram histogram, which is only
a valid approximation when aberrations are large compared to the diffraction
limit. Plain numpy FFT, no new dependency, per the same "physics/ only
imports numpy" invariant as the rest of this package.

Because the wavefront map is rotationally symmetric (see raytrace.py's and
zernike.py's docstrings), a genuinely exact 2D pupil array can be built by
evaluating the fitted 1D W(rho) polynomial at each grid point's radius --
every point at a given rho has the same phase and amplitude by the proven
symmetry, so this is exact revolution, not an approximation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from .zernike import wavefront_polynomial

# Largest pupil grid, and largest zero-padded FFT, this module will grow to
# when the wavefront needs finer sampling (see _required_grid_size). Bounded
# because the FFT is O(N^2 log N) in memory and time and this runs inside an
# interactive refresh: 2048^2 complex is ~64 MB and ~600 ms per call, which
# is far too slow to sit behind a drag.
#
# Holding the *padded* size fixed means refining the pupil grid spends the
# zero-padding rather than the FFT budget, so the cost stays flat (~80 ms) at
# every refinement level. That is the right trade rather than a reluctant
# one: a steeper wavefront makes a broader pattern, which needs the image
# plane sampled over a wider span, not more finely.
MAX_GRID_SIZE = 1024
MAX_PADDED_SIZE = 1024


@dataclass
class PSFResult:
    radius_mm_at_target: np.ndarray  # radial coordinate at the target plane, mm
    intensity: np.ndarray  # normalized (peak = 1) radial intensity profile
    airy_first_null_mm: float  # 1.22 * lambda * (distance to target / (2*pupil_radius)), for reference
    # Radius at which the computed profile first falls to 1/e^2 of its peak.
    # Unlike airy_first_null_mm this is measured from the pattern actually
    # produced, so it stays meaningful for an apodized (Gaussian-illuminated)
    # pupil, which has no null at all -- see `gaussian_w_norm` below.
    core_radius_mm: float = 0.0
    # Suggested half-width for a linear-axis plot: wide enough to show the
    # core and the first couple of rings, narrow enough that the core is not
    # a single pixel. The FFT's own radius array runs out to ~100x this.
    display_radius_mm: float = 0.0
    grid_size_used: int = 0  # pupil samples across the diameter, after any Nyquist-driven refinement
    pad_factor_used: int = 0  # zero-padding multiple actually applied


def _required_grid_size(coefficients_mm: Dict[int, float], wavelength_mm: float) -> int:
    """Pupil samples needed across the diameter to keep the phase step
    between neighbouring samples below pi.

    The pupil phase is 2*pi*W(rho)/lambda, sampled at spacing 2/(n-1) in
    normalized rho, so the worst-case step is 2*pi*S * 2/(n-1) where S is
    max|dW/drho| in waves. Requiring that to stay under pi gives n > 4S + 1.
    Above that the FFT aliases *silently*: the pattern wraps around and a
    badly defocused pupil comes back looking near-diffraction-limited again,
    which is a far worse failure than refusing to plot."""
    rho = np.linspace(0.0, 1.0, 2049)
    w_waves = wavefront_polynomial(coefficients_mm, rho) / wavelength_mm
    slope = np.max(np.abs(np.diff(w_waves))) * (len(rho) - 1) if len(rho) > 1 else 0.0
    return int(math.ceil(4.0 * float(slope))) + 2


def psf_radial_profile(
    coefficients_mm: Dict[int, float],
    pupil_radius_mm: float,
    wavelength_nm: float,
    distance_to_target_mm: float,
    grid_size: int = 256,
    pad_factor: int = 4,
    gaussian_w_norm: Optional[float] = None,
) -> PSFResult:
    """Fraunhofer-propagate the aberrated pupil to the target plane via a
    zero-padded 2D FFT, then azimuthally average back to a 1D radial profile
    (exact for a rotationally symmetric pupil -- every pixel at a given
    image-plane radius is statistically identical, so averaging over angle
    only reduces the square grid's sampling noise, it doesn't discard real
    information).

    `grid_size` is a *minimum*: a steeper wavefront is sampled on a finer
    pupil grid (with the zero-padding reduced to keep the FFT bounded), and
    one steeper than MAX_GRID_SIZE can represent raises ValueError rather
    than returning an aliased profile.

    `gaussian_w_norm` is the illuminating beam's 1/e^2 *intensity* radius
    expressed in units of `pupil_radius_mm`, and it matters far more than it
    looks. Leaving it None gives a uniformly illuminated disk -- the textbook
    Airy case, and the right default for a filled aperture, but badly wrong
    for a Gaussian beam that the traced fan deliberately extends past (the
    fan runs to 2.5 w by default, so a uniform disk over that radius is 2.5x
    too wide an aperture and predicts a core ~2.5x too narrow, plus Airy
    rings a Gaussian simply does not have).

    One approximation is carried here, the same one the fitted W(rho)
    already carries: the amplitude is a function of the *launch*-height
    Gaussian evaluated at the normalized exit-pupil coordinate, i.e. the
    launch-to-exit pupil map is taken as linear and its Jacobian (which
    would redistribute amplitude where the mapping is compressed) is
    neglected. That is exact for a system with no pupil distortion and small
    for the on-axis systems this app models.
    """
    wavelength_mm = wavelength_nm * 1e-6
    if not pupil_radius_mm > 0.0:
        raise ValueError(f"The pupil radius must be positive to diffract from (got {pupil_radius_mm}).")
    if not distance_to_target_mm > 0.0:
        raise ValueError(
            "The target is at or in front of the system's exit plane, so there is no propagation "
            "distance to diffract over; pin a target downstream of the last optic."
        )

    required_n = _required_grid_size(coefficients_mm, wavelength_mm)
    if required_n > MAX_GRID_SIZE:
        pv_waves = float(
            np.ptp(wavefront_polynomial(coefficients_mm, np.linspace(0.0, 1.0, 257))) / wavelength_mm
        )
        raise ValueError(
            f"The wavefront error at this target ({pv_waves:.0f} waves peak-to-valley) is far too "
            "large to compute a meaningful diffraction pattern -- at this point the spot is a "
            "geometric blur, not a PSF. Move the target closer to best focus. (The Zernike terms "
            "and wavefront plot above are still valid.)"
        )
    n = max(int(grid_size), required_n)
    pad = max(1, min(int(pad_factor), MAX_PADDED_SIZE // n))

    coords = np.linspace(-1.0, 1.0, n)
    x, y = np.meshgrid(coords, coords)
    rho_norm = np.hypot(x, y)
    aperture = rho_norm <= 1.0

    amplitude = np.zeros((n, n))
    if gaussian_w_norm is not None and gaussian_w_norm > 0.0:
        # Field amplitude, not irradiance: I = |E|^2, so a 1/e^2 intensity
        # radius w corresponds to exp(-(rho/w)^2) in amplitude. Getting that
        # factor of two wrong is invisible on the pupil and obvious in the
        # pattern -- it would put the beam's effective aperture out by sqrt(2).
        amplitude[aperture] = np.exp(-((rho_norm[aperture] / gaussian_w_norm) ** 2))
    else:
        amplitude[aperture] = 1.0

    phase = np.zeros((n, n))
    phase[aperture] = 2.0 * np.pi * wavefront_polynomial(coefficients_mm, rho_norm[aperture]) / wavelength_mm

    pupil = amplitude * np.exp(1j * phase)

    padded_n = n * pad
    padded = np.zeros((padded_n, padded_n), dtype=complex)
    offset = (padded_n - n) // 2
    padded[offset:offset + n, offset:offset + n] = pupil

    field = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(padded)))
    intensity_2d = np.abs(field) ** 2
    peak = intensity_2d.max()
    if peak > 0:
        intensity_2d = intensity_2d / peak

    # Image-plane sampling implied by the FFT: for an input grid spanning
    # +/-pupil_radius_mm over `n` samples, zero-padded to `padded_n`, the
    # angular-spectrum FFT's output pixel pitch is
    # wavelength * distance / (padded_n * pixel_pitch_in), by the standard
    # discrete-Fourier-propagation relation. `coords` above is a linspace
    # *inclusive of both endpoints*, so its spacing is 2/(n-1), not 2/n --
    # getting that wrong scales the whole radius axis by n/(n-1) and puts
    # the plotted profile a fraction of a percent out of step with the
    # analytic airy_first_null_mm reported alongside it.
    pixel_pitch_in = (2.0 * pupil_radius_mm) / (n - 1)
    image_pixel_pitch = wavelength_mm * distance_to_target_mm / (padded_n * pixel_pitch_in)

    center = padded_n // 2
    profile, radius_px = _azimuthal_average(intensity_2d, center)

    airy_first_null = 1.22 * wavelength_mm * distance_to_target_mm / (2.0 * pupil_radius_mm)
    radius = radius_px * image_pixel_pitch
    core_radius = _first_crossing(radius, profile, math.exp(-2.0))

    return PSFResult(
        radius_mm_at_target=radius,
        intensity=profile,
        airy_first_null_mm=airy_first_null,
        core_radius_mm=core_radius,
        # Enough room for the core plus the first two or three rings. Taking
        # the larger of the two widths covers both regimes: a hard-edged
        # pupil where the Airy null is the natural scale, and an apodized or
        # aberrated one where the measured core is much the wider.
        display_radius_mm=3.0 * max(airy_first_null, core_radius),
        grid_size_used=n,
        pad_factor_used=pad,
    )


def _first_crossing(radius: np.ndarray, profile: np.ndarray, level: float) -> float:
    """Radius at which `profile` first drops below `level`, linearly
    interpolated between the bracketing samples rather than snapped to one
    of them -- the core is only a handful of samples wide at the default
    grid, so rounding to the nearest sample is a several-percent error in
    the reported spot size."""
    below = np.flatnonzero(profile < level)
    if len(below) == 0:
        return float(radius[-1])
    i = int(below[0])
    if i == 0:
        return 0.0
    hi, lo = profile[i - 1], profile[i]
    frac = (hi - level) / (hi - lo) if hi > lo else 0.0
    return float(radius[i - 1] + frac * (radius[i] - radius[i - 1]))


def _azimuthal_average(intensity_2d: np.ndarray, center: int):
    """Mean intensity in one-pixel-wide annuli about `center`, out to the
    edge of the inscribed circle, returned with the *mean pixel radius* of
    each annulus alongside it.

    A single central row would be cheaper, but it is not what a rotationally
    symmetric pupil sampled on a *square* grid gives you: the FFT output has
    only 4-fold symmetry, so one row carries the grid's sampling noise
    undiminished. Averaging the whole annulus is what actually delivers the
    noise reduction, and it costs a bincount next to an FFT.

    The returned radii are why this function hands back two arrays. Binning
    by `rint(hypot(...))` puts pixels at 1.0 and 1.414 pixels from the centre
    into the same annulus, whose mean radius is 1.21 -- so labelling that bin
    "1" reports a value sampled further out than it claims. On a profile as
    sharply peaked as a PSF core that is a several-percent error that grows
    toward the centre, and it draws as a too-tall, too-narrow spike sitting
    on the axis with a ripple beside it. The centre bin holds exactly one
    pixel and so keeps radius 0 and the true peak; every other bin is now
    plotted where its samples actually are."""
    n = intensity_2d.shape[0]
    idx = np.arange(n) - center
    r_exact = np.hypot(idx[:, None], idx[None, :])
    r_pix = np.rint(r_exact).astype(np.intp)
    flat = r_pix.ravel()
    counts = np.bincount(flat)
    sums = np.bincount(flat, weights=intensity_2d.ravel())
    radii = np.bincount(flat, weights=r_exact.ravel())
    return sums[:center] / counts[:center], radii[:center] / counts[:center]
