"""Config tab: display/model settings that don't belong to any one optic
or the beam itself, plus the app-level dark-mode preference."""
from __future__ import annotations

from pyqtgraph.Qt import QtCore, QtWidgets

from ...model.config import SystemConfig
from ...version import APP_AUTHOR, APP_BUILD_DATE, APP_ORGANISATION, APP_VERSION


class ConfigTab(QtWidgets.QWidget):
    configChanged = QtCore.Signal(object)  # SystemConfig
    resetViewRequested = QtCore.Signal()
    darkModeToggled = QtCore.Signal(bool)
    # Fired (in addition to configChanged) only by fields that define the
    # plotted z/x range itself (View box, plus the beam-curve padding
    # fields) -- so the canvas snaps to the new range immediately instead of
    # requiring a manual "Reset View" click, without every unrelated Config
    # toggle (annotations, ...) also fighting a user's manual pan/zoom.
    viewRangeChanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self.config = SystemConfig()

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._build_view_box())
        layout.addWidget(self._build_beam_curve_box())
        layout.addWidget(self._build_annotations_box())
        layout.addWidget(self._build_appearance_box())
        layout.addWidget(self._build_about_box())

        note = QtWidgets.QLabel(
            "Model assumptions: single wavelength, no dispersion, ambient index fixed at "
            "1.0 (air), strictly axis-aligned (no transverse offset or tilt), "
            "no aperture-clipping/vignetting."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        layout.addWidget(note)
        layout.addStretch(1)

    # -- view / aspect ratio -------------------------------------------------
    def _build_view_box(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("View")
        form = QtWidgets.QFormLayout(box)

        self.lock_aspect_check = QtWidgets.QCheckBox("Lock aspect ratio (x:z)")
        self.aspect_ratio_spin = QtWidgets.QDoubleSpinBox()
        self.aspect_ratio_spin.setRange(0.001, 10.0)
        self.aspect_ratio_spin.setDecimals(3)
        self.aspect_ratio_spin.setSingleStep(0.05)
        form.addRow(self.lock_aspect_check, self.aspect_ratio_spin)

        self.auto_z_check = QtWidgets.QCheckBox("Auto z range")
        self.z_min_spin = self._mm_spin()
        self.z_max_spin = self._mm_spin()
        form.addRow(self.auto_z_check)
        form.addRow("z min / max", self._wrap(self.z_min_spin, self.z_max_spin))

        self.auto_x_check = QtWidgets.QCheckBox("Auto x range")
        self.x_min_spin = self._mm_spin()
        self.x_max_spin = self._mm_spin()
        form.addRow(self.auto_x_check)
        form.addRow("x min / max", self._wrap(self.x_min_spin, self.x_max_spin))

        self.reset_view_btn = QtWidgets.QPushButton("Reset View")
        self.reset_view_btn.clicked.connect(self.resetViewRequested.emit)
        form.addRow(self.reset_view_btn)

        for w in (self.aspect_ratio_spin, self.z_min_spin, self.z_max_spin, self.x_min_spin, self.x_max_spin):
            w.valueChanged.connect(self._on_view_range_changed)
        for c in (self.lock_aspect_check, self.auto_z_check, self.auto_x_check):
            c.toggled.connect(self._on_view_range_changed)

        return box

    # -- beam curve sampling / coloring --------------------------------------
    def _build_beam_curve_box(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Beam curve")
        form = QtWidgets.QFormLayout(box)

        self.leading_pad_spin = self._mm_spin()
        self.trailing_mult_spin = QtWidgets.QDoubleSpinBox()
        self.trailing_mult_spin.setRange(0.1, 100.0)
        self.trailing_mult_spin.setSuffix(" × zᵣ")
        self.trailing_min_spin = self._mm_spin()
        self.resolution_spin = QtWidgets.QSpinBox()
        self.resolution_spin.setRange(10, 5000)

        form.addRow("Plot padding before input plane", self.leading_pad_spin)
        form.addRow("Plot padding past output (× zᵣ)", self.trailing_mult_spin)
        form.addRow("Minimum plot padding past output", self.trailing_min_spin)
        form.addRow("Beam curve points per segment", self.resolution_spin)

        for w in (self.leading_pad_spin, self.trailing_mult_spin, self.trailing_min_spin):
            w.valueChanged.connect(self._on_view_range_changed)
        self.resolution_spin.valueChanged.connect(self._on_changed)

        return box

    # -- annotations ----------------------------------------------------------
    def _build_annotations_box(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Annotations")
        layout = QtWidgets.QVBoxLayout(box)
        self.waist_markers_check = QtWidgets.QCheckBox("Show waist markers")
        self.rayleigh_shading_check = QtWidgets.QCheckBox("Shade ±1 Rayleigh range around each waist")
        layout.addWidget(self.waist_markers_check)
        layout.addWidget(self.rayleigh_shading_check)
        for c in (self.waist_markers_check, self.rayleigh_shading_check):
            c.toggled.connect(self._on_changed)
        return box

    # -- appearance (app-level, not part of SystemConfig) ----------------------
    def _build_appearance_box(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Appearance")
        layout = QtWidgets.QVBoxLayout(box)
        self.dark_mode_check = QtWidgets.QCheckBox("Dark mode")
        self.dark_mode_check.toggled.connect(self.darkModeToggled.emit)
        layout.addWidget(self.dark_mode_check)
        return box

    # -- about (read-only, hardcoded, not part of SystemConfig) ---------------
    def _build_about_box(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("About")
        form = QtWidgets.QFormLayout(box)
        form.addRow("Version", QtWidgets.QLabel(APP_VERSION))
        form.addRow("Date of compile", QtWidgets.QLabel(APP_BUILD_DATE))
        form.addRow("Author", QtWidgets.QLabel(APP_AUTHOR))
        form.addRow("Organisation", QtWidgets.QLabel(APP_ORGANISATION))
        return box

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _mm_spin() -> QtWidgets.QDoubleSpinBox:
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(-1.0e6, 1.0e6)
        s.setDecimals(3)
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

    # -- state sync ----------------------------------------------------------
    def _on_view_range_changed(self, *_args) -> None:
        self._on_changed()
        if not self._updating:
            self.viewRangeChanged.emit()

    def _on_changed(self, *_args) -> None:
        if self._updating:
            return
        self.aspect_ratio_spin.setEnabled(self.lock_aspect_check.isChecked())
        auto_z = self.auto_z_check.isChecked()
        auto_x = self.auto_x_check.isChecked()
        self.z_min_spin.setEnabled(not auto_z)
        self.z_max_spin.setEnabled(not auto_z)
        self.x_min_spin.setEnabled(not auto_x)
        self.x_max_spin.setEnabled(not auto_x)

        self.config.lock_aspect_ratio = self.lock_aspect_check.isChecked()
        self.config.aspect_ratio = self.aspect_ratio_spin.value()
        self.config.z_range_min = None if auto_z else self.z_min_spin.value()
        self.config.z_range_max = None if auto_z else self.z_max_spin.value()
        self.config.x_range_min = None if auto_x else self.x_min_spin.value()
        self.config.x_range_max = None if auto_x else self.x_max_spin.value()
        self.config.plot_leading_padding_mm = self.leading_pad_spin.value()
        self.config.plot_trailing_padding_zr_multiple = self.trailing_mult_spin.value()
        self.config.plot_trailing_padding_min_mm = self.trailing_min_spin.value()
        self.config.beam_curve_points_per_segment = int(self.resolution_spin.value())
        self.config.show_waist_markers = self.waist_markers_check.isChecked()
        self.config.show_rayleigh_shading = self.rayleigh_shading_check.isChecked()
        self.configChanged.emit(self.config)

    def set_config(self, config: SystemConfig) -> None:
        self.config = config
        self._updating = True
        self.lock_aspect_check.setChecked(config.lock_aspect_ratio)
        self.aspect_ratio_spin.setValue(config.aspect_ratio)
        self.aspect_ratio_spin.setEnabled(config.lock_aspect_ratio)

        auto_z = config.z_range_min is None or config.z_range_max is None
        self.auto_z_check.setChecked(auto_z)
        self.z_min_spin.setValue(config.z_range_min if config.z_range_min is not None else 0.0)
        self.z_max_spin.setValue(config.z_range_max if config.z_range_max is not None else 0.0)
        self.z_min_spin.setEnabled(not auto_z)
        self.z_max_spin.setEnabled(not auto_z)

        auto_x = config.x_range_min is None or config.x_range_max is None
        self.auto_x_check.setChecked(auto_x)
        self.x_min_spin.setValue(config.x_range_min if config.x_range_min is not None else 0.0)
        self.x_max_spin.setValue(config.x_range_max if config.x_range_max is not None else 0.0)
        self.x_min_spin.setEnabled(not auto_x)
        self.x_max_spin.setEnabled(not auto_x)

        self.leading_pad_spin.setValue(config.plot_leading_padding_mm)
        self.trailing_mult_spin.setValue(config.plot_trailing_padding_zr_multiple)
        self.trailing_min_spin.setValue(config.plot_trailing_padding_min_mm)
        self.resolution_spin.setValue(config.beam_curve_points_per_segment)
        self.waist_markers_check.setChecked(config.show_waist_markers)
        self.rayleigh_shading_check.setChecked(config.show_rayleigh_shading)
        self._updating = False

    def set_dark_mode(self, enabled: bool) -> None:
        self.dark_mode_check.blockSignals(True)
        self.dark_mode_check.setChecked(enabled)
        self.dark_mode_check.blockSignals(False)
