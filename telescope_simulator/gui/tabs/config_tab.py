"""Config tab: display/model settings that don't belong to any one optic
or the beam itself."""
from __future__ import annotations

from pyqtgraph.Qt import QtCore, QtWidgets

from ...model.config import SystemConfig


class ConfigTab(QtWidgets.QWidget):
    configChanged = QtCore.Signal(object)  # SystemConfig

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self.config = SystemConfig()

        form = QtWidgets.QFormLayout()

        self.leading_pad_spin = QtWidgets.QDoubleSpinBox()
        self.leading_pad_spin.setRange(0.0, 1.0e6)
        self.leading_pad_spin.setSuffix(" mm")

        self.trailing_mult_spin = QtWidgets.QDoubleSpinBox()
        self.trailing_mult_spin.setRange(0.1, 100.0)
        self.trailing_mult_spin.setSuffix(" × zᵣ")

        self.trailing_min_spin = QtWidgets.QDoubleSpinBox()
        self.trailing_min_spin.setRange(0.0, 1.0e6)
        self.trailing_min_spin.setSuffix(" mm")

        self.resolution_spin = QtWidgets.QSpinBox()
        self.resolution_spin.setRange(10, 5000)

        self.waist_markers_check = QtWidgets.QCheckBox("Show waist markers")
        self.rayleigh_shading_check = QtWidgets.QCheckBox("Shade ±1 Rayleigh range around each waist")
        self.equal_aspect_check = QtWidgets.QCheckBox("Equal aspect ratio (z vs x)")

        form.addRow("Plot padding before input plane", self.leading_pad_spin)
        form.addRow("Plot padding past output (× zᵣ)", self.trailing_mult_spin)
        form.addRow("Minimum plot padding past output", self.trailing_min_spin)
        form.addRow("Beam curve points per segment", self.resolution_spin)
        form.addRow(self.waist_markers_check)
        form.addRow(self.rayleigh_shading_check)
        form.addRow(self.equal_aspect_check)

        note = QtWidgets.QLabel(
            "Model assumptions (v1): single wavelength, no dispersion, ambient index fixed at "
            "1.0 (air), tilt affects rendering/aperture projection only (no induced astigmatism), "
            "no aperture-clipping/vignetting."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addStretch(1)

        for w in (self.leading_pad_spin, self.trailing_mult_spin, self.trailing_min_spin, self.resolution_spin):
            w.valueChanged.connect(self._on_changed)
        for c in (self.waist_markers_check, self.rayleigh_shading_check, self.equal_aspect_check):
            c.toggled.connect(self._on_changed)

    def _on_changed(self, *_args) -> None:
        if self._updating:
            return
        self.config.plot_leading_padding_mm = self.leading_pad_spin.value()
        self.config.plot_trailing_padding_zr_multiple = self.trailing_mult_spin.value()
        self.config.plot_trailing_padding_min_mm = self.trailing_min_spin.value()
        self.config.beam_curve_points_per_segment = int(self.resolution_spin.value())
        self.config.show_waist_markers = self.waist_markers_check.isChecked()
        self.config.show_rayleigh_shading = self.rayleigh_shading_check.isChecked()
        self.config.equal_aspect = self.equal_aspect_check.isChecked()
        self.configChanged.emit(self.config)

    def set_config(self, config: SystemConfig) -> None:
        self.config = config
        self._updating = True
        self.leading_pad_spin.setValue(config.plot_leading_padding_mm)
        self.trailing_mult_spin.setValue(config.plot_trailing_padding_zr_multiple)
        self.trailing_min_spin.setValue(config.plot_trailing_padding_min_mm)
        self.resolution_spin.setValue(config.beam_curve_points_per_segment)
        self.waist_markers_check.setChecked(config.show_waist_markers)
        self.rayleigh_shading_check.setChecked(config.show_rayleigh_shading)
        self.equal_aspect_check.setChecked(config.equal_aspect)
        self._updating = False
