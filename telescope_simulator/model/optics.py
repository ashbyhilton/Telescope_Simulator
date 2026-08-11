from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


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
    x: float = 0.0  # mm, transverse decenter
    angle_deg: float = 0.0  # tilt of the optic normal relative to +z (cosmetic in v1)
    lock_z: bool = False
    lock_x: bool = False
    lock_angle: bool = False
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
            "x": self.x,
            "angle_deg": self.angle_deg,
            "lock_z": self.lock_z,
            "lock_x": self.lock_x,
            "lock_angle": self.lock_angle,
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
            x=d.get("x", 0.0),
            angle_deg=d.get("angle_deg", 0.0),
            lock_z=d.get("lock_z", False),
            lock_x=d.get("lock_x", False),
            lock_angle=d.get("lock_angle", False),
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
