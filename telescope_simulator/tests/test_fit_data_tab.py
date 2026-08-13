import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.gui.tabs.fit_data_tab import FitDataTab
from telescope_simulator.model.fit_data import FitDataPoint


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_defaults_to_four_empty_rows(qapp):
    tab = FitDataTab()
    assert tab.table.rowCount() == 4
    assert all(not p.is_valid() for p in tab.points_snapshot())
    assert not tab.fit_btn.isEnabled()


def _fill_row(tab: FitDataTab, row: int, z: float, diameter: float) -> None:
    tab.table.item(row, 1).setText(str(z))
    tab.table.item(row, 2).setText(str(diameter))


def test_fit_button_enables_once_three_rows_are_valid(qapp):
    tab = FitDataTab()
    _fill_row(tab, 0, 10.0, 1.0)
    _fill_row(tab, 1, 20.0, 1.2)
    assert not tab.fit_btn.isEnabled()

    _fill_row(tab, 2, 30.0, 1.5)
    assert tab.fit_btn.isEnabled()


def test_add_row_appends_and_renumbers(qapp):
    tab = FitDataTab()
    tab._on_add_row()
    assert tab.table.rowCount() == 5
    assert tab.table.item(4, 0).text() == "5"


def test_remove_row_renumbers_remaining_rows(qapp):
    tab = FitDataTab()
    tab._on_remove_row()
    assert tab.table.rowCount() == 3
    assert [tab.table.item(r, 0).text() for r in range(3)] == ["1", "2", "3"]


def test_clear_data_blanks_values_but_keeps_row_count(qapp):
    tab = FitDataTab()
    _fill_row(tab, 0, 10.0, 1.0)
    _fill_row(tab, 1, 20.0, 1.2)
    _fill_row(tab, 2, 30.0, 1.5)

    tab._on_clear_data()

    assert tab.table.rowCount() == 4
    assert all(not p.is_valid() for p in tab.points_snapshot())
    assert not tab.fit_btn.isEnabled()


def test_set_points_round_trips_through_snapshot(qapp):
    tab = FitDataTab()
    points = [FitDataPoint(z_mm=1.0, diameter_mm=2.0), FitDataPoint(z_mm=None, diameter_mm=None)]
    tab.set_points(points)

    snapshot = tab.points_snapshot()
    assert snapshot[0].z_mm == 1.0
    assert snapshot[0].diameter_mm == 2.0
    assert snapshot[1].z_mm is None


def test_editing_a_cell_emits_fit_data_changed(qapp):
    tab = FitDataTab()
    seen = []
    tab.fitDataChanged.connect(lambda: seen.append(True))

    tab.table.item(0, 1).setText("5.0")

    assert seen
