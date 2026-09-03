"""'Add optic' dialog: replaces the old kind-preset dropdown. "Single optic"
mode edits one Optic's full parameter set, with a live edge/center-thickness
coupling and a construction-diagram preview; "Composite (grouped) lens" mode
builds a rigid group of several sub-optics plus inter-element spacings,
added/edited as one unit (see model/optics.py's group_id/group_name and
gui/tabs/optics_tab.py's one-row-per-group list). Accept/Reject via a
standard QDialogButtonBox; the caller reads back `result_optic()` or
`result_group()` depending on `is_composite()`."""
from __future__ import annotations

import math
from typing import List, Optional

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from ...model.optics import (
    Optic,
    center_thickness_from_edge,
    edge_thickness_from_center,
    layout_group_z,
    surface_sag,
)
from ..lens_geometry import build_lens_polygon
from ..widget_utils import mm_spin, wrap_row


def _clone_shape(o: Optic) -> Optic:
    """A fresh Optic carrying only o's shape fields (own new id, no
    position/group/lock) -- used to build working copies for the dialog to
    edit without mutating the caller's project state until Accept."""
    return Optic(
        name=o.name, diameter_full=o.diameter_full, thickness_center=o.thickness_center,
        r1=o.r1, r2=o.r2, n=o.n,
    )


class _OpticFieldsWidget(QtWidgets.QWidget):
    """The shared name/diameter/thickness/edge-thickness/R1/R2/n field set --
    used both for single-optic mode and, in composite mode, for editing
    whichever sub-element is currently selected. Owns no Optic itself;
    callers push/pull values via load()/apply()."""

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        form = QtWidgets.QFormLayout(self)

        self.name_edit = QtWidgets.QLineEdit()
        self.diameter_spin = mm_spin(0.001, 1000.0)
        self.thickness_spin = mm_spin(0.0, 1000.0)
        self.edge_thickness_spin = mm_spin(-1000.0, 1000.0)
        self.edge_thickness_spin.setToolTip(
            "Coupled with center thickness above: editing either one recomputes\n"
            "the other from the current diameter and R1/R2."
        )
        roc_tip = (
            "Sign convention: positive = convex, negative = concave (as seen from\n"
            "outside the lens looking at that surface), for both R1 and R2."
        )
        self.r1_spin = mm_spin(-1.0e7, 1.0e7)
        self.r1_spin.setToolTip(roc_tip)
        self.r1_flat_check = QtWidgets.QCheckBox("Flat")
        self.r2_spin = mm_spin(-1.0e7, 1.0e7)
        self.r2_spin.setToolTip(roc_tip)
        self.r2_flat_check = QtWidgets.QCheckBox("Flat")
        self.n_spin = QtWidgets.QDoubleSpinBox()
        self.n_spin.setRange(1.0, 4.0)
        self.n_spin.setDecimals(4)
        self.n_spin.setSingleStep(0.01)

        form.addRow("Name", self.name_edit)
        form.addRow("Full diameter", self.diameter_spin)
        form.addRow("Center thickness", self.thickness_spin)
        form.addRow("Edge thickness", self.edge_thickness_spin)
        form.addRow("Front ROC (R1)", wrap_row(self.r1_spin, self.r1_flat_check))
        form.addRow("Back ROC (R2)", wrap_row(self.r2_spin, self.r2_flat_check))
        form.addRow("Refractive index", self.n_spin)

        self.name_edit.textChanged.connect(self._on_changed)
        for w in (self.diameter_spin, self.r1_spin, self.r2_spin, self.n_spin):
            w.valueChanged.connect(self._on_shape_field_changed)
        self.thickness_spin.valueChanged.connect(self._on_center_thickness_changed)
        self.edge_thickness_spin.valueChanged.connect(self._on_edge_thickness_changed)
        self.r1_flat_check.toggled.connect(self._on_flat_toggled)
        self.r2_flat_check.toggled.connect(self._on_flat_toggled)

    def load(self, optic: Optic) -> None:
        self._updating = True
        self.name_edit.setText(optic.name)
        self.diameter_spin.setValue(optic.diameter_full)
        self.thickness_spin.setValue(optic.thickness_center)
        r1_flat = math.isinf(optic.r1)
        self.r1_flat_check.setChecked(r1_flat)
        self.r1_spin.setValue(0.0 if r1_flat else optic.r1)
        self.r1_spin.setEnabled(not r1_flat)
        r2_flat = math.isinf(optic.r2)
        self.r2_flat_check.setChecked(r2_flat)
        self.r2_spin.setValue(0.0 if r2_flat else -optic.r2)
        self.r2_spin.setEnabled(not r2_flat)
        self.n_spin.setValue(optic.n)
        self._updating = False
        self._sync_edge_from_center()

    def apply(self, optic: Optic) -> None:
        optic.name = self.name_edit.text().strip() or optic.name
        optic.diameter_full = self.diameter_spin.value()
        optic.thickness_center = self.thickness_spin.value()
        r1, r2 = self.current_r1_r2()
        optic.r1 = r1
        optic.r2 = r2
        optic.n = self.n_spin.value()

    def current_r1_r2(self):
        r1 = float("inf") if self.r1_flat_check.isChecked() else self.r1_spin.value()
        r2 = float("inf") if self.r2_flat_check.isChecked() else -self.r2_spin.value()
        return r1, r2

    def _on_flat_toggled(self, _checked: bool) -> None:
        self.r1_spin.setEnabled(not self.r1_flat_check.isChecked())
        self.r2_spin.setEnabled(not self.r2_flat_check.isChecked())
        self._on_shape_field_changed()

    def _on_shape_field_changed(self, *_args) -> None:
        if self._updating:
            return
        self._sync_edge_from_center()
        self.changed.emit()

    def _on_center_thickness_changed(self, _value: float) -> None:
        if self._updating:
            return
        self._sync_edge_from_center()
        self.changed.emit()

    def _on_edge_thickness_changed(self, _value: float) -> None:
        if self._updating:
            return
        r1, r2 = self.current_r1_r2()
        center = center_thickness_from_edge(r1, r2, self.diameter_spin.value(), self.edge_thickness_spin.value())
        self._updating = True
        self.thickness_spin.setValue(max(center, 0.0))
        self._updating = False
        self.changed.emit()

    def _on_changed(self, *_args) -> None:
        if self._updating:
            return
        self.changed.emit()

    def _sync_edge_from_center(self) -> None:
        r1, r2 = self.current_r1_r2()
        edge = edge_thickness_from_center(r1, r2, self.diameter_spin.value(), self.thickness_spin.value())
        self._updating = True
        self.edge_thickness_spin.setValue(edge)
        self._updating = False


