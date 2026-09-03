from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SystemConfig:
    plot_leading_padding_mm: float = 20.0  # shown before the input reference plane
    plot_trailing_padding_zr_multiple: float = 3.0  # * output Rayleigh range
    plot_trailing_padding_min_mm: float = 20.0
    beam_curve_points_per_segment: int = 200
    show_waist_markers: bool = True
    show_rayleigh_shading: bool = False

    # View / aspect ratio (x-span / z-span). Locked by default at 0.3 so the
    # transverse beam size stays readable against much larger z spans.
    lock_aspect_ratio: bool = True
    aspect_ratio: float = 0.3

    # Default/reset view range. None means "auto" (derived from beam extent
    # and the padding fields above), matching the pre-v0.2 behavior.
    z_range_min: Optional[float] = None
    z_range_max: Optional[float] = None
    x_range_min: Optional[float] = None
    x_range_max: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plot_leading_padding_mm": self.plot_leading_padding_mm,
            "plot_trailing_padding_zr_multiple": self.plot_trailing_padding_zr_multiple,
            "plot_trailing_padding_min_mm": self.plot_trailing_padding_min_mm,
            "beam_curve_points_per_segment": self.beam_curve_points_per_segment,
            "show_waist_markers": self.show_waist_markers,
            "show_rayleigh_shading": self.show_rayleigh_shading,
            "lock_aspect_ratio": self.lock_aspect_ratio,
            "aspect_ratio": self.aspect_ratio,
            "z_range_min": self.z_range_min,
            "z_range_max": self.z_range_max,
            "x_range_min": self.x_range_min,
            "x_range_max": self.x_range_max,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SystemConfig":
        return cls(
            plot_leading_padding_mm=d.get("plot_leading_padding_mm", 20.0),
            plot_trailing_padding_zr_multiple=d.get("plot_trailing_padding_zr_multiple", 3.0),
            plot_trailing_padding_min_mm=d.get("plot_trailing_padding_min_mm", 20.0),
            beam_curve_points_per_segment=d.get("beam_curve_points_per_segment", 200),
            show_waist_markers=d.get("show_waist_markers", True),
            show_rayleigh_shading=d.get("show_rayleigh_shading", False),
            lock_aspect_ratio=d.get("lock_aspect_ratio", True),
            aspect_ratio=d.get("aspect_ratio", 0.3),
            z_range_min=d.get("z_range_min"),
            z_range_max=d.get("z_range_max"),
            x_range_min=d.get("x_range_min"),
            x_range_max=d.get("x_range_max"),
        )
