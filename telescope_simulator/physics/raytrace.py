"""Real (non-paraxial) geometric ray tracing through the same optic list
`physics/system.py` propagates a Gaussian beam through -- this is the v2.0
"spherical aberration" engine (see TODO.md).

Scope-defining fact this module leans on: the app is strictly axis-aligned,
with no tilt/decenter anywhere in the model (see README "Known limitations").
For an on-axis source through a rotationally symmetric system, a ray's
optical path length depends only on its launch height (pupil radius), never
on azimuth -- a ray at (rho, phi) traces identically to one at (rho, 0) up to
a trivial rotation about the axis. So a single **meridional ray fan** (all
rays in one plane containing the axis, varying only launch height `r`, signed
so the fan covers both sides of the axis) fully characterizes the system.
This keeps the whole engine 2D (z, r) instead of a full 3D skew-ray tracer,
consistent with everything else in `physics/` -- see `physics/zernike.py`'s
docstring for the corresponding consequence on the Zernike fit.

Two things this module deliberately does NOT do (confirmed with the user
before implementing, not silently assumed):
- Total internal reflection stops the ray at the TIR surface; the reflected
  path is not traced further. Modeling the bounce would turn this into a
  non-sequential tracer (rays potentially re-entering earlier optics) -- a
  much bigger undertaking than the rest of the ask, which is inherently
  sequential (rays march forward optic-by-optic, exactly like
  `OpticalSystem.propagate()`).
- A ray whose intersection with a surface falls outside that optic's clear
  aperture (`diameter_full / 2`) is marked vignetted and stops there (per
  the TODO: "should end at the z location of the optic they fail to
  intersect"). This is the first place aperture clipping appears in this
  app -- the existing Gaussian/ABCD model still draws its envelope
  regardless of aperture, unchanged, per its own documented limitations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..model.beam_spec import InputBeamSpec
from ..model.optics import Optic

Vec2 = Tuple[float, float]  # (z, r)

# Two surfaces are "in contact" when their vertices coincide to within this:
# a cemented doublet, or any composite group laid out with zero spacing. It
# is a numerical tolerance, not a physical gap -- 1 picometre, five orders
# above the double-precision noise in the intersection arithmetic at
# millimetre scales and far below anything optical.
SURFACE_CONTACT_TOL_MM = 1e-9


@dataclass
class RaySegment:
    """One straight-line leg of a traced ray, within one homogeneous medium."""

    z0: float
    r0: float
    z1: float
    r1: float
    direction: Vec2  # unit vector (dz, dr)
    n_medium: float
    opl_at_start: float  # accumulated optical path length at (z0, r0)

    def opl_at(self, z: float) -> float:
        """OPL at any z on (or beyond) this segment's line, extrapolating
        past z1 if needed -- same 'a segment's own beam/line is valid beyond
        the window a particular trace happened to bound it to' precedent as
        `physics.system.segment_covering`."""
        dz = self.direction[0]
        if abs(dz) < 1e-12:
            return self.opl_at_start
        t = (z - self.z0) / dz
        return self.opl_at_start + self.n_medium * t

    def r_at(self, z: float) -> float:
        dz = self.direction[0]
        if abs(dz) < 1e-12:
            return self.r0
        t = (z - self.z0) / dz
        return self.r0 + t * self.direction[1]


@dataclass
class RayPath:
    r_launch: float  # signed launch height at the beam's z_ref plane
    segments: List[RaySegment] = field(default_factory=list)
    status: str = "ok"  # "ok" | "vignetted" | "tir"
    stop_label: str = ""  # human-readable surface name, set when status != "ok"

    @property
    def stop_z(self) -> float:
        return self.segments[-1].z1

    def reaches(self, z: float) -> bool:
        """Whether this ray is still physically present at `z` -- False past
        a vignetting/TIR stop point, True for any z >= launch otherwise
        (an 'ok' ray is assumed to continue in a straight line forever, same
        as the Gaussian model's trailing segment)."""
        if z < self.segments[0].z0:
            return False
        return self.status == "ok" or z <= self.stop_z + 1e-9

    def opl_at(self, z: float) -> float:
        for seg in self.segments:
            if seg.z0 - 1e-9 <= z <= seg.z1 + 1e-9:
                return seg.opl_at(z)
        if z < self.segments[0].z0:
            return self.segments[0].opl_at(z)
        return self.segments[-1].opl_at(z)

    def r_at(self, z: float) -> float:
        for seg in self.segments:
            if seg.z0 - 1e-9 <= z <= seg.z1 + 1e-9:
                return seg.r_at(z)
        if z < self.segments[0].z0:
            return self.segments[0].r_at(z)
        return self.segments[-1].r_at(z)


@dataclass
class RayFanResult:
    paths: List[RayPath]
    pupil_radius_mm: float  # nominal fan half-width the launch heights span
    wavelength_nm: float
    # z of the last optical surface the fan passes through (the back vertex
    # of the last optic, or the launch plane for an empty system). This is
    # the app's stand-in for the exit pupil plane -- the only plane a
    # Fraunhofer propagation to the target may legitimately start from.
    exit_plane_z: float = 0.0


def _wavefront_direction(r: float, r_ref_curvature: Optional[float]) -> Vec2:
    """Unit (dz, dr) for a ray launched at height `r` on a spherical
    wavefront of radius of curvature `r_ref_curvature` (None/inf = flat,
    i.e. collimated). Exact (not paraxial): a spherical wavefront's rays are
    exactly radial lines through its center of curvature, so
    dr/dz = r / R for *any* r, not just small r -- see module docstring's
    sibling derivation in the implementation notes. Uses the Gaussian-beam
    convention for R (matches physics.beam.GaussianBeam.radius_of_curvature):
    positive R means a diverging wavefront (center of curvature behind the
    launch plane)."""
    if r_ref_curvature is None or math.isinf(r_ref_curvature):
        return (1.0, 0.0)
    if r_ref_curvature == 0.0:
        # Same "fail loudly and catchably rather than ZeroDivisionError"
        # precedent as the r1/r2 == 0.0 guard in _trace_one_surface and as
        # physics.beam.GaussianBeam.from_measurement's identical check. The
        # Beam tab's spin box repairs 0 on entry, but InputBeamSpec.from_dict
        # does not, so a hand-edited project file reaches here.
        raise ValueError(
            "The input beam's wavefront radius of curvature at z_ref is exactly zero "
            "(a point has no defined curvature); use a non-zero radius, or mark the beam collimated."
        )
    slope = r / r_ref_curvature
    norm = math.hypot(1.0, slope)
    return (1.0 / norm, slope / norm)


def _refract(d: Vec2, normal: Vec2, n1: float, n2: float) -> Optional[Vec2]:
    """Vector Snell's law. `normal` is auto-flipped to oppose `d` (so the
    caller doesn't need to know which way a given surface's raw normal
    happens to point). Returns None for total internal reflection."""
    cos_i = -(d[0] * normal[0] + d[1] * normal[1])
    if cos_i < 0.0:
        normal = (-normal[0], -normal[1])
        cos_i = -cos_i
    eta = n1 / n2
    sin2_t = eta * eta * (1.0 - cos_i * cos_i)
    if sin2_t > 1.0:
        return None
    cos_t = math.sqrt(max(0.0, 1.0 - sin2_t))
    k = eta * cos_i - cos_t
    tz = eta * d[0] + k * normal[0]
    tr = eta * d[1] + k * normal[1]
    norm = math.hypot(tz, tr)
    return (tz / norm, tr / norm)


def _intersect_surface(z0: float, r0: float, d: Vec2, vertex_z: float, radius: float) -> Optional[Vec2]:
    """Nearest forward intersection (t > 0) of the ray with a spherical (or,
    for infinite radius, flat) surface of vertex `vertex_z` and
    radius-of-curvature `radius` (matrices.py convention: positive if the
    center of curvature is on the +z side of the vertex). Returns the hit
    point (z, r), or None if the ray does not reach the surface going
    forward.

    A refracting surface is only the *cap* of its sphere that contains the
    vertex, never the whole sphere -- so of the (up to) two forward roots,
    only the one on the vertex side of the center of curvature is a real
    surface; the other is the phantom rear hemisphere. Taking simply the
    nearest forward root is right for R > 0 (the ray meets the vertex-side
    cap first) but wrong for every R < 0 surface, whose sphere spans
    [vertex_z - 2|R|, vertex_z]: a ray starting further than 2|R| upstream
    meets the phantom hemisphere first, and refracting there put the bend up
    to 2|R| in front of the glass (a plano-concave lens then *converged*
    the beam). Hence the explicit vertex-side test rather than min(t)."""
    dz, dr = d
    if math.isinf(radius):
        if abs(dz) < 1e-12:
            return None
        t = (vertex_z - z0) / dz
        if t < -SURFACE_CONTACT_TOL_MM:
            return None
        return (vertex_z, r0 + t * dr)

    cz = vertex_z + radius
    r_abs = abs(radius)
    ox, oy = z0 - cz, r0
    b = ox * dz + oy * dr
    c = ox * ox + oy * oy - r_abs * r_abs
    disc = b * b - c
    if disc < 0.0:
        return None
    sq = math.sqrt(disc)
    # `t >= 0` rather than `t > eps`: a ray may legitimately start *on* the
    # surface it is about to meet. With zero spacing between two elements the
    # previous optic's back surface and this one's front surface are the same
    # sphere, so the root comes out at exactly 0 -- and an eps of 1e-9
    # discarded it, stopping every ray in the fan, the axial one included, at
    # the cemented interface. Nothing here needs protecting against
    # re-finding the surface just left: the trace is strictly sequential
    # (front, back, next front) and never asks for the same surface twice.
    for t in sorted(t for t in (-b - sq, -b + sq) if t >= -SURFACE_CONTACT_TOL_MM):
        hit_z = z0 + t * dz
        # The vertex sits at cz - radius, so the physical cap is the side of
        # the center with (hit_z - cz) opposite in sign to `radius`.
        if (hit_z - cz) * radius <= 0.0:
            return (hit_z, r0 + t * dr)
    return None


def _surface_normal(hit: Vec2, vertex_z: float, radius: float) -> Vec2:
    if math.isinf(radius):
        return (1.0, 0.0)
    cz = vertex_z + radius
    r_abs = abs(radius)
    return ((hit[0] - cz) / r_abs, hit[1] / r_abs)


def _trace_one_surface(path: RayPath, cur: Vec2, d: Vec2, opl: float,
                        vertex_z: float, radius: float, half_aperture: float,
                        n1: float, n2: float, surface_label: str) -> Optional[Tuple[Vec2, Vec2, float]]:
    """Advance `path` through one refracting surface. Returns the new
    (position, direction, opl) on success, or None if the path was
    terminated (vignetted/TIR) -- the caller should stop tracing this ray
    when None comes back; `path` itself is already updated either way."""
    if radius == 0.0:
        # A momentary r1/r2 == 0.0 (e.g. a GUI spin box mid-edit) must fail
        # loudly and catchably here too, matching
        # physics.matrices.interface()'s identical precedent -- left
        # unguarded, this degrades into an opaque ZeroDivisionError deep
        # inside _surface_normal's division by abs(radius).
        raise ValueError(
            f"Optic '{surface_label}' has a surface radius of curvature of exactly zero "
            "(a point has no defined curvature)."
        )
    hit = _intersect_surface(cur[0], cur[1], d, vertex_z, radius)
    if hit is None or abs(hit[1]) > half_aperture:
        # Vignetted (or, degenerately, no forward intersection at all): the
        # ray is drawn continuing undeviated up to this optic's front-vertex
        # z, per the TODO's "should end at the z location of the optic they
        # fail to intersect".
        length = (vertex_z - cur[0]) / d[0] if abs(d[0]) > 1e-12 else 0.0
        end = (vertex_z, cur[1] + length * d[1])
        path.segments.append(RaySegment(cur[0], cur[1], end[0], end[1], d, n1, opl))
        path.status = "vignetted"
        path.stop_label = surface_label
        return None

    seg_len = math.hypot(hit[0] - cur[0], hit[1] - cur[1])
    normal = _surface_normal(hit, vertex_z, radius)
    refracted = _refract(d, normal, n1, n2)
    if refracted is None:
        path.segments.append(RaySegment(cur[0], cur[1], hit[0], hit[1], d, n1, opl))
        path.status = "tir"
        path.stop_label = surface_label
        return None

    path.segments.append(RaySegment(cur[0], cur[1], hit[0], hit[1], d, n1, opl))
    return hit, refracted, opl + n1 * seg_len


def _check_traceable(optic: Optic) -> None:
    """Reject an optic whose two surfaces coincide on the axis, before any
    ray is launched at it.

    The paraxial thick-lens matrix tolerates a zero center thickness (that's
    just its thin-lens limit) and the Optics tab's spin box lets one be
    typed, but real geometric tracing cannot: the back vertex then sits at
    or behind the front surface, no forward intersection with the back
    surface exists for *any* ray, and every one of them -- the axial ray
    included -- comes back "vignetted". The caller's next step,
    wavefront_at(), then reports "the axial ray does not reach z=...", which
    describes a symptom several steps removed from the cause. Naming the
    geometry here is the difference between an error the user can act on and
    one they can't.

    Deliberately not checked: a negative *edge* thickness. Surfaces that
    cross somewhere out near the rim still trace correctly over the inner
    bundle the fan actually occupies, and rays that do reach the crossed
    region are legitimately reported as vignetted."""
    if optic.thickness_center <= 0.0:
        raise ValueError(
            f"Optic '{optic.name}' has a center thickness of {optic.thickness_center:g} mm; "
            "ray tracing needs a real (positive) thickness, since its front and back surfaces "
            "would otherwise coincide on the axis."
        )


def trace_ray(r_launch: float, beam_spec: InputBeamSpec, optics_sorted: List[Optic],
              ambient_index: float = 1.0) -> RayPath:
    """Trace one meridional ray, launched at signed height `r_launch` on the
    input beam's wavefront at `beam_spec.z_ref`, through `optics_sorted`
    (must already be sorted by z, as `OpticalSystem.optics` is)."""
    path = RayPath(r_launch=r_launch)
    r_ref_curvature = None if beam_spec.collimated else beam_spec.r_ref
    d = _wavefront_direction(r_launch, r_ref_curvature)
    cur: Vec2 = (beam_spec.z_ref, r_launch)
    opl = 0.0

    n_medium = ambient_index
    for index, optic in enumerate(optics_sorted):
        if optic.z < cur[0] - 1e-9:
            raise ValueError(
                f"Optic '{optic.name}' front surface (z={optic.z}) precedes the ray's current "
                f"position (z={cur[0]}); optics must not overlap the beam."
            )
        _check_traceable(optic)
        half_aperture = optic.diameter_full / 2.0

        result = _trace_one_surface(
            path, cur, d, opl, optic.z, optic.r1, half_aperture, n_medium, optic.n, optic.name,
        )
        if result is None:
            return path
        cur, d, opl = result

        z_back = optic.z + optic.thickness_center
        # A zero air gap is a cemented joint, not an infinitesimally thin
        # sliver of air, so refract straight into the next glass. Snell's law
        # composes -- n1 sin1 = n_air sin_air = n2 sin2 -- so the direction is
        # the same either way and this changes nothing in the ordinary case.
        # What it removes is a failure mode: detouring through the ambient
        # index can total-internally-reflect at an angle a real cemented joint
        # passes without trouble, stopping the ray at an air surface that does
        # not physically exist.
        nxt = optics_sorted[index + 1] if index + 1 < len(optics_sorted) else None
        in_contact = nxt is not None and abs(nxt.z - z_back) <= SURFACE_CONTACT_TOL_MM
        n_next = nxt.n if in_contact else ambient_index

        result = _trace_one_surface(
            path, cur, d, opl, z_back, optic.r2, half_aperture, optic.n, n_next, optic.name,
        )
        if result is None:
            return path
        cur, d, opl = result
        n_medium = n_next

    # Trailing straight-line segment, extrapolated to arbitrary z by
    # RaySegment.opl_at/r_at -- mirrors physics.system's "output" segment,
    # just without a fixed plotted length (the GUI layer decides how far to
    # draw it, same as it already decides the Gaussian curve's trailing
    # padding).
    far_z = cur[0] + 1.0e7
    far_r = cur[1] + 1.0e7 * d[1] if abs(d[0]) > 1e-12 else cur[1]
    path.segments.append(RaySegment(cur[0], cur[1], far_z, far_r, d, ambient_index, opl))
    return path


def trace_fan(beam_spec: InputBeamSpec, optics: List[Optic], ambient_index: float = 1.0,
              ray_count: int = 21, pupil_radius_mm: Optional[float] = None) -> RayFanResult:
    """Trace a symmetric meridional ray fan (heights from -pupil_radius_mm to
    +pupil_radius_mm, `ray_count` rays). `pupil_radius_mm` defaults to a
    multiple of the input beam's 1/e^2 radius at z_ref, clipped to the first
    optic's clear aperture when there is one (so the fan doesn't needlessly
    extend past what any optic could ever pass).

    `ray_count` is rounded up to the next odd number so the fan always
    contains the axial (rho = 0) ray. wavefront_at() references every OPD to
    that ray, and the Config tab documents the count as odd for exactly this
    reason -- but its spin box still accepts a *typed* even value, so the
    invariant has to be enforced where it's relied on, not only where it's
    entered."""
    optics_sorted = sorted(optics, key=lambda o: o.z)
    if pupil_radius_mm is None:
        pupil_radius_mm = 2.5 * beam_spec.w_ref
        if optics_sorted:
            pupil_radius_mm = min(pupil_radius_mm, optics_sorted[0].diameter_full / 2.0)
    ray_count = max(int(ray_count), 3)
    if ray_count % 2 == 0:
        ray_count += 1

    heights = [
        -pupil_radius_mm + 2.0 * pupil_radius_mm * i / (ray_count - 1)
        for i in range(ray_count)
    ]

    exit_plane_z = beam_spec.z_ref
    if optics_sorted:
        exit_plane_z = max(o.z + o.thickness_center for o in optics_sorted)

    paths = [trace_ray(h, beam_spec, optics_sorted, ambient_index) for h in heights]
    return RayFanResult(
        paths=paths,
        pupil_radius_mm=pupil_radius_mm,
        wavelength_nm=beam_spec.wavelength_nm,
        exit_plane_z=exit_plane_z,
    )


@dataclass
class WavefrontSample:
    rho_mm: List[float]  # signed launch height of each surviving ray
    opd_mm: List[float]  # optical path difference vs. the axial ray, same units
    n_total: int  # rays in the fan
    n_surviving: int
    # Half-width of the *surviving* part of the fan, not the launched fan --
    # the only radius the OPD samples actually cover, and therefore the only
    # correct normalization radius for a Zernike fit over them.
    pupil_radius_mm: float = 0.0
    # The same surviving bundle measured at the fan's exit plane: the
    # physical aperture that diffracts, and the plane the PSF propagates
    # from. Both are needed because the wavefront is parameterized by launch
    # height while diffraction happens at the exit pupil.
    exit_pupil_radius_mm: float = 0.0
    exit_pupil_z: float = 0.0


def wavefront_at(result: RayFanResult, target_z: float) -> WavefrontSample:
    """Wavefront error of the bundle that still exists at `target_z`,
    measured in the conventional way: against a reference sphere centred on
    the axial ray's arrival point and passing through the exit pupil.

    The reference matters, and getting it wrong is invisible in the plot.
    The obvious quantity -- optical path difference measured at the target
    *plane*, referenced to the axial ray there -- is easy to compute and
    agrees with this one exactly at best focus, which is what makes the
    difference so easy to miss. Away from focus the two differ by a defocus
    term in the ratio (distance to target)/(distance to focus), and it is
    this one, not the plane-referenced one, that is the pupil phase a
    Fraunhofer propagation needs: a PSF built on the plane-referenced OPD
    comes out steadily too wide with defocus (a factor of two by ten
    Rayleigh ranges out) while still looking perfectly plausible.

    The conversion, for a ray leaving the exit plane at height `xi` and
    landing at height `r` a distance `L` downstream, is
    `W = OPD_plane + n*(xi^2 - (r - xi)^2)/(2L)`: the first term removes the
    pupil-to-plane path the OPD picked up, the second adds the Fresnel
    kernel's own quadratic, which together turn a plane-referenced path
    difference into a sphere-referenced one. Both pieces vanish when the
    rays converge to a point (r = 0 and xi = 0 respectively), which is why
    the two agree at focus.

    A target at or in front of the exit plane has no such reference sphere
    (there is no propagation distance to build one over, and the rays have
    not finished refracting), so the plane-referenced OPD is reported there
    instead. Nothing downstream diffracts from it -- psf_radial_profile
    refuses that case outright -- and the Zernike fit and wavefront plot
    remain perfectly meaningful.

    Vignetted rays are dropped, so the returned `pupil_radius_mm` is the
    largest launch height that actually survived, *not* the fan's nominal
    half-width. Normalizing a Zernike fit by the launched half-width when a
    stop has cut the bundle down would fit the polynomial over rho_norm in
    (say) [0, 0.3] and then let callers extrapolate it out to 1.0 -- the
    reported wavefront and every PSF derived from it would describe an
    aperture the light never filled."""
    axial = min(result.paths, key=lambda p: abs(p.r_launch))
    if not axial.reaches(target_z):
        # Say which surface stopped it and how: "the axial ray does not
        # reach the target" on its own is a symptom, and the user has no way
        # to tell a too-small aperture from total internal reflection from a
        # degenerate optic without it.
        where = f" at '{axial.stop_label}'" if axial.stop_label else ""
        how = {"vignetted": "vignetted (it missed the clear aperture)", "tir": "totally internally reflected"}
        raise ValueError(
            f"The axial ray does not reach z={target_z}: it was "
            f"{how.get(axial.status, axial.status)}{where}, at z={axial.stop_z:g}."
        )
    opl_axial = axial.opl_at(target_z)

    exit_z = result.exit_plane_z
    distance = target_z - exit_z

    rho, opd = [], []
    exit_radius = 0.0
    for p in result.paths:
        if p.reaches(target_z):
            xi = p.r_at(exit_z)
            plane_opd = p.opl_at(target_z) - opl_axial
            if distance > 0.0:
                r = p.r_at(target_z)
                n = p.segments[-1].n_medium if p.segments else 1.0
                plane_opd += n * (xi * xi - (r - xi) ** 2) / (2.0 * distance)
            rho.append(p.r_launch)
            opd.append(plane_opd)
            exit_radius = max(exit_radius, abs(xi))
    return WavefrontSample(
        rho_mm=rho,
        opd_mm=opd,
        n_total=len(result.paths),
        n_surviving=len(rho),
        pupil_radius_mm=max((abs(r) for r in rho), default=0.0),
        exit_pupil_radius_mm=exit_radius,
        exit_pupil_z=result.exit_plane_z,
    )