class _LensPreview(pg.PlotWidget):
    """Live construction-diagram preview: the true sag silhouette of one or
    more chained lens elements (reusing `build_lens_polygon`, the same
    geometry `OpticItem` draws on the main canvas), annotated with dimension
    lines/labels identifying diameter, center thickness, edge thickness, and
    both radii of curvature."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # pg.PlotWidget's background follows the app-wide QPalette when not
        # explicitly set (see theme.py's apply_theme(), which sets that
        # palette globally but only ever restyles the *main* canvas's
        # background/axis-pen colors -- never a dialog's own preview widget).
        # Without this, dark mode leaves this preview with a dark background
        # but the light-mode-tuned dark-gray annotation colors below, which
        # is what made them "very faint". Detected once at construction --
        # the dialog is modal, so the app palette can't change underneath it.
        app = QtWidgets.QApplication.instance()
        is_dark = False
        if app is not None:
            is_dark = app.palette().color(QtGui.QPalette.ColorRole.Window).lightness() < 128
        if is_dark:
            self.setBackground((30, 30, 30))
            axis_pen = pg.mkPen((200, 200, 200))
            self._text_color = (220, 220, 220)
            self._line_color = (170, 170, 170)
        else:
            self.setBackground("w")
            axis_pen = pg.mkPen((0, 0, 0))
            self._text_color = (70, 70, 70)
            self._line_color = (90, 90, 90)
        for name in ("bottom", "left"):
            axis = self.getAxis(name)
            axis.setPen(axis_pen)
            axis.setTextPen(axis_pen)

        self.showGrid(x=True, y=True, alpha=0.15)
        self.setLabel("bottom", "z", units="mm")
        self.setLabel("left", "x", units="mm")
        self.getViewBox().setAspectLocked(True)
        self._shape_items: List[QtWidgets.QGraphicsPolygonItem] = []
        self._dim_lines: List[pg.PlotDataItem] = []
        self._dim_labels: List[pg.TextItem] = []

    def render(self, elements: List[Optic], anchors: List[float]) -> None:
        self._clear()
        for optic, z0 in zip(elements, anchors):
            poly = build_lens_polygon(optic)
            item = QtWidgets.QGraphicsPolygonItem(poly)
            item.setPos(z0, 0.0)
            item.setBrush(QtGui.QBrush(QtGui.QColor(140, 190, 230, 120)))
            pen = QtGui.QPen(QtGui.QColor(60, 110, 150))
            pen.setWidth(0)
            item.setPen(pen)
            self.addItem(item)
            self._shape_items.append(item)
            self._add_dimension_annotations(optic, z0)
        self.getViewBox().enableAutoRange()

    def _clear(self) -> None:
        for item in self._shape_items:
            self.removeItem(item)
        self._shape_items = []
        for item in self._dim_lines:
            self.removeItem(item)
        self._dim_lines = []
        for item in self._dim_labels:
            self.removeItem(item)
        self._dim_labels = []

    def _add_dimension_annotations(self, optic: Optic, z0: float) -> None:
        half_d = max(optic.diameter_full, 1e-6) / 2.0
        back_z = z0 + optic.thickness_center

        dia_z = z0 - max(optic.thickness_center, half_d) * 0.35 - 1.0
        self._add_line([dia_z, dia_z], [-half_d, half_d])
        self._add_label(f"⌀ {optic.diameter_full:.3g} mm", dia_z, half_d, anchor=(1.1, 0.5))

        ct_x = -half_d * 1.15
        self._add_line([z0, back_z], [ct_x, ct_x])
        self._add_label(f"tc {optic.thickness_center:.3g} mm", (z0 + back_z) / 2.0, ct_x, anchor=(0.5, 1.1))

        front_edge_z = z0 + surface_sag(optic.r1, half_d)
        back_edge_z = back_z + surface_sag(optic.r2, half_d)
        et_x = half_d * 1.15
        self._add_line([front_edge_z, back_edge_z], [et_x, et_x])
        edge = edge_thickness_from_center(optic.r1, optic.r2, optic.diameter_full, optic.thickness_center)
        self._add_label(f"te {edge:.3g} mm", (front_edge_z + back_edge_z) / 2.0, et_x, anchor=(0.5, -0.1))

        r1_text = "R1 flat" if math.isinf(optic.r1) else f"R1 {optic.r1:.3g} mm"
        r2_text = "R2 flat" if math.isinf(optic.r2) else f"R2 {-optic.r2:.3g} mm"
        self._add_label(r1_text, z0, 0.0, anchor=(1.1, 0.5))
        self._add_label(r2_text, back_z, 0.0, anchor=(-0.1, 0.5))

    def _add_line(self, xs, ys) -> None:
        item = pg.PlotDataItem(xs, ys, pen=pg.mkPen(self._line_color, width=1, style=QtCore.Qt.PenStyle.DashLine))
        self.addItem(item)
        self._dim_lines.append(item)

    def _add_label(self, text: str, z: float, x: float, anchor=(0.5, 0.5)) -> None:
        label = pg.TextItem(text, anchor=anchor, color=self._text_color)
        label.setPos(z, x)
        self.addItem(label)
        self._dim_labels.append(label)


class _SingleOpticPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields = _OpticFieldsWidget()
        self.preview = _LensPreview()
        layout = QtWidgets.QHBoxLayout(self)
        layout.addWidget(self.fields, 0)
        layout.addWidget(self.preview, 1)
        self.fields.load(Optic(name="New optic"))
        self.fields.changed.connect(self._refresh_preview)
        self._refresh_preview()

    def load(self, optic: Optic) -> None:
        self.fields.load(optic)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        draft = Optic(name=self.fields.name_edit.text() or "optic")
        self.fields.apply(draft)
        self.preview.render([draft], [0.0])

    def result_optic(self) -> Optic:
        optic = Optic(name="optic")
        self.fields.apply(optic)
        return optic


class _CompositePage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.elements: List[Optic] = []
        self.spacings: List[float] = []
        self._selected_index: Optional[int] = None
        self._updating = False

        self.group_name_edit = QtWidgets.QLineEdit("Composite Lens")
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        add_btn = QtWidgets.QPushButton("Add element")
        add_btn.clicked.connect(self._on_add_element)
        remove_btn = QtWidgets.QPushButton("Remove element")
        remove_btn.clicked.connect(self._on_remove_element)

        self.spacing_spin = mm_spin(0.0, 1000.0)
        self.spacing_spin.valueChanged.connect(self._on_spacing_changed)
        self.spacing_row = wrap_row(QtWidgets.QLabel("Spacing to next element"), self.spacing_spin)

        self.fields = _OpticFieldsWidget()
        self.fields.changed.connect(self._on_fields_changed)
        self.preview = _LensPreview()

        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Group name"))
        left.addWidget(self.group_name_edit)
        left.addWidget(self.list_widget, 1)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        left.addLayout(btn_row)
        left.addWidget(self.spacing_row)
        left.addWidget(self.fields)
        left_widget = QtWidgets.QWidget()
        left_widget.setLayout(left)

        layout = QtWidgets.QHBoxLayout(self)
        layout.addWidget(left_widget, 0)
        layout.addWidget(self.preview, 1)

        self._on_add_element()

    def load_group(self, members: List[Optic]) -> None:
        members_sorted = sorted(members, key=lambda o: o.z)
        self.group_name_edit.setText(members_sorted[0].group_name or "Composite Lens")
        self.elements = [_clone_shape(o) for o in members_sorted]
        self.spacings = [
            cur.z - (prev.z + prev.thickness_center) for prev, cur in zip(members_sorted, members_sorted[1:])
        ]
        self._rebuild_list()
        if self.elements:
            self.list_widget.setCurrentRow(0)

    def _rebuild_list(self) -> None:
        self._updating = True
        self.list_widget.clear()
        for i, o in enumerate(self.elements):
            self.list_widget.addItem(f"{i + 1}. {o.name}")
        self._updating = False

    def _on_add_element(self) -> None:
        idx = len(self.elements)
        self.elements.append(Optic(name=f"Element {idx + 1}"))
        if idx > 0:
            self.spacings.append(0.0)
        self._rebuild_list()
        self.list_widget.setCurrentRow(idx)

    def _on_remove_element(self) -> None:
        idx = self._selected_index
        if idx is None or len(self.elements) <= 1:
            return
        del self.elements[idx]
        if idx < len(self.spacings):
            del self.spacings[idx]
        elif self.spacings:
            del self.spacings[-1]
        self._rebuild_list()
        self.list_widget.setCurrentRow(min(idx, len(self.elements) - 1))

    def _on_row_changed(self, row: int) -> None:
        if self._updating:
            return
        if row < 0 or row >= len(self.elements):
            self._selected_index = None
            self.fields.setEnabled(False)
            return
        self._selected_index = row
        self.fields.setEnabled(True)
        self._updating = True
        self.fields.load(self.elements[row])
        is_last = row == len(self.elements) - 1
        self.spacing_row.setVisible(not is_last)
        if not is_last:
            self.spacing_spin.setValue(self.spacings[row])
        self._updating = False
        self._refresh_preview()

    def _on_fields_changed(self) -> None:
        if self._updating or self._selected_index is None:
            return
        idx = self._selected_index
        self.fields.apply(self.elements[idx])
        self.list_widget.item(idx).setText(f"{idx + 1}. {self.elements[idx].name}")
        self._refresh_preview()

    def _on_spacing_changed(self, value: float) -> None:
        if self._updating or self._selected_index is None:
            return
        if self._selected_index < len(self.spacings):
            self.spacings[self._selected_index] = value
            self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not self.elements:
            return
        anchors = layout_group_z(self.elements, self.spacings, anchor_z=0.0)
        self.preview.render(self.elements, anchors)

    def result_group(self) -> List[Optic]:
        group_name = self.group_name_edit.text().strip() or "Composite Lens"
        result = [_clone_shape(o) for o in self.elements]
        anchors = layout_group_z(result, self.spacings, anchor_z=0.0)
        shared_group_id = result[0].id
        for optic, z in zip(result, anchors):
            optic.z = z
            optic.group_id = shared_group_id
            optic.group_name = group_name
        return result


class AddOpticDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent=None,
        existing_group: Optional[List[Optic]] = None,
        existing_single: Optional[Optic] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Add optic")

        self.tabs = QtWidgets.QTabWidget()
        self.single_page = _SingleOpticPage()
        self.composite_page = _CompositePage()
        self.tabs.addTab(self.single_page, "Single optic")
        self.tabs.addTab(self.composite_page, "Composite (grouped) lens")

        if existing_single is not None:
            self.single_page.load(existing_single)
            self.tabs.setCurrentWidget(self.single_page)
        if existing_group:
            self.composite_page.load_group(existing_group)
            self.tabs.setCurrentWidget(self.composite_page)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)
        self.resize(820, 560)

    def is_composite(self) -> bool:
        return self.tabs.currentWidget() is self.composite_page

    def result_optic(self) -> Optic:
        return self.single_page.result_optic()

    def result_group(self) -> List[Optic]:
        return self.composite_page.result_group()
