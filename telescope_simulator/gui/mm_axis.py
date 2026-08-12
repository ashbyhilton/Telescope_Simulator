"""A pg.AxisItem whose underlying data is always in millimeters (matching
the rest of the app), but whose tick labels and unit suffix switch between
um/mm/m/km based on the currently visible span. pyqtgraph's built-in
auto-SI-prefix logic instead naively prepends metric prefixes onto the
literal unit string (e.g. producing "kmm" for a zoomed-out mm axis) since it
isn't aware that our declared unit is already non-base; this subclass does
unit-aware conversion instead."""
from __future__ import annotations

from typing import List, Optional, Tuple

import pyqtgraph as pg

# (upper bound of span in mm, unit label, multiplier from mm to that unit)
_UNIT_BANDS: List[Tuple[float, str, float]] = [
    (1.0, "µm", 1000.0),
    (1000.0, "mm", 1.0),
    (1.0e6, "m", 1.0e-3),
    (float("inf"), "km", 1.0e-6),
]


def _unit_for_span(span_mm: float) -> Tuple[str, float]:
    span_mm = abs(span_mm)
    for threshold, unit, factor in _UNIT_BANDS:
        if span_mm < threshold:
            return unit, factor
    return _UNIT_BANDS[-1][1], _UNIT_BANDS[-1][2]


def format_length_mm(value_mm: float, sig_figs: int = 4) -> str:
    """Format a single length (stored internally in mm) using the same
    um/mm/m/km unit selection as the plot axes, so a readout like the beam
    characteristics panels doesn't show raw millimeters in scientific
    notation (e.g. "3.5e4 mm") for large/small values."""
    unit, factor = _unit_for_span(value_mm)
    converted = value_mm * factor
    return f"{converted:.{sig_figs}g} {unit}"


class MMAxisItem(pg.AxisItem):
    def __init__(self, *args, base_text: str = "", **kwargs):
        self._base_text = base_text
        self._current_unit: Optional[str] = None
        super().__init__(*args, **kwargs)
        self.autoSIPrefix = False
        self._set_unit("mm")

    def _set_unit(self, unit: str) -> None:
        if unit != self._current_unit:
            self._current_unit = unit
            self.setLabel(text=self._base_text, units=unit)

    def setRange(self, mn: float, mx: float) -> None:
        super().setRange(mn, mx)
        unit, _ = _unit_for_span(mx - mn)
        self._set_unit(unit)

    def tickStrings(self, values, scale, spacing):
        span = (self.range[1] - self.range[0]) if self.range else 0.0
        _, factor = _unit_for_span(span)
        strings = []
        for v in values:
            converted = v * factor
            if converted == 0:
                strings.append("0")
            elif abs(converted) >= 100:
                strings.append(f"{converted:.0f}")
            elif abs(converted) >= 10:
                strings.append(f"{converted:.1f}")
            else:
                strings.append(f"{converted:.3g}")
        return strings
