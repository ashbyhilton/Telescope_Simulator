from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OpticKind(Enum):
    PLANO_CONVEX = "plano-convex"
    PLANO_CONCAVE = "plano-concave"
    PLANO_PLANO = "plano-plano"
    BICONVEX = "biconvex"
    BICONCAVE = "biconcave"
    CUSTOM = "custom"


_id_counter = itertools.count(1)

# Sign convention: R > 0 if the surface's center of curvature lies on the
# +z side of its vertex. These defaults produce a converging lens for the
# convex kinds and a diverging lens for the concave kinds (verified against
# the thin-lens equation in tests/test_matrices.py).
_KIND_DEFAULTS: Dict[OpticKind, Dict[str, float]] = {
    OpticKind.PLANO_CONVEX: dict(r1=50.0, r2=float("inf")),
    OpticKind.PLANO_CONCAVE: dict(r1=-50.0, r2=float("inf")),
    OpticKind.PLANO_PLANO: dict(r1=float("inf"), r2=float("inf")),
    OpticKind.BICONVEX: dict(r1=50.0, r2=-50.0),
    OpticKind.BICONCAVE: dict(r1=-50.0, r2=50.0),
    OpticKind.CUSTOM: dict(r1=float("inf"), r2=float("inf")),
}


@dataclass
class Optic:
    name: str
    kind: OpticKind = OpticKind.CUSTOM
    diameter_full: float = 25.4  # mm, clear/full aperture
    thickness_center: float = 5.0  # mm
    r1: float = float("inf")  # mm, front surface radius of curvature
    r2: float = float("inf")  # mm, back surface radius of curvature
    n: float = 1.5168  # refractive index (N-BK7 @ 587.6nm by default)
    z: float = 0.0  # mm, global position of the front-surface vertex
    lock_z: bool = False
    group_id: Optional[int] = None  # None = standalone; a shared value means these
    # Optic instances are members of one rigid "composite lens" group (see
    # gui/dialogs/add_optic_dialog.py) -- they are dragged/removed together as
    # one unit. The group's id is simply the id of its first (frontmost)
    # member; no separate id counter is needed.
    group_name: str = ""  # display name, duplicated on every member for simplicity
    id: int = field(default_factory=lambda: next(_id_counter))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "diameter_full": self.diameter_full,
            "thickness_center": self.thickness_center,
            "r1": self.r1,
            "r2": self.r2,
            "n": self.n,
            "z": self.z,
            "lock_z": self.lock_z,
            "group_id": self.group_id,
            "group_name": self.group_name,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Optic":
        optic = cls(
            name=d["name"],
            kind=OpticKind(d.get("kind", OpticKind.CUSTOM.value)),
            diameter_full=d.get("diameter_full", 25.4),
            thickness_center=d.get("thickness_center", 5.0),
            r1=d.get("r1", float("inf")),
            r2=d.get("r2", float("inf")),
            n=d.get("n", 1.5168),
            z=d.get("z", 0.0),
            lock_z=d.get("lock_z", False),
            group_id=d.get("group_id"),
            group_name=d.get("group_name", ""),
        )
        if "id" in d:
            optic.id = d["id"]
        return optic


def make_default_optic(kind: OpticKind, name: str, z: float = 0.0) -> Optic:
    """Create a new optic of `kind` with sensible preset radii, for the
    Optics tab's "add new" action. All fields remain fully editable
    afterwards."""
    defaults = _KIND_DEFAULTS[kind]
    return Optic(name=name, kind=kind, z=z, **defaults)


def group_key(optic: "Optic") -> int:
    """Canonical selection/list-row key: an optic's own id if standalone, or
    its composite group's id (shared by every member) otherwise. Using this
    everywhere a UI needs to key on "this optic or its group" means a
    standalone optic (the overwhelmingly common case) behaves identically to
    before group_id existed."""
    return optic.group_id if optic.group_id is not None else optic.id


def describe_shape(r1: float, r2: float) -> str:
    """Human-readable lens shape derived from *live* r1/r2, using the same
    sign convention as `_KIND_DEFAULTS` (R > 0 if the surface's center of
    curvature lies on the +z side of its vertex). `Optic.kind` is only a
    write-once creation preset and is never recomputed as r1/r2 are edited,
    so this is the only reliable "what shape is this *right now*" readout."""
    front_flat = math.isinf(r1)
    back_flat = math.isinf(r2)
    if front_flat and back_flat:
        return "Plano-plano (flat window)"
    front_convex = (not front_flat) and r1 > 0
    back_convex = (not back_flat) and r2 < 0
    if front_flat:
        return "Plano-convex" if back_convex else "Plano-concave"
    if back_flat:
        return "Plano-convex" if front_convex else "Plano-concave"
    if front_convex and back_convex:
        return "Biconvex"
    if not front_convex and not back_convex:
        return "Biconcave"
    return "Meniscus"


def surface_sag(radius: float, x: float) -> float:
    """Sag of a spherical surface at radial coordinate `x`, relative to its
    own vertex (i.e. with the vertex placed at z=0) -- same sign convention
    as everywhere else in this module (R > 0 if the center of curvature lies
    on the +z side of the vertex). 0.0 for a flat (infinite-radius) surface,
    per this app's confirmed "flat contributes no sag" rule. Pure geometry,
    reused by both `gui/optic_item.py`'s rendering and the edge/center
    thickness coupling below -- don't re-derive this elsewhere."""
    if math.isinf(radius):
        return 0.0
    r_eff = abs(radius)
    x_clamped = min(abs(x), 0.999 * r_eff)
    return radius - math.copysign(1.0, radius) * math.sqrt(r_eff * r_eff - x_clamped * x_clamped)


def edge_thickness_from_center(r1: float, r2: float, diameter_full: float, thickness_center: float) -> float:
    """The lens thickness at the clear-aperture edge, derived from its
    center thickness and both surfaces' sag at the edge radius. Both sag
    terms are 0 for flat surfaces, so a flat-flat window's edge thickness
    always equals its center thickness."""
    half_d = diameter_full / 2.0
    return thickness_center + surface_sag(r2, half_d) - surface_sag(r1, half_d)


def center_thickness_from_edge(r1: float, r2: float, diameter_full: float, thickness_edge: float) -> float:
    """Inverse of `edge_thickness_from_center` -- linear in the thickness
    term, so no iterative solve is needed."""
    half_d = diameter_full / 2.0
    return thickness_edge - surface_sag(r2, half_d) + surface_sag(r1, half_d)


def layout_group_z(elements: List["Optic"], spacings_mm: List[float], anchor_z: float = 0.0) -> List[float]:
    """Absolute front-vertex z for each element of a composite-lens chain:
    element 0 at `anchor_z`, each subsequent element after the previous
    one's `thickness_center` plus the air gap in `spacings_mm` (length
    len(elements)-1, spacing after element i). Mirrors the z_cursor-advance
    arithmetic `physics.system.OpticalSystem.propagate()` already does for a
    flat optics list -- a composite group must lay out to the exact z
    positions physics will later re-derive independently from those values,
    so this is the one place that arithmetic is written."""
    zs = []
    z = anchor_z
    for i, element in enumerate(elements):
        zs.append(z)
        z += element.thickness_center
        if i < len(spacings_mm):
            z += spacings_mm[i]
    return zs
