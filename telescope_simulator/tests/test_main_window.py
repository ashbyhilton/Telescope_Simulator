import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.gui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_explicit_view_range_applies_without_reset_view_click(qapp):
    """Changing the View box's z/x range fields must snap the canvas to the
    new range immediately -- previously this only took effect after
    clicking "Reset View"."""
    w = MainWindow()
    w.config_tab.lock_aspect_check.setChecked(False)
    w.config_tab.auto_x_check.setChecked(False)
    w.config_tab.x_min_spin.setValue(-10.0)
    w.config_tab.x_max_spin.setValue(10.0)
    w.config_tab.auto_z_check.setChecked(False)
    w.config_tab.z_min_spin.setValue(-500.0)
    w.config_tab.z_max_spin.setValue(2500.0)

    (z_lo, z_hi), (x_lo, x_hi) = w.plot_view.getViewBox().viewRange()
    assert z_lo == pytest.approx(-500.0, abs=1.0)
    assert z_hi == pytest.approx(2500.0, abs=1.0)
    assert x_lo == pytest.approx(-10.0, abs=1.0)
    assert x_hi == pytest.approx(10.0, abs=1.0)


def test_trailing_padding_change_applies_without_reset_view_click(qapp):
    """Changing 'plot padding past output' must extend the visible z range
    immediately when in auto z-range mode."""
    w = MainWindow()
    w.config_tab.lock_aspect_check.setChecked(False)
    (_, z_hi_before), _ = w.plot_view.getViewBox().viewRange()

    w.config_tab.trailing_min_spin.setValue(5000.0)

    (_, z_hi_after), _ = w.plot_view.getViewBox().viewRange()
    assert z_hi_after > z_hi_before + 1000.0
