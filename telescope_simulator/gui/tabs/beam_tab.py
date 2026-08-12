"""Beam tab: input beam editor, plus read-only characteristics panels for
the input beam, the output beam (after the last optic), and the beam at a
cursor-tracked / click-pinned target z location."""
from __future__ import annotations

import math
from typing import Dict, Tuple

from pyqtgraph.Qt import QtCore, QtWidgets

from ...model.beam_spec import InputBeamSpec
from ...physics.beam import GaussianBeam
from ...physics.system import SystemResult
from ..mm_axis import format_length_mm


def _format_common(zr: float, q: complex, div: float, waist_z: float, waist_d: float) -> Dict[str, str]:
    deg = div * 180.0 / math.pi
    return {
        "zr": format_length_mm(zr),
        "q": f"{q.real:.4g} + {q.imag:.4g}i  mm",
        "div": f"{div * 1e3:.4g} mrad ({deg:.4g}°)",
        "waist_z": format_length_mm(waist_z),
        "waist_d": format_length_mm(waist_d),
    }


class BeamTab(QtWidgets.QWidget):
    beamChanged = QtCore.Signal(object)  # InputBeamSpec

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self.beam = InputBeamSpec()

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)

        content_layout.addWidget(self._build_input_form())
        content_layout.addWidget(self._build_input_characteristics_box())
        content_layout.addWidget(self._build_output_box())
        content_layout.addWidget(self._build_target_box())

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        content_layout.addWidget(self.error_label)
        content_layout.addStretch(1)

        scroll.setWidget(content)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    # -- input form ---------------------------------------------------------
    def _build_input_form(self) -> QtWidgets.QWidget:
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

        return input_box

    # -- characteristics groups ----------------------------------------------
    @staticmethod
    def _build_readout_group(title: str, rows: Tuple[Tuple[str, str], ...]) -> Tuple[QtWidgets.QGroupBox, Dict[str, QtWidgets.QLabel]]:
        box = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(box)
        labels: Dict[str, QtWidgets.QLabel] = {}
        for key, caption in rows:
            lbl = QtWidgets.QLabel("-")
            form.addRow(caption, lbl)
            labels[key] = lbl
        return box, labels

    def _build_input_characteristics_box(self) -> QtWidgets.QWidget:
        box, labels = self._build_readout_group(
            "Input beam characteristics",
            (
                ("zr", "Rayleigh range"),
                ("q", "Complex q at z_ref"),
                ("div", "Divergence half-angle"),
                ("waist_z", "Waist z (absolute)"),
                ("waist_d", "Waist diameter"),
            ),
        )
        self._input_labels = labels
        return box

    def _build_output_box(self) -> QtWidgets.QWidget:
        box, labels = self._build_readout_group(
            "Output beam (after last optic)",
            (
                ("zr", "Rayleigh range"),
                ("diam_at_zr", "Diameter at +1 zᵣ past last optic"),
                ("q", "Complex q"),
                ("div", "Divergence half-angle"),
                ("waist_z", "Next waist z (absolute)"),
                ("waist_d", "Next waist diameter"),
            ),
        )
        self._output_labels = labels
        return box

    def _build_target_box(self) -> QtWidgets.QWidget:
        box, labels = self._build_readout_group(
            "Beam at target location",
            (
                ("status", "Status"),
                ("element", "In"),
                ("z", "Target z"),
                ("diam", "Diameter at z"),
                ("roc", "Wavefront ROC at z"),
                ("zr", "Rayleigh range (local)"),
                ("q", "Complex q at z"),
                ("div", "Divergence half-angle (local)"),
                ("waist_z", "Local waist z (absolute)"),
                ("waist_d", "Local waist diameter"),
            ),
        )
        self._target_labels = labels
        return box

    # -- input form <-> model -------------------------------------------------
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
        self._update_input_characteristics()
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
        self._update_input_characteristics()

    def _update_input_characteristics(self) -> None:
        r_ref = None if self.beam.collimated else self.beam.r_ref
        beam = GaussianBeam.from_measurement(
            z_ref=self.beam.z_ref, w_ref=self.beam.w_ref, wavelength_nm=self.beam.wavelength_nm,
            n=1.0, r_ref=r_ref,
        )
        values = _format_common(beam.rayleigh_range, beam.q_ref, beam.divergence_half_angle, beam.z_waist, 2.0 * beam.w0)
        for key, text in values.items():
            self._input_labels[key].setText(text)

    # -- output / error -----------------------------------------------------
    def set_output_result(self, result: SystemResult) -> None:
        self.error_label.setText("")
        values = _format_common(
            result.output_rayleigh_range, result.output_q, result.output_divergence_half_angle,
            result.next_waist_z, result.next_waist_diameter,
        )
        for key, text in values.items():
            self._output_labels[key].setText(text)
        self._output_labels["diam_at_zr"].setText(format_length_mm(result.diameter_one_zr_past_last_optic))

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)

    # -- target location ------------------------------------------------------
    def set_target_result(self, info) -> None:
        labels = self._target_labels
        labels["status"].setText("Pinned" if info.pinned else "Tracking cursor")
        labels["element"].setText(info.label)
        labels["z"].setText(format_length_mm(info.z))
        labels["diam"].setText(format_length_mm(2.0 * info.beam.w(info.z)))
        roc = info.beam.radius_of_curvature(info.z)
        labels["roc"].setText("∞ (flat)" if math.isinf(roc) else format_length_mm(roc))
        common = _format_common(
            info.beam.rayleigh_range, info.beam.q_at(info.z), info.beam.divergence_half_angle,
            info.beam.z_waist, 2.0 * info.beam.w0,
        )
        for key in ("zr", "q", "div", "waist_z", "waist_d"):
            labels[key].setText(common[key])
