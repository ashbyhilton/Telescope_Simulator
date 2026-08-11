"""Gaussian beam representation via the complex beam parameter q.

All lengths are in millimeters; wavelength is stored/accepted in nanometers
and converted internally. A `GaussianBeam` instance is a value object valid
within a single homogeneous medium (constant refractive index) -- it can be
queried for w(z)/R(z) at any z, but only means what it claims to mean within
the medium it was constructed for. Chaining across interfaces is handled by
`transform_q` plus constructing a fresh `GaussianBeam` on the far side (see
physics/system.py), since the index generally changes there.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .matrices import Matrix


def transform_q(q: complex, matrix: Matrix) -> complex:
    """Apply the generalized ABCD law: q_out = (A*q + B) / (C*q + D)."""
    a, b = matrix[0]
    c, d = matrix[1]
    return (a * q + b) / (c * q + d)


@dataclass
class GaussianBeam:
    z_ref: float
    q_ref: complex
    wavelength_nm: float
    n: float = 1.0

    @property
    def wavelength_mm(self) -> float:
        return self.wavelength_nm * 1e-6

    def q_at(self, z: float) -> complex:
        """q is invariant in form under free propagation within one medium:
        q(z) = q_ref + (z - z_ref)."""
        return self.q_ref + (z - self.z_ref)

    def w(self, z: float) -> float:
        """1/e^2 intensity radius at z."""
        q = self.q_at(z)
        return np.sqrt(-self.wavelength_mm / (self.n * np.pi * (1.0 / q).imag))

    def radius_of_curvature(self, z: float) -> float:
        q = self.q_at(z)
        re = (1.0 / q).real
        if re == 0.0:
            return float("inf")
        return 1.0 / re

    @property
    def rayleigh_range(self) -> float:
        """Im(q) is invariant under free propagation, so this holds at any z."""
        return self.q_ref.imag

    @property
    def z_waist(self) -> float:
        return self.z_ref - self.q_ref.real

    @property
    def w0(self) -> float:
        return self.w(self.z_waist)

    @property
    def divergence_half_angle(self) -> float:
        """Far-field half-angle in radians (paraxial approximation)."""
        return self.wavelength_mm / (self.n * np.pi * self.w0)

    @classmethod
    def from_measurement(
        cls,
        z_ref: float,
        w_ref: float,
        wavelength_nm: float,
        n: float = 1.0,
        r_ref: Optional[float] = None,
    ) -> "GaussianBeam":
        """Construct a beam from a diameter/curvature measured at `z_ref`,
        which need not be the waist. `r_ref=None` (or inf) means a flat
        wavefront (collimated) at `z_ref`.
        """
        lam = wavelength_nm * 1e-6
        if r_ref is None or np.isinf(r_ref):
            inv_r = 0.0
        else:
            inv_r = 1.0 / r_ref
        inv_q = inv_r - 1j * lam / (n * np.pi * w_ref**2)
        q_ref = 1.0 / inv_q
        return cls(z_ref=z_ref, q_ref=q_ref, wavelength_nm=wavelength_nm, n=n)
