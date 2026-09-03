"""Small widget-construction helpers shared by `optics_tab.py` and the
"Add optic" dialog, so both build their mm-valued spin boxes and horizontal
widget rows the same way instead of each keeping its own copy."""
from __future__ import annotations

from pyqtgraph.Qt import QtWidgets


def mm_spin(lo: float, hi: float) -> QtWidgets.QDoubleSpinBox:
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(4)
    s.setSuffix(" mm")
    return s


def wrap_row(*widgets: QtWidgets.QWidget) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    row = QtWidgets.QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        row.addWidget(widget)
    return w
