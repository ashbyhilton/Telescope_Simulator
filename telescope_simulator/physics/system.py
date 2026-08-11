from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..model.beam_spec import InputBeamSpec
from ..model.optics import Optic
from .beam import GaussianBeam, transform_q
from .matrices import interface


@dataclass
class BeamSegment:
    """A piece of the propagation path within one homogeneous medium."""

    beam: GaussianBeam
    z_start: float
    z_end: float
    label: str


@dataclass
class SystemResult:
    segments: List[BeamSegment]
    output_beam: GaussianBeam
    next_waist_z: float
    next_waist_diameter: float
    output_rayleigh_range: float
    output_divergence_half_angle: float
    diameter_one_zr_past_last_optic: float
    output_q: complex
    last_surface_z: float


class OpticalSystem:
    """Chains ABCD propagation through an input beam and an ordered list of
    thick lenses, sorted by their front-surface z position."""

    def __init__(self, beam_spec: InputBeamSpec, optics: List[Optic]):
        self.beam_spec = beam_spec
        self.optics = sorted(optics, key=lambda o: o.z)

    def propagate(self, trailing_length: Optional[float] = None) -> SystemResult:
        lam_nm = self.beam_spec.wavelength_nm
        r_ref = None if self.beam_spec.collimated else self.beam_spec.r_ref
        beam = GaussianBeam.from_measurement(
            z_ref=self.beam_spec.z_ref,
            w_ref=self.beam_spec.w_ref,
            wavelength_nm=lam_nm,
            n=1.0,
            r_ref=r_ref,
        )

        segments: List[BeamSegment] = []
        z_cursor = self.beam_spec.z_ref
        last_surface_z = self.beam_spec.z_ref

        for optic in self.optics:
            if optic.z < z_cursor:
                raise ValueError(
                    f"Optic '{optic.name}' front surface (z={optic.z}) overlaps or "
                    f"precedes the beam position (z={z_cursor}); optics must not overlap."
                )
            if optic.z > z_cursor:
                segments.append(BeamSegment(beam=beam, z_start=z_cursor, z_end=optic.z, label="air gap"))

            q_at_front = beam.q_at(optic.z)
            q_inside = transform_q(q_at_front, interface(1.0, optic.n, optic.r1))
            beam_inside = GaussianBeam(z_ref=optic.z, q_ref=q_inside, wavelength_nm=lam_nm, n=optic.n)
            z_back = optic.z + optic.thickness_center
            segments.append(BeamSegment(beam=beam_inside, z_start=optic.z, z_end=z_back, label=optic.name))

            q_at_back_inside = beam_inside.q_at(z_back)
            q_after = transform_q(q_at_back_inside, interface(optic.n, 1.0, optic.r2))
            beam = GaussianBeam(z_ref=z_back, q_ref=q_after, wavelength_nm=lam_nm, n=1.0)
            z_cursor = z_back
            last_surface_z = z_back

        if trailing_length is None:
            trailing_length = max(3.0 * beam.rayleigh_range, 20.0)
        trailing_end = z_cursor + trailing_length
        segments.append(BeamSegment(beam=beam, z_start=z_cursor, z_end=trailing_end, label="output"))

        diameter_one_zr = 2.0 * beam.w(last_surface_z + beam.rayleigh_range)

        return SystemResult(
            segments=segments,
            output_beam=beam,
            next_waist_z=beam.z_waist,
            next_waist_diameter=2.0 * beam.w0,
            output_rayleigh_range=beam.rayleigh_range,
            output_divergence_half_angle=beam.divergence_half_angle,
            diameter_one_zr_past_last_optic=diameter_one_zr,
            output_q=beam.q_ref,
            last_surface_z=last_surface_z,
        )
