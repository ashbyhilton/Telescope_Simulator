"""Beam tab: input beam editor plus read-only output beam readouts."""
from __future__ import annotations

import math

from pyqtgraph.Qt import QtCore, QtWidgets

from ...model.beam_spec import InputBeamSpec
from ...physics.system import SystemResult


class BeamTab(QtWidgets.QWidget):
    beamChanged = QtCore.Signal(object)  # InputBeamSpec

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self.beam = InputBeamSpec()

        input_box = QtWidgets.QGroupBox("Input beam")
        form = QtWidgets.QFormLayout(input_box)

        self.diameter_spin = QtWidgets.QDoubleSpinBox()
        self.diameter_spin.setRange(0.0001, 10000.0)
        self.diameter_spin.setDecimals(4)
        self.diameter_spin.setSuffix(" mm")

        self.z_ref_spin = QtWidgets.QDoubleSpinBox()
        self.z_ref_spin.setRange(-1.0e6, 1.0e6)
        self.z_ref_spin.setDecimals(3)
        self.z_ref_spin.setSuffix(" mm")

        self.wavelength_spin = QtWidgets.QDoubleSpinBox()
        self.wavelength_spin.setRange(1.0, 20000.0)
        self.wavelength_spin.setDecimals(2)
        self.wavelength_spin.setSuffix(" nm")

        self.collimated_check = QtWidgets.QCheckBox("Collimated here (flat wavefront / at waist)")
        self.collimated_check.setToolTip(
            "Check this if z_ref is the beam waist (flat wavefront). Uncheck to enter a\n"
            "measured beam that is already converging or diverging at z_ref."
        )

        self.r_ref_spin = QtWidgets.QDoubleSpinBox()
        self.r_ref_spin.setRange(-1.0e7, 1.0e7)
        self.r_ref_spin.setDecimals(3)
        self.r_ref_spin.setSuffix(" mm")
        self.r_ref_spin.setToolTip("Measured wavefront radius of curvature at z_ref (only used when not collimated).")

        self.x_offset_spin = QtWidgets.QDoubleSpinBox()
        self.x_offset_spin.setRange(-1.0e6, 1.0e6)
        self.x_offset_spin.setDecimals(4)
        self.x_offset_spin.setSuffix(" mm")

        form.addRow("Diameter (1/e²) at z_ref", self.diameter_spin)
        form.addRow("z_ref", self.z_ref_spin)
        form.addRow("Wavelength", self.wavelength_spin)
        form.addRow(self.collimated_check)
        form.addRow("Wavefront ROC at z_ref", self.r_ref_spin)
        form.addRow("x offset", self.x_offset_spin)

        for w in (self.diameter_spin, self.z_ref_spin, self.wavelength_spin,
                  self.r_ref_spin, self.x_offset_spin):
            w.valueChanged.connect(self._on_changed)
        self.collimated_check.toggled.connect(self._on_collimated_toggled)

        output_box = QtWidgets.QGroupBox("Output beam (after last optic)")
        out_form = QtWidgets.QFormLayout(output_box)
        self.out_zr = QtWidgets.QLabel("-")
        self.out_diam_at_zr = QtWidgets.QLabel("-")
        self.out_q = QtWidgets.QLabel("-")
        self.out_div = QtWidgets.QLabel("-")
        self.out_waist_z = QtWidgets.QLabel("-")
        self.out_waist_diam = QtWidgets.QLabel("-")
        out_form.addRow("Rayleigh range", self.out_zr)
        out_form.addRow("Diameter at +1 zᵣ past last optic", self.out_diam_at_zr)
        out_form.addRow("Complex q", self.out_q)
        out_form.addRow("Divergence half-angle", self.out_div)
        out_form.addRow("Next waist z (absolute)", self.out_waist_z)
        out_form.addRow("Next waist diameter", self.out_waist_diam)

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(input_box)
        layout.addWidget(output_box)
        layout.addWidget(self.error_label)
        layout.addStretch(1)

    def _on_collimated_toggled(self, checked: bool) -> None:
        self.r_ref_spin.setEnabled(not checked)
        self._on_changed()

    def _on_changed(self, *_args) -> None:
        if self._updating:
            return
        self.beam.w_ref = self.diameter_spin.value() / 2.0
        self.beam.z_ref = self.z_ref_spin.value()
        self.beam.wavelength_nm = self.wavelength_spin.value()
        self.beam.collimated = self.collimated_check.isChecked()
        self.beam.r_ref = None if self.beam.collimated else self.r_ref_spin.value()
        self.beam.x_offset = self.x_offset_spin.value()
        self.beamChanged.emit(self.beam)

    def set_beam(self, beam: InputBeamSpec) -> None:
        self.beam = beam
        self._updating = True
        self.diameter_spin.setValue(beam.w_ref * 2.0)
        self.z_ref_spin.setValue(beam.z_ref)
        self.wavelength_spin.setValue(beam.wavelength_nm)
        self.collimated_check.setChecked(beam.collimated)
        self.r_ref_spin.setEnabled(not beam.collimated)
        self.r_ref_spin.setValue(beam.r_ref if beam.r_ref is not None else 0.0)
        self.x_offset_spin.setValue(beam.x_offset)
        self._updating = False

    def set_output_result(self, result: SystemResult) -> None:
        self.error_label.setText("")
        self.out_zr.setText(f"{result.output_rayleigh_range:.4g} mm")
        self.out_diam_at_zr.setText(f"{result.diameter_one_zr_past_last_optic:.4g} mm")
        q = result.output_q
        self.out_q.setText(f"{q.real:.4g} + {q.imag:.4g}i  mm")
        deg = result.output_divergence_half_angle * 180.0 / math.pi
        self.out_div.setText(f"{result.output_divergence_half_angle * 1e3:.4g} mrad ({deg:.4g}°)")
        self.out_waist_z.setText(f"{result.next_waist_z:.4g} mm")
        self.out_waist_diam.setText(f"{result.next_waist_diameter:.4g} mm")

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
