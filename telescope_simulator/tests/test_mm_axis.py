import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.gui.mm_axis import MMAxisItem, format_length_mm


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_set_unit_relabels_even_when_unit_is_unchanged(qapp):
    """The label must be (re)applied on every setRange() call, not just when
    the unit string changes -- otherwise the very first, construction-time
    label never actually renders (it's set before the widget has real
    on-screen geometry), and nothing forces a fresh layout pass until a zoom
    happens to cross a _UNIT_BANDS threshold."""
    axis = MMAxisItem(orientation="bottom", base_text="z")
    calls = []
    axis.setLabel = lambda **kwargs: calls.append(kwargs)

    axis.setRange(0.0, 10.0)  # still "mm", same as __init__'s initial unit
    axis.setRange(0.0, 20.0)  # still "mm" again

    assert len(calls) == 2


def test_small_value_uses_micrometers():
    assert format_length_mm(0.5) == "500 µm"


def test_millimeter_range_uses_mm():
    assert format_length_mm(35.0) == "35 mm"


def test_large_value_uses_meters_not_scientific_notation():
    text = format_length_mm(3.5e4)
    assert "e" not in text.lower()
    assert text == "35 m"


def test_very_large_value_uses_kilometers():
    text = format_length_mm(2.5e7)
    assert text == "25 km"
