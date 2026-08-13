"""Fit-to-data tab: a table of measured (z, beam diameter) points used to fit
the input beam's parameters. Follows the same conventions as the other tabs
(see README's "Signal conventions") -- this widget never talks to PlotView
directly; it only emits notification/request signals for MainWindow to act
on."""
from __future__ import annotations

from typing import List, Optional

from pyqtgraph.Qt import QtCore, QtWidgets

from ...model.fit_data import FitDataPoint

_DEFAULT_ROWS = 4
_MIN_FIT_ROWS = 3
_COL_INDEX, _COL_Z, _COL_DIAMETER = range(3)


class FitDataTab(QtWidgets.QWidget):
    fitDataChanged = QtCore.Signal()  # notification: re-read points_snapshot()
    fitRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Point #", "z location (mm)", "Beam diameter (mm)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._on_item_changed)

        add_btn = QtWidgets.QPushButton("Add row")
        add_btn.clicked.connect(self._on_add_row)
        remove_btn = QtWidgets.QPushButton("Remove row")
        remove_btn.clicked.connect(self._on_remove_row)
        clear_btn = QtWidgets.QPushButton("Clear data")
        clear_btn.clicked.connect(self._on_clear_data)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(add_btn)
        button_row.addWidget(remove_btn)
        button_row.addWidget(clear_btn)

        self.fit_btn = QtWidgets.QPushButton("Fit input beam to data")
        self.fit_btn.clicked.connect(self.fitRequested.emit)

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(button_row)
        layout.addWidget(self.fit_btn)
        layout.addWidget(self.error_label)

        self.set_points([FitDataPoint() for _ in range(_DEFAULT_ROWS)])

    # -- data in/out -----------------------------------------------------
    def set_points(self, points: List[FitDataPoint]) -> None:
        self._updating = True
        self.table.setRowCount(len(points))
        for row, point in enumerate(points):
            self._set_index_item(row)
            self._set_editable_item(row, _COL_Z, point.z_mm)
            self._set_editable_item(row, _COL_DIAMETER, point.diameter_mm)
        self._updating = False
        self._update_fit_eligibility()

    def points_snapshot(self) -> List[FitDataPoint]:
        points = []
        for row in range(self.table.rowCount()):
            points.append(FitDataPoint(z_mm=self._cell_value(row, _COL_Z), diameter_mm=self._cell_value(row, _COL_DIAMETER)))
        return points

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)

    # -- row helpers -------------------------------------------------------
    def _set_index_item(self, row: int) -> None:
        item = QtWidgets.QTableWidgetItem(str(row + 1))
        item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, _COL_INDEX, item)

    def _set_editable_item(self, row: int, col: int, value: Optional[float]) -> None:
        text = "" if value is None else f"{value:g}"
        self.table.setItem(row, col, QtWidgets.QTableWidgetItem(text))

    def _cell_value(self, row: int, col: int) -> Optional[float]:
        item = self.table.item(row, col)
        if item is None:
            return None
        text = item.text().strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _renumber_rows(self) -> None:
        self._updating = True
        for row in range(self.table.rowCount()):
            self._set_index_item(row)
        self._updating = False

    # -- signal handlers ---------------------------------------------------
    def _on_item_changed(self, _item: QtWidgets.QTableWidgetItem) -> None:
        if self._updating:
            return
        self._update_fit_eligibility()
        self.fitDataChanged.emit()

    def _on_add_row(self) -> None:
        row = self.table.rowCount()
        self._updating = True
        self.table.insertRow(row)
        self._set_index_item(row)
        self._set_editable_item(row, _COL_Z, None)
        self._set_editable_item(row, _COL_DIAMETER, None)
        self._updating = False
        self._update_fit_eligibility()
        self.fitDataChanged.emit()

    def _on_remove_row(self) -> None:
        if self.table.rowCount() == 0:
            return
        selected = self.table.selectionModel().selectedRows()
        row = selected[0].row() if selected else self.table.rowCount() - 1
        self.table.removeRow(row)
        self._renumber_rows()
        self._update_fit_eligibility()
        self.fitDataChanged.emit()

    def _on_clear_data(self) -> None:
        self._updating = True
        for row in range(self.table.rowCount()):
            self._set_editable_item(row, _COL_Z, None)
            self._set_editable_item(row, _COL_DIAMETER, None)
        self._updating = False
        self._update_fit_eligibility()
        self.fitDataChanged.emit()

    def _update_fit_eligibility(self) -> None:
        valid_count = sum(1 for p in self.points_snapshot() if p.is_valid())
        if valid_count >= _MIN_FIT_ROWS:
            self.fit_btn.setEnabled(True)
            self.fit_btn.setToolTip("")
        else:
            self.fit_btn.setEnabled(False)
            self.fit_btn.setToolTip(
                f"Fill in at least {_MIN_FIT_ROWS} complete rows (z and diameter) to fit "
                f"the input beam (have {valid_count})."
            )
