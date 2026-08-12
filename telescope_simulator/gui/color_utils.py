"""Approximate visible-light wavelength -> RGB color, for the optional
"color beam by wavelength" display mode."""
from __future__ import annotations

from typing import Tuple

PALE_PINK = (255, 182, 193)  # displayed for wavelengths beyond the visible red edge (>700nm)
VIOLET = (148, 0, 211)  # displayed for wavelengths beyond the visible violet edge (<400nm)


def wavelength_to_rgb(wavelength_nm: float, gamma: float = 0.8) -> Tuple[int, int, int]:
    """Approximate RGB color for a visible-light wavelength (piecewise linear
    in each color band, per the well-known Dan Bruton algorithm), with two
    explicit out-of-band cases: pale pink above 700nm, violet below 400nm."""
    if wavelength_nm > 700:
        return PALE_PINK
    if wavelength_nm < 400:
        return VIOLET

    wl = float(wavelength_nm)
    if wl < 440:
        r, g, b = -(wl - 440) / (440 - 400), 0.0, 1.0
    elif wl < 490:
        r, g, b = 0.0, (wl - 440) / (490 - 440), 1.0
    elif wl < 510:
        r, g, b = 0.0, 1.0, -(wl - 510) / (510 - 490)
    elif wl < 580:
        r, g, b = (wl - 510) / (580 - 510), 1.0, 0.0
    elif wl < 645:
        r, g, b = 1.0, -(wl - 645) / (645 - 580), 0.0
    else:
        r, g, b = 1.0, 0.0, 0.0

    if wl < 420:
        factor = 0.3 + 0.7 * (wl - 400) / (420 - 400)
    elif wl < 645:
        factor = 1.0
    else:
        factor = 0.3 + 0.7 * (700 - wl) / (700 - 645)

    def adjust(c: float) -> int:
        if c <= 0.0:
            return 0
        return int(round(255 * (c * factor) ** gamma))

    return (adjust(r), adjust(g), adjust(b))
