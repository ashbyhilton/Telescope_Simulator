"""Optics tab: list of optics (add/remove/rename) plus a live property
form for the selected optic. Shares Optic object instances directly with
the rest of the app (no copying), so edits from here or from a canvas drag
are immediately visible everywhere; the signals below exist only to say
"something changed, please redraw/resync" rather than to carry data."""
from __future__ import annotations

import math
from typing import List, Optional

from pyqtgraph.Qt import QtCore, QtWidgets

from ...model.optics import Optic, OpticKind, describe_shape, make_default_optic
from ...physics.matrices import thick_lens
from ..mm_axis import format_length_mm

# What "Add" can create: (display label, starting-shape preset, name prefix).
# Deliberately just two starting points rather than one entry per OpticKind
# -- every field (including R1/R2) stays fully editable after creation, so
# these are only a sane starting shape, not a permanent classification. Kind
# values not offered here (biconvex, biconcave, plano-concave, custom) still
# exist in `OpticKind`/save files for backward compatibility; they're simply
# not offered as an "Add" starting point anymore.
_ADD_PRESETS = [
    ("Flat plate", OpticKind.PLANO_PLANO, "Flat Plate"),
    ("Singlet lens", OpticKind.PLANO_CONVEX, "Singlet Lens"),
]


class OpticsTab(QtWidgets.QWidget):
    opticsListChanged = QtCore.Signal()
    opticPropertyChanged = QtCore.Signal(int)
    selectionChanged = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.optics: List[Optic] = []
        self._selected_id: Optional[int] = None
        self._updating_list = False
        self._updating_form = False

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_list_selection_changed)
        self.list_widget.itemChanged.connect(self._on_item_renamed)

        self.kind_combo = QtWidgets.QComboBox()
        self.kind_combo.setToolTip(
            "Preset for the next optic created by \"Add\" below — it has no\n"
            "effect on the currently selected optic. See \"Shape (from R1/R2)\"\n"
            "in Properties for the selected optic's actual current shape."
        )
        for label, kind, name_prefix in _ADD_PRESETS:
            self.kind_combo.addItem(label, (kind, name_prefix))
        add_btn = QtWidgets.QPushButton("Add")
        add_btn.clicked.connect(self._on_add_clicked)
        remove_btn = QtWidgets.QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove_clicked)

        add_row = QtWidgets.QHBoxLayout()
        add_row.addWidget(self.kind_combo, 1)
        add_row.addWidget(add_btn)
        add_row.addWidget(remove_btn)

        self.form = self._build_form()

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Optics (double-click a name to rename)"))
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(add_row)
        layout.addWidget(self.form)
        self._set_form_enabled(False)

    # -- form construction -----------------------------------------------
    def _build_form(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Properties")
        form = QtWidgets.QFormLayout(box)

        self.diameter_spin = self._mm_spin(0.001, 1000.0)
        self.thickness_spin = self._mm_spin(0.0, 1000.0)
        roc_tip = (
            "Sign convention: positive = convex, negative = concave (as seen from\n"
            "outside the lens looking at that surface), for both R1 and R2."
        )
        self.r1_spin = self._mm_spin(-1.0e7, 1.0e7)
        self.r1_spin.setToolTip(roc_tip)
        self.r1_flat_check = QtWidgets.QCheckBox("Flat")
        self.r2_spin = self._mm_spin(-1.0e7, 1.0e7)
        self.r2_spin.setToolTip(
            roc_tip + "\n\n(Internally R2 is stored/propagated in the opposite, physics-"
            "textbook convention -- center of curvature on the +z side of the vertex is "
            "positive -- so this field's sign is flipped from the saved project file's "
            "raw r2 value; see README.)"
        )
        self.r2_flat_check = QtWidgets.QCheckBox("Flat")
        self.n_spin = QtWidgets.QDoubleSpinBox()
        self.n_spin.setRange(1.0, 4.0)
        self.n_spin.setDecimals(4)
        self.n_spin.setSingleStep(0.01)
        self.z_spin = self._mm_spin(-1.0e6, 1.0e6)
        self.x_spin = self._mm_spin(-1.0e6, 1.0e6)
        self.angle_spin = QtWidgets.QDoubleSpinBox()
        self.angle_spin.setRange(-89.0, 89.0)
        self.angle_spin.setDecimals(2)
        self.angle_spin.setSuffix(" deg")
        self.angle_spin.setToolTip(
            "Tilt of the optic normal relative to +z. In v1 this rotates the drawing and\n"
            "aperture projection only; it does not add astigmatism to the beam physics."
        )

        self.lock_z_check = QtWidgets.QCheckBox("Lock z")
        self.lock_x_check = QtWidgets.QCheckBox("Lock x")
        self.lock_angle_check = QtWidgets.QCheckBox("Lock angle")

        form.addRow("Full diameter", self.diameter_spin)
        form.addRow("Center thickness", self.thickness_spin)
        form.addRow("Front ROC (R1)", self._wrap(self.r1_spin, self.r1_flat_check))
        form.addRow("Back ROC (R2)", self._wrap(self.r2_spin, self.r2_flat_check))
        self.shape_label = QtWidgets.QLabel("-")
        self.shape_label.setToolTip(
            "Derived live from R1/R2 above — not the same as this optic's\n"
            "creation-time kind (its name/list entry), which never changes\n"
            "automatically if you hand-edit R1/R2 afterwards."
        )
        form.addRow("Shape (from R1/R2)", self.shape_label)
        self.efl_label = QtWidgets.QLabel("-")
        form.addRow("Effective focal length", self.efl_label)
        self.bfl_label = QtWidgets.QLabel("-")
        self.bfl_label.setToolTip(
            "Distance from the back vertex (the surface facing +z) to the rear focal\n"
            "point, for a collimated beam entering the front -- unlike EFL, this is\n"
            "measured from the physical lens, not from a principal plane."
        )
        form.addRow("Back focal length", self.bfl_label)
        form.addRow("Refractive index", self.n_spin)
        form.addRow("z position", self.z_spin)
        form.addRow("x position", self.x_spin)
        form.addRow("Tilt angle", self.angle_spin)
        form.addRow(self._wrap(self.lock_z_check, self.lock_x_check, self.lock_angle_check))

        for w in (self.diameter_spin, self.thickness_spin, self.r1_spin, self.r2_spin,
                  self.n_spin, self.z_spin, self.x_spin, self.angle_spin):
            w.valueChanged.connect(self._on_form_value_changed)
        for c in (self.lock_z_check, self.lock_x_check, self.lock_angle_check):
            c.toggled.connect(self._on_form_value_changed)
        self.r1_flat_check.toggled.connect(self._on_r1_flat_toggled)
        self.r2_flat_check.toggled.connect(self._on_r2_flat_toggled)

        return box

    @staticmethod
    def _mm_spin(lo: float, hi: float) -> QtWidgets.QDoubleSpinBox:
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(4)
        s.setSuffix(" mm")
        return s

    @staticmethod
    def _wrap(*widgets: QtWidgets.QWidget) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            row.addWidget(widget)
        return w

    def _set_form_enabled(self, enabled: bool) -> None:
        self.form.setEnabled(enabled)

    # -- list management --------------------------------------------------
    def set_optics(self, optics: List[Optic]) -> None:
        self.optics = optics
        self._updating_list = True
        self.list_widget.clear()
        for optic in self.optics:
            item = QtWidgets.QListWidgetItem(optic.name)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, optic.id)
            self.list_widget.addItem(item)
        self._updating_list = False
        if self._selected_id is not None and self._optic_by_id(self._selected_id) is None:
            self._selected_id = None
            self._set_form_enabled(False)

    def select_optic(self, optic_id: int) -> None:
        row = self._row_for_id(optic_id)
        if row < 0:
            return
        self._updating_list = True
        self.list_widget.setCurrentRow(row)
        self._updating_list = False
        self._selected_id = optic_id
        self._load_optic_into_form(self._optic_by_id(optic_id))

    def update_optic_position(self, optic_id: int, z: float, x: float) -> None:
        if optic_id != self._selected_id:
            return
        self._updating_form = True
        self.z_spin.setValue(z)
        self.x_spin.setValue(x)
        self._updating_form = False

    def _row_for_id(self, optic_id: int) -> int:
        for row in range(self.list_widget.count()):
            if self.list_widget.item(row).data(QtCore.Qt.ItemDataRole.UserRole) == optic_id:
                return row
        return -1

    def _optic_by_id(self, optic_id: int) -> Optional[Optic]:
        for o in self.optics:
            if o.id == optic_id:
                return o
        return None

    # -- signal handlers ---------------------------------------------------
    def _on_list_selection_changed(self) -> None:
        if self._updating_list:
            return
        items = self.list_widget.selectedItems()
        if not items:
            self._selected_id = None
            self._set_form_enabled(False)
            self.selectionChanged.emit(-1)
            return
        optic_id = items[0].data(QtCore.Qt.ItemDataRole.UserRole)
        self._selected_id = optic_id
        self._load_optic_into_form(self._optic_by_id(optic_id))
        self.selectionChanged.emit(optic_id)

    def _on_item_renamed(self, item: QtWidgets.QListWidgetItem) -> None:
        if self._updating_list:
            return
        optic_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        optic = self._optic_by_id(optic_id)
        if optic is None:
            return
        optic.name = item.text()
        self.opticPropertyChanged.emit(optic_id)

    def _load_optic_into_form(self, optic: Optional[Optic]) -> None:
        if optic is None:
            self._set_form_enabled(False)
            self.shape_label.setText("-")
            self.efl_label.setText("-")
            self.bfl_label.setText("-")
            return
        self._set_form_enabled(True)
        self._updating_form = True
        self.diameter_spin.setValue(optic.diameter_full)
        self.thickness_spin.setValue(optic.thickness_center)
        r1_flat = math.isinf(optic.r1)
        self.r1_flat_check.setChecked(r1_flat)
        self.r1_spin.setValue(0.0 if r1_flat else optic.r1)
        self.r1_spin.setEnabled(not r1_flat)
        r2_flat = math.isinf(optic.r2)
        self.r2_flat_check.setChecked(r2_flat)
        # Displayed with sign flipped from the stored physics-convention
        # value, so positive reads as convex here too (see r2_spin's tooltip).
        self.r2_spin.setValue(0.0 if r2_flat else -optic.r2)
        self.r2_spin.setEnabled(not r2_flat)
        self.n_spin.setValue(optic.n)
        self.z_spin.setValue(optic.z)
        self.x_spin.setValue(optic.x)
        self.angle_spin.setValue(optic.angle_deg)
        self.lock_z_check.setChecked(optic.lock_z)
        self.lock_x_check.setChecked(optic.lock_x)
        self.lock_angle_check.setChecked(optic.lock_angle)
        self._updating_form = False
        self._update_shape_label(optic)
        self._update_efl_label(optic)

    def _update_shape_label(self, optic: Optic) -> None:
        self.shape_label.setText(describe_shape(optic.r1, optic.r2))

    def _update_efl_label(self, optic: Optic) -> None:
        try:
            m = thick_lens(optic.thickness_center, optic.n, optic.r1, optic.r2)
        except (ValueError, ZeroDivisionError):
            self.efl_label.setText("-")
            self.bfl_label.setText("-")
            return
        power = -m[1, 0]
        if abs(power) < 1e-12:
            self.efl_label.setText("∞ (afocal)")
            self.bfl_label.setText("∞ (afocal)")
        else:
            self.efl_label.setText(format_length_mm(1.0 / power))
            # Back focal length: distance from the back vertex to the rear
            # focal point, -A/C -- unlike EFL (-1/C), this is measured from
            # the physical lens rather than from a principal plane, so it
            # differs from EFL whenever the lens has real thickness.
            self.bfl_label.setText(format_length_mm(-m[0, 0] / m[1, 0]))

    def _on_r1_flat_toggled(self, checked: bool) -> None:
        self.r1_spin.setEnabled(not checked)
        if not checked and self.r1_spin.value() == 0.0:
            self.r1_spin.setValue(100.0)
        self._on_form_value_changed()

    def _on_r2_flat_toggled(self, checked: bool) -> None:
        self.r2_spin.setEnabled(not checked)
        if not checked and self.r2_spin.value() == 0.0:
            self.r2_spin.setValue(100.0)
        self._on_form_value_changed()

    def _on_form_value_changed(self, *_args) -> None:
        if self._updating_form or self._selected_id is None:
            return
        optic = self._optic_by_id(self._selected_id)
        if optic is None:
            return
        # A user can type 0 directly into a ROC spinbox without touching its
        # "Flat" checkbox, bypassing the repair the checkbox's own toggled
        # handler does. Apply the same repair here so optic.r1/r2 can never
        # become 0.0 while "Flat" is unchecked, regardless of entry path.
        # setValue() re-enters this handler (same as the toggled handlers
        # already do), which finishes the write with the repaired value.
        if not self.r1_flat_check.isChecked() and self.r1_spin.value() == 0.0:
            self.r1_spin.setValue(100.0)
            return
        if not self.r2_flat_check.isChecked() and self.r2_spin.value() == 0.0:
            self.r2_spin.setValue(100.0)
            return
        self.r1_spin.setEnabled(not self.r1_flat_check.isChecked())
        self.r2_spin.setEnabled(not self.r2_flat_check.isChecked())
        optic.diameter_full = self.diameter_spin.value()
        optic.thickness_center = self.thickness_spin.value()
        optic.r1 = float("inf") if self.r1_flat_check.isChecked() else self.r1_spin.value()
        optic.r2 = float("inf") if self.r2_flat_check.isChecked() else -self.r2_spin.value()
        optic.n = self.n_spin.value()
        optic.z = self.z_spin.value()
        optic.x = self.x_spin.value()
        optic.angle_deg = self.angle_spin.value()
        optic.lock_z = self.lock_z_check.isChecked()
        optic.lock_x = self.lock_x_check.isChecked()
        optic.lock_angle = self.lock_angle_check.isChecked()
        self._update_shape_label(optic)
        self._update_efl_label(optic)
        self.opticPropertyChanged.emit(optic.id)

    def _on_add_clicked(self) -> None:
        kind, name_prefix = self.kind_combo.currentData()
        z = max((o.z + o.thickness_center for o in self.optics), default=0.0) + 10.0
        name = f"{name_prefix} {len(self.optics) + 1}"
        optic = make_default_optic(kind, name, z=z)
        self.optics.append(optic)
        self.set_optics(self.optics)
        self.opticsListChanged.emit()
        self.select_optic(optic.id)

    def _on_remove_clicked(self) -> None:
        if self._selected_id is None:
            return
        self.optics[:] = [o for o in self.optics if o.id != self._selected_id]
        self._selected_id = None
        self.set_optics(self.optics)
        self.opticsListChanged.emit()
