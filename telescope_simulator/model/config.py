from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class SystemConfig:
    plot_leading_padding_mm: float = 20.0  # shown before the input reference plane
    plot_trailing_padding_zr_multiple: float = 3.0  # * output Rayleigh range
    plot_trailing_padding_min_mm: float = 20.0
    beam_curve_points_per_segment: int = 200
    show_waist_markers: bool = True
    show_rayleigh_shading: bool = True
    equal_aspect: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plot_leading_padding_mm": self.plot_leading_padding_mm,
            "plot_trailing_padding_zr_multiple": self.plot_trailing_padding_zr_multiple,
            "plot_trailing_padding_min_mm": self.plot_trailing_padding_min_mm,
            "beam_curve_points_per_segment": self.beam_curve_points_per_segment,
            "show_waist_markers": self.show_waist_markers,
            "show_rayleigh_shading": self.show_rayleigh_shading,
            "equal_aspect": self.equal_aspect,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SystemConfig":
        return cls(
            plot_leading_padding_mm=d.get("plot_leading_padding_mm", 20.0),
            plot_trailing_padding_zr_multiple=d.get("plot_trailing_padding_zr_multiple", 3.0),
            plot_trailing_padding_min_mm=d.get("plot_trailing_padding_min_mm", 20.0),
            beam_curve_points_per_segment=d.get("beam_curve_points_per_segment", 200),
            show_waist_markers=d.get("show_waist_markers", True),
            show_rayleigh_shading=d.get("show_rayleigh_shading", True),
            equal_aspect=d.get("equal_aspect", False),
        )
