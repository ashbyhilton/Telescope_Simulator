from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Union

from .beam_spec import InputBeamSpec
from .config import SystemConfig
from .optics import Optic, OpticKind


@dataclass
class Project:
    beam: InputBeamSpec = field(default_factory=InputBeamSpec)
    optics: List[Optic] = field(default_factory=list)
    config: SystemConfig = field(default_factory=SystemConfig)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "beam": self.beam.to_dict(),
            "optics": [o.to_dict() for o in self.optics],
            "config": self.config.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Project":
        return cls(
            beam=InputBeamSpec.from_dict(d.get("beam", {})),
            optics=[Optic.from_dict(o) for o in d.get("optics", [])],
            config=SystemConfig.from_dict(d.get("config", {})),
        )

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Project":
        return cls.from_dict(json.loads(Path(path).read_text()))


def default_demo_project() -> Project:
    """A small starter system shown on first launch: a collimated HeNe-like
    beam focusing through a single biconvex lens."""
    beam = InputBeamSpec(wavelength_nm=632.8, z_ref=0.0, w_ref=0.5, collimated=True)
    lens = Optic(
        name="Biconvex Lens 1",
        kind=OpticKind.BICONVEX,
        diameter_full=25.4,
        thickness_center=4.0,
        r1=50.0,
        r2=-50.0,
        n=1.5168,
        z=100.0,
    )
    return Project(beam=beam, optics=[lens], config=SystemConfig())
