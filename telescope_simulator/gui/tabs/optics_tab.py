"""Optics tab: list of optics (add/remove/rename) plus a live property
form for the selected optic. Shares Optic object instances directly with
the rest of the app (no copying), so edits from here or from a canvas drag
are immediately visible everywhere; the signals below exist only to say
"something changed, please redraw/resync" rather than to carry data."""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from pyqtgraph.Qt import QtCore, QtWidgets

from ...model.optics import Optic, describe_shape, group_key
from ...physics.matrices import propagation, thick_lens
from ..dialogs.add_optic_dialog import AddOpticDialog
from ..mm_axis import format_length_mm
from ..widget_utils import mm_spin, wrap_row


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

        add_btn = QtWidgets.QPushButton("Add")
        add_btn.clicked.connect(self._on_add_clicked)
        remove_btn = QtWidgets.QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove_clicked)

        add_row = QtWidgets.QHBoxLayout()
        add_row.addWidget(add_btn)
        add_row.addWidget(remove_btn)

        self.form = self._build_form()
        self.group_box = self._build_group_box()
        self.group_box.hide()

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Optics (double-click a name to rename)"))
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(add_row)
        layout.addWidget(self.form)
        layout.addWidget(self.group_box)
        self._set_form_enabled(False)

    # -- form construction -----------------------------------------------
    def _build_form(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Properties")
        form = QtWidgets.QFormLayout(box)

        self.diameter_spin = mm_spin(0.001, 1000.0)
        self.thickness_spin = mm_spin(0.0, 1000.0)
        roc_tip = (
            "Sign convention: positive = convex, negative = concave (as seen from\n"
            "outside the lens looking at that surface), for both R1 and R2."
        )
        self.r1_spin = mm_spin(-1.0e7, 1.0e7)
        self.r1_spin.setToolTip(roc_tip)
        self.r1_flat_check = QtWidgets.QCheckBox("Flat")
        self.r2_spin = mm_spin(-1.0e7, 1.0e7)
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
        self.z_spin = mm_spin(-1.0e6, 1.0e6)

        self.lock_z_check = QtWidgets.QCheckBox("Lock z")

        form.addRow("Full diameter", self.diameter_spin)
        form.addRow("Center thickness", self.thickness_spin)
        form.addRow("Front ROC (R1)", wrap_row(self.r1_spin, self.r1_flat_check))
        form.addRow("Back ROC (R2)", wrap_row(self.r2_spin, self.r2_flat_check))
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
        form.addRow(self.lock_z_check)
        edit_single_btn = QtWidgets.QPushButton("Edit lens...")
        edit_single_btn.setToolTip(
            "Opens this lens in the Add-optic dialog's live construction-diagram\n"
            "preview, with the coupled edge/center-thickness fields -- the fields\n"
            "above already edit the same optic directly, this is just the other view."
        )
        edit_single_btn.clicked.connect(self._on_edit_single_clicked)
        form.addRow(edit_single_btn)

        for w in (self.diameter_spin, self.thickness_spin, self.r1_spin, self.r2_spin,
                  self.n_spin, self.z_spin):
            w.valueChanged.connect(self._on_form_value_changed)
        self.lock_z_check.toggled.connect(self._on_form_value_changed)
        self.r1_flat_check.toggled.connect(self._on_r1_flat_toggled)
        self.r2_flat_check.toggled.connect(self._on_r2_flat_toggled)

        return box

    def _build_group_box(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Composite lens")
        form = QtWidgets.QFormLayout(box)
        self.group_members_label = QtWidgets.QLabel("-")
        self.group_members_label.setWordWrap(True)
        form.addRow("Elements", self.group_members_label)
        self.group_length_label = QtWidgets.QLabel("-")
        form.addRow("Total length", self.group_length_label)
        self.group_efl_label = QtWidgets.QLabel("-")
        form.addRow("Effective focal length", self.group_efl_label)
        self.group_bfl_label = QtWidgets.QLabel("-")
        form.addRow("Back focal length", self.group_bfl_label)
        self.group_z_spin = mm_spin(-1.0e6, 1.0e6)
        self.group_z_spin.setToolTip("The group's anchor (frontmost element's z) -- editing this rigidly shifts every element together, same as dragging the group on the canvas.")
        form.addRow("z position (group anchor)", self.group_z_spin)
        self.group_lock_check = QtWidgets.QCheckBox("Lock z")
        form.addRow(self.group_lock_check)
        edit_btn = QtWidgets.QPushButton("Edit...")
        edit_btn.clicked.connect(self._on_edit_group_clicked)
        form.addRow(edit_btn)
        hint = QtWidgets.QLabel(
            "A composite lens is a rigid group -- drag any element on the canvas to\n"
            "move the whole group, or use Edit... to change its sub-elements/spacings."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        form.addRow(hint)

        self.group_z_spin.valueChanged.connect(self._on_group_form_value_changed)
        self.group_lock_check.toggled.connect(self._on_group_form_value_changed)

        return box

    def _set_form_enabled(self, enabled: bool) -> None:
        self.form.setEnabled(enabled)

    # -- list management --------------------------------------------------
    def set_optics(self, optics: List[Optic]) -> None:
        """Builds one list row per composite group plus one row per
        standalone optic (see `group_key`) -- a composite is presented and
        selected/removed as a single rigid unit, matching its canvas
        behavior in `plot_view.py`."""
        self.optics = optics
        self._updating_list = True
        self.list_widget.clear()
        seen_keys = set()
        for optic in self.optics:
            key = group_key(optic)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            label = optic.group_name if optic.group_id is not None else optic.name
            item = QtWidgets.QListWidgetItem(label)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, key)
            self.list_widget.addItem(item)
        self._updating_list = False
        if self._selected_id is not None and not self._members_for_key(self._selected_id):
            self._selected_id = None
            self._set_form_enabled(False)
            self.group_box.hide()

    def select_optic(self, key: int) -> None:
        row = self._row_for_key(key)
        if row < 0:
            return
        self._updating_list = True
        self.list_widget.setCurrentRow(row)
        self._updating_list = False
        self._load_selection(key)

    def update_optic_position(self, key: int, z: float) -> None:
        if key != self._selected_id:
            return
        members = self._members_for_key(key)
        if len(members) == 1 and members[0].group_id is None:
            self._updating_form = True
            self.z_spin.setValue(z)
            self._updating_form = False
        else:
            self._load_group_into_summary(members)

    def _row_for_key(self, key: int) -> int:
        for row in range(self.list_widget.count()):
            if self.list_widget.item(row).data(QtCore.Qt.ItemDataRole.UserRole) == key:
                return row
        return -1

    def _members_for_key(self, key: Optional[int]) -> List[Optic]:
        if key is None:
            return []
        return [o for o in self.optics if group_key(o) == key]

    # -- signal handlers ---------------------------------------------------
    def _on_list_selection_changed(self) -> None:
        if self._updating_list:
            return
        items = self.list_widget.selectedItems()
        if not items:
            self._load_selection(None)
            self.selectionChanged.emit(-1)
            return
        key = items[0].data(QtCore.Qt.ItemDataRole.UserRole)
        self._load_selection(key)
        self.selectionChanged.emit(key)

    def _on_item_renamed(self, item: QtWidgets.QListWidgetItem) -> None:
        if self._updating_list:
            return
        key = item.data(QtCore.Qt.ItemDataRole.UserRole)
        members = self._members_for_key(key)
        if not members:
            return
        if len(members) == 1 and members[0].group_id is None:
            members[0].name = item.text()
        else:
            for o in members:
                o.group_name = item.text()
        self.opticPropertyChanged.emit(key)

    def _load_selection(self, key: Optional[int]) -> None:
        """Dispatches the selected row to either the editable single-optic
        form or the read-only composite-group summary, based on whether the
        row's key resolves to one standalone optic or a rigid group."""
        self._selected_id = key
        members = self._members_for_key(key)
        if len(members) == 1 and members[0].group_id is None:
            self.group_box.hide()
            self.form.show()
            self._load_optic_into_form(members[0])
        elif members:
            self.form.hide()
            self.group_box.show()
            self._set_form_enabled(True)
            self._load_group_into_summary(members)
        else:
            self.form.show()
            self.group_box.hide()
            self._load_optic_into_form(None)

    def _load_group_into_summary(self, members: List[Optic]) -> None:
        members_sorted = sorted(members, key=lambda o: o.z)
        lines = [
            f"{i}. {o.name} — {describe_shape(o.r1, o.r2)}, ⌀{o.diameter_full:.3g} mm"
            for i, o in enumerate(members_sorted, start=1)
        ]
        self.group_members_label.setText("\n".join(lines))
        total_len = (members_sorted[-1].z + members_sorted[-1].thickness_center) - members_sorted[0].z
        self.group_length_label.setText(format_length_mm(total_len))
        self._updating_form = True
        self.group_z_spin.setValue(members_sorted[0].z)
        self.group_lock_check.setChecked(members_sorted[0].lock_z)
        self._updating_form = False
        self._update_group_efl_bfl_labels(members_sorted)

    def _composite_matrix(self, members_sorted: List[Optic]):
        """Composes the whole chain's ABCD system matrix: each member's
        thick_lens() matrix folded with propagation() for the air gap to the
        next member, in the same rightmost-applied-first order thick_lens()
        itself already uses internally -- just extended across more than one
        element instead of re-deriving a multi-lens formula."""
        m = thick_lens(members_sorted[0].thickness_center, members_sorted[0].n, members_sorted[0].r1, members_sorted[0].r2)
        for prev, cur in zip(members_sorted, members_sorted[1:]):
            gap = cur.z - (prev.z + prev.thickness_center)
            cur_m = thick_lens(cur.thickness_center, cur.n, cur.r1, cur.r2)
            m = cur_m @ propagation(gap) @ m
        return m

    def _update_group_efl_bfl_labels(self, members_sorted: List[Optic]) -> None:
        try:
            m = self._composite_matrix(members_sorted)
            efl_text, bfl_text = self._efl_bfl_text(m)
        except (ValueError, ZeroDivisionError):
            efl_text = bfl_text = "-"
        self.group_efl_label.setText(efl_text)
        self.group_bfl_label.setText(bfl_text)

    def _on_group_form_value_changed(self, *_args) -> None:
        if self._updating_form or self._selected_id is None:
            return
        members = self._members_for_key(self._selected_id)
        if not members or members[0].group_id is None:
            return
        anchor = min(o.z for o in members)
        delta = self.group_z_spin.value() - anchor
        locked = self.group_lock_check.isChecked()
        for o in members:
            o.z += delta
            o.lock_z = locked
        # z/lock don't change the list row's label, so no need to rebuild the
        # list widget (which would cost the user their row-selection
        # highlight for nothing) -- opticsListChanged already makes
        # MainWindow resync every OpticItem's position and re-propagate.
        self.opticsListChanged.emit()

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
        self.lock_z_check.setChecked(optic.lock_z)
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
        efl_text, bfl_text = self._efl_bfl_text(m)
        self.efl_label.setText(efl_text)
        self.bfl_label.setText(bfl_text)

    @staticmethod
    def _efl_bfl_text(m) -> Tuple[str, str]:
        power = -m[1, 0]
        if abs(power) < 1e-12:
            return "∞ (afocal)", "∞ (afocal)"
        # Back focal length: distance from the back vertex to the rear focal
        # point, -A/C -- unlike EFL (-1/C), this is measured from the
        # physical lens rather than from a principal plane, so it differs
        # from EFL whenever the lens (or, for a composite, the whole chain)
        # has real thickness.
        return format_length_mm(1.0 / power), format_length_mm(-m[0, 0] / m[1, 0])

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
        members = self._members_for_key(self._selected_id)
        if len(members) != 1 or members[0].group_id is not None:
            return
        optic = members[0]
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
        optic.lock_z = self.lock_z_check.isChecked()
        self._update_shape_label(optic)
        self._update_efl_label(optic)
        self.opticPropertyChanged.emit(optic.id)

    def _on_add_clicked(self) -> None:
        dialog = AddOpticDialog(self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        insertion_z = max((o.z + o.thickness_center for o in self.optics), default=0.0) + 10.0
        if dialog.is_composite():
            members = dialog.result_group()
            for o in members:
                o.z += insertion_z
            self.optics.extend(members)
            new_key = group_key(members[0])
        else:
            optic = dialog.result_optic()
            optic.z = insertion_z
            self.optics.append(optic)
            new_key = optic.id
        self.set_optics(self.optics)
        self.opticsListChanged.emit()
        self.select_optic(new_key)

    def _on_edit_single_clicked(self) -> None:
        members = self._members_for_key(self._selected_id)
        if len(members) != 1 or members[0].group_id is not None:
            return
        optic = members[0]
        dialog = AddOpticDialog(self, existing_single=optic)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        if dialog.is_composite():
            # Promoted into a composite group while editing -- same
            # remove-old/insert-new pattern _on_edit_group_clicked uses,
            # just starting from a single optic instead of an existing group.
            new_members = dialog.result_group()
            for o in new_members:
                o.z += optic.z
            self.optics[:] = [o for o in self.optics if o.id != optic.id] + new_members
            self.set_optics(self.optics)
            self.opticsListChanged.emit()
            self.select_optic(group_key(new_members[0]))
            return
        # Edit in place: same id/z/lock_z, matching how the inline form
        # above already edits this exact optic -- the dialog is just an
        # alternate view (construction-diagram preview + coupled edge
        # thickness) onto the same fields, not a replacement flow.
        dialog.single_page.fields.apply(optic)
        self._load_optic_into_form(optic)
        row = self._row_for_key(optic.id)
        if row >= 0:
            self._updating_list = True
            self.list_widget.item(row).setText(optic.name)
            self._updating_list = False
        self.opticPropertyChanged.emit(optic.id)

    def _on_edit_group_clicked(self) -> None:
        key = self._selected_id
        members = self._members_for_key(key)
        if not members:
            return
        anchor_z = min(o.z for o in members)
        dialog = AddOpticDialog(self, existing_group=members)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        new_members = dialog.result_group() if dialog.is_composite() else [dialog.result_optic()]
        for o in new_members:
            o.z += anchor_z
        self.optics[:] = [o for o in self.optics if group_key(o) != key] + new_members
        self.set_optics(self.optics)
        self.opticsListChanged.emit()
        self.select_optic(group_key(new_members[0]))

    def _on_remove_clicked(self) -> None:
        if self._selected_id is None:
            return
        key = self._selected_id
        self.optics[:] = [o for o in self.optics if group_key(o) != key]
        self._selected_id = None
        self.set_optics(self.optics)
        self.opticsListChanged.emit()
