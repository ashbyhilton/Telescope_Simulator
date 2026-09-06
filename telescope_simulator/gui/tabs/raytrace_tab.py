"""Ray-tracing tab (v2.0): the fan's ray count, plus Zernike/wavefront-error
analysis at a pinned target location, shown only when the Config tab's
ray-tracing model is enabled. Like every other tab, this one never talks to
PlotView or another tab directly -- MainWindow computes the ray trace/Zernike
fit/PSF and pushes the result in through set_result()/set_unavailable(), the
same "MainWindow owns the trigger logic" convention already used for the Beam
tab's optimise buttons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

from ...physics.diffraction import PSFResult
from ...physics.irradiance import TransverseIntensityResult
from ...physics.raytrace import WavefrontSample
from ...physics.zernike import ZERNIKE_DESCRIPTIONS, ZERNIKE_NAMES, ZernikeFitResult
from ..mm_axis import MMAxisItem, format_length_mm


@dataclass
class RaytraceView:
    """Everything the tab draws for one target, assembled by MainWindow.

    A single payload rather than a growing positional argument list: the
    three plots fail independently (the PSF and the card profile are valid in
    opposite regimes -- see physics/irradiance.py), so each carries its own
    optional result and its own note, and the set only keeps growing.
    """

    sample: WavefrontSample
    fit: ZernikeFitResult
    wavelength_nm: float
    psf: Optional[PSFResult] = None
    psf_note: str = ""
    card: Optional[TransverseIntensityResult] = None
    card_note: str = ""
    # Default half-width for the card plot's x axis, in mm. Fixed by the
    # optics rather than by the data, so the spot visibly grows and shrinks
    # as the target moves instead of every target looking the same size
    # under an auto-ranging axis.
    card_half_span_mm: float = 0.0
    timings_ms: Dict[str, float] = field(default_factory=dict)


class RaytraceTab(QtWidgets.QWidget):
    rayCountChanged = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        # Vertical scrolling only. Everything in this tab either wraps or
        # elides, so a horizontal bar would only ever mean something inside
        # is refusing to shrink -- better to squeeze it than to make the
        # whole panel scroll sideways.
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)

        self.status_label = QtWidgets.QLabel(
            "Enable ray tracing in the Config tab, then pin a target location on the canvas."
        )
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #666;")

        layout.addWidget(self._build_settings_box())
        layout.addWidget(self.status_label)
        layout.addWidget(self._build_summary_box())
        layout.addWidget(self._build_zernike_table())
        layout.addWidget(self._build_wavefront_plot())
        layout.addWidget(self._build_card_plot())
        layout.addWidget(self._build_psf_plot())
        layout.addStretch(1)

        scroll.setWidget(content)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.set_unavailable(
            "Enable ray tracing in the Config tab, then pin a target location on the canvas."
        )

    @staticmethod
    def _note(text: str) -> QtWidgets.QLabel:
        """A wrapped, muted caption under a plot. Every plot in this tab
        carries one: each is answering a different question about the same
        target, and which of them to believe depends on the regime (see
        physics/irradiance.py), so none of them is self-explanatory from its
        axes alone."""
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #666;")
        return label

    @staticmethod
    def _mm_plot(base_text: str) -> pg.PlotWidget:
        """A plot whose x axis is a length in mm, using the app's own unit
        handling. pyqtgraph's built-in SI prefixing does not know the
        declared unit is already non-base, so a micron-wide spot on a plain
        units="mm" axis comes out labelled "mmm" -- see gui/mm_axis.py."""
        return pg.PlotWidget(
            axisItems={"bottom": MMAxisItem(orientation="bottom", base_text=base_text)}
        )

    # -- trace settings -------------------------------------------------------
    def _build_settings_box(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Trace settings")
        form = QtWidgets.QFormLayout(box)
        self.ray_count_spin = QtWidgets.QSpinBox()
        self.ray_count_spin.setRange(3, 201)
        self.ray_count_spin.setSingleStep(2)
        self.ray_count_spin.setToolTip(
            "Rounded up to the next odd number, so the fan always contains the axial ray "
            "every other ray's wavefront error is measured against.\n\n"
            "This is the fan drawn on the canvas and fitted for the Zernike terms below. "
            "The transverse-intensity plot traces its own, much denser fan: a binned "
            "profile needs far more rays than a five-term polynomial fit does."
        )
        form.addRow("Number of rays (fan)", self.ray_count_spin)
        self.ray_count_spin.valueChanged.connect(self._on_ray_count_changed)

        self.timing_label = QtWidgets.QLabel("-")
        self.timing_label.setWordWrap(True)
        self.timing_label.setToolTip(
            "Wall-clock time for the last recompute of this tab, broken down by stage."
        )
        form.addRow("Last recompute", self.timing_label)
        return box

    def _on_ray_count_changed(self, value: int) -> None:
        if self._updating:
            return
        self.rayCountChanged.emit(int(value))

    def set_ray_count(self, ray_count: int) -> None:
        self._updating = True
        self.ray_count_spin.setValue(int(ray_count))
        self._updating = False

    def _build_summary_box(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Summary")
        form = QtWidgets.QFormLayout(box)
        self._summary_labels: Dict[str, QtWidgets.QLabel] = {}
        for key, caption in (
            ("survived", "Rays reaching target"),
            ("rms", "RMS wavefront error"),
            ("pv", "Peak-to-valley wavefront error"),
            # How well five m=0 terms describe the traced samples -- a
            # diagnostic, and emphatically not the RMS above, which it used
            # to be mistaken for.
            ("residual", "Zernike fit residual (RMS)"),
            ("pupil", "Pupil radius (traced, at launch)"),
            ("exit_pupil", "Pupil radius (traced, at exit plane)"),
            ("spot", "Geometric spot radius (as seen on a card)"),
            # Measured off the computed PSF, not assumed from an aperture:
            # the pupil is Gaussian-illuminated and so has no null to quote.
            ("core", "Diffraction spot radius (1/e^2 of PSF peak)"),
            ("airy", "Airy first null (uniform-aperture reference)"),
        ):
            lbl = QtWidgets.QLabel("-")
            lbl.setWordWrap(True)
            form.addRow(caption, lbl)
            self._summary_labels[key] = lbl
        return box

    def _build_zernike_table(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Zernike terms (rotationally symmetric only -- see note below)")
        layout = QtWidgets.QVBoxLayout(box)
        self.zernike_table = QtWidgets.QTableWidget(0, 3)
        self.zernike_table.setHorizontalHeaderLabels(["Term", "Coefficient (waves)", "Description"])
        self.zernike_table.horizontalHeader().setStretchLastSection(True)
        self.zernike_table.verticalHeader().setVisible(False)
        self.zernike_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.zernike_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        # The Description column holds full sentences. Let it wrap into the
        # width that's left rather than demand its natural width, which is
        # what would otherwise push a horizontal scrollbar onto the panel.
        self.zernike_table.setWordWrap(True)
        header = self.zernike_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.zernike_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.zernike_table)
        layout.addWidget(self._note(
            "Every other standard Zernike term (coma, astigmatism, trefoil, ...) is exactly zero "
            "for this app's strictly axis-aligned, on-axis model -- not fitted, not omitted, "
            "genuinely zero by rotational symmetry."
        ))
        return box

    def _build_wavefront_plot(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Wavefront error across the pupil")
        layout = QtWidgets.QVBoxLayout(box)
        self.wavefront_plot = self._mm_plot("Pupil radius")
        self.wavefront_plot.setLabel("left", "OPD", units="waves")
        self.wavefront_plot.showGrid(x=True, y=True, alpha=0.2)
        self.wavefront_plot.setMinimumHeight(180)
        self._wavefront_curve = self.wavefront_plot.plot(pen=pg.mkPen((80, 140, 200), width=2))
        layout.addWidget(self.wavefront_plot)
        layout.addWidget(self._note(
            "How far each ray's optical path runs ahead of or behind the axial ray by the time it "
            "reaches the target, measured against a reference sphere centred on the target point "
            "and plotted against the height the ray entered the system at. This is the raw data "
            "the Zernike terms above are fitted to, one point per surviving ray: a flat line is a "
            "perfect wavefront, and the classic upward- or downward-curling tails at the edges of "
            "the pupil are spherical aberration. One wave of error is one wavelength of path "
            "difference; a system is usually called diffraction-limited below about a quarter of "
            "a wave peak-to-valley, or a fourteenth of a wave RMS."
        ))
        return box

    def _build_card_plot(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Transverse intensity at target (what you'd see on a card)")
        layout = QtWidgets.QVBoxLayout(box)
        self.card_status_label = QtWidgets.QLabel("")
        self.card_status_label.setWordWrap(True)
        self.card_status_label.setStyleSheet("color: #666;")
        self.card_status_label.hide()
        layout.addWidget(self.card_status_label)
        self.card_plot = self._mm_plot("x at target")
        self.card_plot.setLabel("left", "Relative irradiance")
        self.card_plot.showGrid(x=True, y=True, alpha=0.2)
        self.card_plot.setMinimumHeight(180)
        self._card_curve = self.card_plot.plot(pen=pg.mkPen((90, 175, 100), width=2))
        layout.addWidget(self.card_plot)
        layout.addWidget(self._note(
            "A full slice across the spot: irradiance I(x, 0), power per unit area, from one side "
            "of the axis to the other. Each ray is weighted by the input beam's Gaussian intensity "
            "at its launch height, binned by the area of the annulus it lands in, and spread over "
            "the width of the ray tube it represents so the curve is smooth rather than a "
            "staircase of individual rays. This is deliberately not the radial power distribution "
            "2*pi*r*I(r), which differs by exactly that factor and is zero on axis, peaking in a "
            "ring even for an ordinary Gaussian spot. The profile here is the visible spot "
            "whenever it is much larger than the diffraction limit -- a defocused or aberrated "
            "beam. It is the wrong picture at best focus, where geometric optics collapses to a "
            "point and the diffraction PSF below is the real profile. The default x range is "
            "fixed at 1.5x the largest optic's diameter, so the spot can be seen growing and "
            "shrinking as the target moves rather than being rescaled to fill the frame; zoom and "
            "pan freely."
        ))
        return box

    def _build_psf_plot(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox(
            "Transverse intensity profile at target (diffraction PSF, from the exit plane)"
        )
        layout = QtWidgets.QVBoxLayout(box)
        # The PSF can be unavailable while the wavefront analysis above is
        # perfectly valid (target upstream of the exit plane, or aberration
        # too large to sample without aliasing), so it carries its own
        # status line rather than blanking the whole tab.
        self.psf_status_label = QtWidgets.QLabel("")
        self.psf_status_label.setWordWrap(True)
        self.psf_status_label.setStyleSheet("color: #666;")
        self.psf_status_label.hide()
        layout.addWidget(self.psf_status_label)
        self.psf_plot = self._mm_plot("x at target")
        self.psf_plot.setLabel("left", "Relative intensity")
        self.psf_plot.showGrid(x=True, y=True, alpha=0.2)
        self.psf_plot.setMinimumHeight(180)
        self._psf_curve = self.psf_plot.plot(pen=pg.mkPen((230, 120, 40), width=2))
        layout.addWidget(self.psf_plot)
        layout.addWidget(self._note(
            "The diffraction pattern the wavefront above produces at the target: a Fraunhofer "
            "propagation of the fitted pupil from the system's exit plane, sliced through the "
            "axis on the same signed x as the plot above so the two can be read against each "
            "other. This is the true profile at and near best focus, where the spot size is set "
            "by the wavelength and the aperture rather than by where the rays land. The pupil "
            "carries the input beam's own Gaussian illumination, so a clean, unclipped system "
            "gives a Gaussian far field rather than the textbook Airy rings of a uniformly filled "
            "aperture -- rings appear once an aperture actually cuts into the beam. Aberration "
            "fills in whatever nulls there are and moves light out of the central core. The x "
            "range defaults to a few core widths; the computed profile extends far past it."
        ))
        return box

    # -- data in -------------------------------------------------------------
    def set_unavailable(self, reason: str) -> None:
        self.status_label.setText(reason)
        self.status_label.setStyleSheet("color: #666;")
        for lbl in self._summary_labels.values():
            lbl.setText("-")
        self.timing_label.setText("-")
        self.zernike_table.setRowCount(0)
        self._wavefront_curve.setData([], [])
        self._psf_curve.setData([], [])
        self.psf_status_label.setText("")
        self.psf_status_label.hide()
        self._card_curve.setData([], [])
        self.card_status_label.setText("")
        self.card_status_label.hide()

    def set_result(self, view: RaytraceView) -> None:
        self.status_label.setText("")
        sample, fit = view.sample, view.fit
        wavelength_mm = view.wavelength_nm * 1e-6
        psf = view.psf

        self._summary_labels["survived"].setText(f"{sample.n_surviving} / {sample.n_total}")
        self._summary_labels["rms"].setText(
            f"{fit.rms_mm / wavelength_mm:.4g} waves ({format_length_mm(fit.rms_mm)})"
        )
        self._summary_labels["pv"].setText(
            f"{fit.peak_to_valley_mm / wavelength_mm:.4g} waves ({format_length_mm(fit.peak_to_valley_mm)})"
        )
        self._summary_labels["residual"].setText(
            f"{fit.residual_rms_mm / wavelength_mm:.3g} waves ({format_length_mm(fit.residual_rms_mm)})"
        )
        self._summary_labels["pupil"].setText(format_length_mm(fit.pupil_radius_mm))
        self._summary_labels["exit_pupil"].setText(format_length_mm(sample.exit_pupil_radius_mm))
        self._summary_labels["core"].setText(
            format_length_mm(psf.core_radius_mm) if psf is not None else "-"
        )
        self._summary_labels["airy"].setText(
            format_length_mm(psf.airy_first_null_mm) if psf is not None else "-"
        )
        self.timing_label.setText(self._format_timings(view.timings_ms))

        self.zernike_table.setRowCount(len(fit.coefficients_mm))
        for row, (noll, coeff_mm) in enumerate(sorted(fit.coefficients_mm.items())):
            name = ZERNIKE_NAMES.get(noll, f"Noll {noll}")
            desc = ZERNIKE_DESCRIPTIONS.get(noll, "")
            self.zernike_table.setItem(row, 0, QtWidgets.QTableWidgetItem(f"{name} (Noll {noll})"))
            self.zernike_table.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{coeff_mm / wavelength_mm:.4g}"))
            self.zernike_table.setItem(row, 2, QtWidgets.QTableWidgetItem(desc))
        self.zernike_table.resizeRowsToContents()

        rho = list(sample.rho_mm)
        opd_waves = [v / wavelength_mm for v in sample.opd_mm]
        order = sorted(range(len(rho)), key=lambda i: rho[i])
        self._wavefront_curve.setData([rho[i] for i in order], [opd_waves[i] for i in order])

        self._set_psf(psf, view.psf_note)
        self._set_card(view.card, view.card_note, view.card_half_span_mm)

    @staticmethod
    def _format_timings(timings_ms: Dict[str, float]) -> str:
        """Total, plus the per-stage breakdown. The breakdown is the useful
        half: it is what shows that raising the ray count above costs almost
        nothing, while pinning a target near focus is what actually makes
        this tab feel slow."""
        if not timings_ms:
            return "-"
        total = sum(timings_ms.values())
        parts = ", ".join(f"{name} {ms:.0f}" for name, ms in timings_ms.items())
        return f"{total:.0f} ms  ({parts})"

    def _set_psf(self, psf: Optional[PSFResult], note: str) -> None:
        if psf is None:
            self._psf_curve.setData([], [])
            self.psf_status_label.setText(note or "Not available for this target.")
            self.psf_status_label.show()
            return
        # The FFT's radial profile is one-sided and runs out to the full
        # half-window, which is ~100x the spot for a typical project. Mirror
        # it about the axis -- the pupil is rotationally symmetric, so the
        # negative half is exact rather than interpolated -- and then frame
        # the core, since on a linear axis the untouched range draws the
        # whole pattern as a single spike at the origin.
        x = np.concatenate((-psf.radius_mm_at_target[:0:-1], psf.radius_mm_at_target))
        y = np.concatenate((psf.intensity[:0:-1], psf.intensity))
        self._psf_curve.setData(x, y)
        half = psf.display_radius_mm if psf.display_radius_mm > 0.0 else float(x[-1])
        self.psf_plot.setXRange(-half, half, padding=0.0)
        # Clear, not just hide: a hidden label that keeps its old text still
        # answers .text() with a reason that no longer applies.
        self.psf_status_label.setText("")
        self.psf_status_label.hide()

    def _set_card(self, card: Optional[TransverseIntensityResult], note: str,
                  half_span_mm: float) -> None:
        if card is None:
            self._card_curve.setData([], [])
            self.card_status_label.setText(note or "Not available for this target.")
            self.card_status_label.show()
            self._summary_labels["spot"].setText("-")
            return
        x, y = card.x_mm, card.intensity
        data_half = float(np.max(np.abs(x)))
        half = half_span_mm if half_span_mm > 0.0 else data_half
        if half > data_half:
            # The default x range comes from the optics, not from the data,
            # so a spot much smaller than the aperture leaves the curve
            # stopping in mid-air well inside the frame. Geometric optics
            # puts exactly nothing out there, so draw the zero rather than
            # let a truncated line imply the profile is simply unknown past
            # its last bin.
            x = np.concatenate(([-half], x, [half]))
            y = np.concatenate(([0.0], y, [0.0]))
        self._card_curve.setData(x, y)
        self.card_plot.setXRange(-half, half, padding=0.0)
        # A note can also accompany a curve that *was* computed -- most
        # usefully when the geometric spot has shrunk below the diffraction
        # limit and this plot, while drawable, is no longer the one to read.
        self.card_status_label.setText(note)
        self.card_status_label.setVisible(bool(note))
        self._summary_labels["spot"].setText(
            f"{format_length_mm(card.spot_radius_mm)} "
            f"(half the power within {format_length_mm(card.encircled_50_mm)})"
        )
