"""ABCD ray-transfer matrix builders for paraxial Gaussian beam propagation.

Convention: the ray vector is (y, theta) with theta = dy/dz the *physical*
ray slope (not a reduced angle). Free-space translation therefore does not
carry an index factor -- theta is already the actual slope, so y advances
as y + theta * distance regardless of the medium. Refractive index only
enters at interfaces (via Snell's law, paraxial form) and in the complex
beam parameter's definition (see beam.py). This matches the convention used
in Kogelnik's generalized ABCD law and in Siegman, "Lasers".

Sign convention for radius of curvature: positive if the center of
curvature lies on the +z side of the vertex. Use float('inf') for a flat
surface.
"""
from __future__ import annotations

import numpy as np

Matrix = np.ndarray


def propagation(distance: float) -> Matrix:
    """Free-space (or in-medium) propagation over `distance`."""
    return np.array([[1.0, distance], [0.0, 1.0]])


def interface(n1: float, n2: float, radius: float) -> Matrix:
    """Refraction at a spherical interface going from index n1 into n2."""
    if np.isinf(radius):
        power = 0.0
    elif radius == 0.0:
        raise ValueError("radius of curvature cannot be exactly zero (a point has no defined curvature)")
    else:
        power = (n1 - n2) / (n2 * radius)
    return np.array([[1.0, 0.0], [power, n1 / n2]])


def thick_lens(thickness: float, n_lens: float, r1: float, r2: float, n_ambient: float = 1.0) -> Matrix:
    """Full thick lens: front interface -> propagation through the lens
    material -> back interface, returning to `n_ambient` on both sides.

    Matrix multiplication order is rightmost-applied-first, i.e. this is
    `M_back @ M_prop @ M_front`.
    """
    m_front = interface(n_ambient, n_lens, r1)
    m_prop = propagation(thickness)
    m_back = interface(n_lens, n_ambient, r2)
    return m_back @ m_prop @ m_front
