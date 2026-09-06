from __future__ import annotations

import time
from typing import Optional

from pyqtgraph.Qt import QtCore, QtWidgets

from ..model.beam_spec import InputBeamSpec
from ..model.config import SystemConfig
from ..model.optics import group_key
from ..model.project import Project, default_demo_project
from ..physics.fit import FitUnavailable, fit_beam_to_data
from ..physics.optimize import (
    OptimizeUnavailable,
    find_governing_optic,
    optimize_for_flatness,
    optimize_for_focus,
)
from ..physics.diffraction import psf_radial_profile
from ..physics.irradiance import transverse_intensity
from ..physics.raytrace import trace_fan, wavefront_at
from ..physics.system import OpticalSystem
from ..physics.zernike import fit_zernike_rotational
from .app_settings import AppSettings
from .plot_view import PlotView, TargetInfo
from .tabs.beam_tab import BeamTab
from .tabs.config_tab import ConfigTab
from .tabs.fit_data_tab import FitDataTab
from .tabs.optics_tab import OpticsTab
from .tabs.raytrace_tab import RaytraceTab, RaytraceView
from .theme import apply_theme


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gaussian Beam Propagation Simulator")
        self.resize(1280, 800)

        self.project: Project = default_demo_project()
        self.current_path: Optional[str] = None
        self.app_settings = AppSettings.load()
        self._current_target: Optional[TargetInfo] = None

        self.plot_view = PlotView()
        self.beam_tab = BeamTab()
        self.optics_tab = OpticsTab()
        self.config_tab = ConfigTab()
        self.fit_data_tab = FitDataTab()
        self.raytrace_tab = RaytraceTab()

        # The Ray Tracing tab's diffraction PSF is the one genuinely
        # expensive thing in a refresh (a multi-megapixel FFT, ~80 ms), and
        # PlotView emits opticMoved on *every* mouse-move of a drag -- paying
        # it per mouse-move drags the canvas down to ~10 fps. Everything else
        # (Gaussian readouts, the canvas itself, the ray overlay) still
        # updates synchronously; only this tab waits for the drag to settle.
        self._raytrace_timer = QtCore.QTimer(self)
        self._raytrace_timer.setSingleShot(True)
        self._raytrace_timer.setInterval(120)
        self._raytrace_timer.timeout.connect(self._refresh_raytrace_tab)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.beam_tab, "Beam")
        tabs.addTab(self.optics_tab, "Optics")
        tabs.addTab(self.config_tab, "Config")
        tabs.addTab(self.fit_data_tab, "Fit to data")
        tabs.addTab(self.raytrace_tab, "Ray Tracing")
        # Wide enough that the Ray Tracing tab's Zernike table and summary
        # rows fit without a horizontal scrollbar -- that tab's content is
        # substantially wider than anything the panel held before v2.0, and
        # a side panel you have to scroll sideways to read is unusable.
        tabs.setMinimumWidth(520)
        tabs.setMaximumWidth(680)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(tabs)
        splitter.addWidget(self.plot_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._build_menu()
        self._wire_signals()
        self._load_project_into_ui()
        self.config_tab.set_dark_mode(self.app_settings.dark_mode)
        apply_theme(QtWidgets.QApplication.instance(), self.plot_view, self.app_settings.dark_mode)
        self.statusBar().showMessage("Ready")

    # -- setup -----------------------------------------------------------
    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")
        menu.addAction("&New", self.on_new)
        menu.addAction("&Open...", self.on_open)
        menu.addAction("&Save", self.on_save)
        menu.addAction("Save &As...", self.on_save_as)

    def _wire_signals(self) -> None:
        self.plot_view.opticSelected.connect(self.on_optic_selected_from_canvas)
        self.plot_view.opticMoved.connect(self.on_optic_moved_from_canvas)
        self.optics_tab.opticsListChanged.connect(self.on_optics_list_changed)
        self.optics_tab.opticPropertyChanged.connect(self.on_optic_property_changed)
        self.optics_tab.selectionChanged.connect(self.plot_view.set_selected)
        self.beam_tab.beamChanged.connect(self.on_beam_changed)
        self.config_tab.configChanged.connect(self.on_config_changed)
        self.config_tab.resetViewRequested.connect(self.plot_view.apply_default_view)
        self.config_tab.viewRangeChanged.connect(self.plot_view.apply_default_view)
        self.config_tab.darkModeToggled.connect(self.on_dark_mode_toggled)
        self.plot_view.targetChanged.connect(self.on_target_changed)
        self.beam_tab.optimizeFlatnessRequested.connect(self.on_optimize_flatness_clicked)
        self.beam_tab.optimizeFocusRequested.connect(self.on_optimize_focus_clicked)
        self.beam_tab.targetPrecisionChanged.connect(self.on_target_precision_changed)
        self.fit_data_tab.fitDataChanged.connect(self.on_fit_data_changed)
        self.fit_data_tab.fitRequested.connect(self.on_fit_requested)
        self.raytrace_tab.rayCountChanged.connect(self.on_ray_count_changed)

    def _load_project_into_ui(self) -> None:
        self.beam_tab.set_beam(self.project.beam)
        # Before set_optics(), so the first EFL/BFL labels are already drawn
        # for the right ambient medium rather than for air.
        self.optics_tab.set_ambient_index(self.project.config.ambient_index)
        self.optics_tab.set_optics(self.project.optics)
        self.config_tab.set_config(self.project.config)
        # The ray count is a SystemConfig field edited on the Ray Tracing tab
        # rather than the Config tab, so it is loaded here alongside the rest
        # of the config rather than inside ConfigTab.set_config().
        self.raytrace_tab.set_ray_count(self.project.config.raytrace_ray_count)
        self.fit_data_tab.set_points(self.project.fit_data_points)
        self.plot_view.set_project(self.project)
        self._current_target = None
        self._refresh_output_readouts()
        # Loading a project is a discrete action, not a drag, so this one
        # doesn't wait on the coalescing timer -- otherwise the tab would
        # keep showing the *previous* project's numbers for the interval.
        self._refresh_raytrace_tab()
        self._recompute_optimize_eligibility()

    # -- canvas -> model --------------------------------------------------
    def on_optic_selected_from_canvas(self, optic_id: int) -> None:
        self.optics_tab.select_optic(optic_id)

    def on_optic_moved_from_canvas(self, optic_id: int, z: float) -> None:
        self.optics_tab.update_optic_position(optic_id, z)
        self._refresh_output_readouts()

    # -- optics tab -> model ------------------------------------------------
    def on_optics_list_changed(self) -> None:
        self.plot_view.set_project(self.project)
        self._refresh_output_readouts()

    def on_optic_property_changed(self, optic_id: int) -> None:
        self.plot_view.refresh_optic(optic_id)
        self._refresh_output_readouts()

    # -- beam / config tabs -> model ------------------------------------------
    def on_beam_changed(self, beam_spec: InputBeamSpec) -> None:
        self.project.beam = beam_spec
        self.plot_view.refresh()
        self._refresh_output_readouts()

    def on_config_changed(self, config: SystemConfig) -> None:
        self.project.config = config
        self.plot_view.set_aspect_locked(config.lock_aspect_ratio, config.aspect_ratio)
        # The Optics tab's focal-length readouts are index-dependent (a lens
        # in water is much weaker than the same lens in air), so they have to
        # be told when the background medium changes -- otherwise that panel
        # keeps reporting in-air values while every other part of the app has
        # already moved to the new index.
        self.optics_tab.set_ambient_index(config.ambient_index)
        self.plot_view.refresh()
        # ambient_index feeds the Gaussian/ABCD model too (see physics/system.py),
        # and raytrace_enabled/ambient_index/raytrace_ray_count all feed the Ray
        # Tracing tab -- unlike the older display-only Config fields, these
        # actually change physics output, not just how it's drawn.
        self._refresh_output_readouts()

    def on_dark_mode_toggled(self, enabled: bool) -> None:
        self.app_settings.dark_mode = enabled
        apply_theme(QtWidgets.QApplication.instance(), self.plot_view, enabled)
        self.app_settings.save()

    # -- beam-at-target -> optimize buttons ------------------------------------
    def on_target_changed(self, info: TargetInfo) -> None:
        self.beam_tab.set_target_result(info)
        # Only a *pinned* target is a stable enough basis for a model-mutating
        # action -- a hover-tracked target changes on every mouse move, and
        # PlotView only re-derives a pinned target after the optic moves (see
        # PlotView.refresh()'s pinned-target block), so an unpinned target
        # would leave this panel visibly stale right after a click.
        self._current_target = info if info.pinned else None
        self._recompute_optimize_eligibility()
        # Deferred, not immediate: PlotView.refresh() re-derives and re-emits
        # the pinned target on *every* call, so during a drag this is the
        # path the expensive PSF actually arrives on -- debouncing only
        # on_optic_moved_from_canvas leaves the drag exactly as slow as it
        # was. A click-to-pin is repaid one timer interval later, which is
        # not perceptible.
        self._schedule_raytrace_refresh()

    def on_ray_count_changed(self, ray_count: int) -> None:
        """The fan's ray count lives on the Ray Tracing tab now (beside the
        analysis it controls) but is still a SystemConfig field, so it saves
        and loads with the project exactly as before."""
        self.project.config.raytrace_ray_count = int(ray_count)
        self.plot_view.refresh()  # the canvas draws this same fan
        self._schedule_raytrace_refresh()

    def on_target_precision_changed(self, _precision_mm: float) -> None:
        self._recompute_optimize_eligibility()

    def _recompute_optimize_eligibility(self) -> None:
        if self._current_target is None:
            self.beam_tab.set_optimize_enabled(
                False, "Pin a target location on the canvas first (click, not just hover)."
            )
            return
        precision_mm = self.beam_tab.target_precision_mm()
        governing, reason = find_governing_optic(
            self.project.optics, self.project.beam.z_ref, self._current_target.z, precision_mm,
        )
        self.beam_tab.set_optimize_enabled(governing is not None, reason)

    def on_optimize_flatness_clicked(self) -> None:
        self._run_optimize(optimize_for_flatness, "flatness")

    def on_optimize_focus_clicked(self) -> None:
        self._run_optimize(optimize_for_focus, "focus")

    def _run_optimize(self, optimize_fn, label: str) -> None:
        if self._current_target is None:
            return
        precision_mm = self.beam_tab.target_precision_mm()
        try:
            result = optimize_fn(
                self.project.beam, self.project.optics, self._current_target.z, precision_mm,
                ambient_index=self.project.config.ambient_index,
            )
        except OptimizeUnavailable as exc:
            self.statusBar().showMessage(f"Optimise for {label}: {exc}")
            self._recompute_optimize_eligibility()
            return

        by_id = {o.id: o for o in self.project.optics}
        optic = by_id.get(result.optic_id)
        if optic is None:
            return
        # result.moved carries every optic that actually needs to shift --
        # just the one optic for a standalone lens, or every member of a
        # composite group (same rigid-group semantics as a canvas drag, see
        # PlotView._on_item_dragged) when the governing unit is a group.
        for moved_id, new_z in result.moved:
            moved_optic = by_id.get(moved_id)
            if moved_optic is not None:
                moved_optic.z = new_z
        # Union of what a canvas drag and an Optics-tab edit each already do
        # individually (see on_optic_moved_from_canvas/on_optic_property_changed)
        # -- this change originates in neither of those views, so both halves
        # are needed: sync the Optics tab's form/summary (keyed by the
        # group, if any, not just the representative optic, so a composite
        # optimize keeps the group panel showing the right anchor z), and
        # fully resync every moved optic's canvas item.
        self.optics_tab.update_optic_position(group_key(optic), min(z for _, z in result.moved))
        self.plot_view.refresh_optics([moved_id for moved_id, _ in result.moved])
        self._refresh_output_readouts()
        self._recompute_optimize_eligibility()

        if result.clamped:
            display_name = optic.group_name if optic.group_id is not None else optic.name
            self.statusBar().showMessage(
                f"Optimise for {label}: '{display_name}' hit the edge of its available "
                f"travel and was clamped there to avoid crossing a neighboring lens "
                f"or the target location."
            )
        else:
            self.statusBar().showMessage(f"Optimise for {label}: done.")

    # -- fit-to-data tab -> model ---------------------------------------------
    def on_fit_data_changed(self) -> None:
        points = self.fit_data_tab.points_snapshot()
        self.project.fit_data_points = points
        # Immediate per-keystroke marker feedback, without waiting on a full
        # propagate()/refresh() -- mirrors why _pin_at() updates its marker
        # directly rather than only through refresh().
        self.plot_view.set_fit_data_points(points)

    def on_fit_requested(self) -> None:
        points = self.fit_data_tab.points_snapshot()
        try:
            result = fit_beam_to_data(
                self.project.beam, self.project.optics, points,
                ambient_index=self.project.config.ambient_index,
            )
        except FitUnavailable as exc:
            self.fit_data_tab.show_error(str(exc))
            self.statusBar().showMessage(f"Fit to data: {exc}")
            return
        self.fit_data_tab.show_error("")
        self.project.beam.z_ref = result.z_waist_mm
        self.project.beam.w_ref = result.w0_mm
        self.project.beam.collimated = True
        self.project.beam.r_ref = None
        self.beam_tab.set_beam(self.project.beam)
        self.plot_view.refresh()
        self._refresh_output_readouts()
        self.statusBar().showMessage(
            f"Fit to data: done (residual {result.objective_value:.4g} mm², {result.iterations} it)."
        )

    def _refresh_output_readouts(self) -> None:
        try:
            result = OpticalSystem(
                self.project.beam, self.project.optics, ambient_index=self.project.config.ambient_index,
            ).propagate()
        except ValueError as exc:
            self.beam_tab.show_error(str(exc))
            # Still recompute the Ray Tracing tab. Returning early here left
            # its Zernike table, RMS/PV summary and PSF plot showing numbers
            # from *before* the system became invalid, with nothing saying
            # they no longer describe it -- exactly the "stale readout that
            # looks live" shape the README's Lessons learned warns about.
            self._schedule_raytrace_refresh()
            return
        self.beam_tab.set_output_result(result)
        self._schedule_raytrace_refresh()

    # -- ray tracing tab (v2.0) -------------------------------------------------
    def _schedule_raytrace_refresh(self) -> None:
        """Coalesce Ray-Tracing-tab recomputes onto one timer -- see the
        timer's construction in __init__ for why. Restarting the timer on
        each call means a continuous drag recomputes once, when it stops."""
        self._raytrace_timer.start()

    def _refresh_raytrace_tab(self) -> None:
        # Recomputing now makes any pending deferred recompute redundant.
        self._raytrace_timer.stop()
        cfg = self.project.config
        if not cfg.raytrace_enabled:
            self.raytrace_tab.set_unavailable("Enable ray tracing in the Config tab to see this analysis.")
            return
        if self._current_target is None:
            self.raytrace_tab.set_unavailable(
                "Pin a target location on the canvas first (click, not just hover)."
            )
            return
        timings_ms = {}
        started = time.perf_counter()
        try:
            fan = trace_fan(
                self.project.beam, self.project.optics,
                ambient_index=cfg.ambient_index, ray_count=cfg.raytrace_ray_count,
            )
            sample = wavefront_at(fan, self._current_target.z)
            # Both radii come from the rays that actually survived to the
            # target, never from the fan's launched half-width -- see
            # wavefront_at()'s docstring.
            fit = fit_zernike_rotational(sample.rho_mm, sample.opd_mm, sample.pupil_radius_mm)
        except ValueError as exc:
            self.raytrace_tab.set_unavailable(str(exc))
            return
        timings_ms["fan+fit"] = (time.perf_counter() - started) * 1e3

        # The diffraction PSF is a strictly weaker calculation than the
        # wavefront analysis above: it can fail (target upstream of the exit
        # plane, aberration too large to sample) on a system whose Zernike
        # terms are perfectly valid, so its failure only blanks its own plot.
        #
        # It propagates from the fan's *exit plane* (the last optic's back
        # vertex) over the bundle's measured half-width there -- not, as the
        # first cut did, from the beam's launch plane over the launched fan
        # half-width, which for a typical project puts the pupil several
        # times too small and the distance several times too long, and so
        # reports an Airy null that is simply the wrong number. The one
        # approximation left is that the fitted W(rho), parameterized by
        # launch height, is evaluated as if rho were the *exit*-pupil
        # coordinate; those two differ only by pupil distortion, which is
        # small for the on-axis systems this app models.
        #
        # The pupil is illuminated by the input beam's own Gaussian, not
        # uniformly: trace_fan deliberately runs the fan out past the beam
        # (2.5 w by default), so treating that whole disk as filled would be
        # a 2.5x-too-wide aperture -- it reported a core about half its true
        # width, with Airy rings a clean Gaussian beam does not have. The
        # apodization is expressed in normalized pupil units, so it is the
        # beam radius over the *launch* pupil radius the fit was normalized
        # by, not the exit-plane one.
        psf, psf_note = None, ""
        started = time.perf_counter()
        try:
            psf = psf_radial_profile(
                fit.coefficients_mm,
                sample.exit_pupil_radius_mm,
                fan.wavelength_nm,
                self._current_target.z - sample.exit_pupil_z,
                gaussian_w_norm=(
                    self.project.beam.w_ref / fit.pupil_radius_mm
                    if fit.pupil_radius_mm > 0.0 else None
                ),
            )
        except ValueError as exc:
            psf_note = str(exc)
        timings_ms["PSF"] = (time.perf_counter() - started) * 1e3

        # The geometric "what's on a card" profile, which is valid in exactly
        # the regime the PSF above is not (see physics/irradiance.py). It
        # traces its own much denser fan, since the fan count on this tab is
        # sized for the wavefront fit, not for a binned histogram.
        card, card_note = None, ""
        started = time.perf_counter()
        try:
            card = transverse_intensity(
                self.project.beam, self.project.optics, self._current_target.z,
                ambient_index=cfg.ambient_index,
            )
        except ValueError as exc:
            card_note = str(exc)
        timings_ms["card"] = (time.perf_counter() - started) * 1e3

        if card is not None and psf is not None and card.spot_radius_mm <= psf.core_radius_mm:
            # Geometric optics has run out of validity here without failing:
            # it still draws a curve, but one narrower than diffraction
            # allows. Say so next to it rather than let the narrower of the
            # two plots look like the better answer. The comparison is
            # against the PSF's measured core, not the hard-aperture Airy
            # null, since the real pupil is Gaussian-illuminated and its core
            # is the wider of the two.
            card_note = (
                "This target is close enough to focus that the geometric spot is smaller than the "
                "diffraction limit, so the real profile is the diffraction PSF below, not this one."
            )

        self.raytrace_tab.set_result(RaytraceView(
            sample=sample,
            fit=fit,
            wavelength_nm=fan.wavelength_nm,
            psf=psf,
            psf_note=psf_note,
            card=card,
            card_note=card_note,
            card_half_span_mm=self._card_half_span_mm(),
            timings_ms=timings_ms,
        ))

    def _card_half_span_mm(self) -> float:
        """Default half-width of the card plot's x axis: 1.5x the largest
        optic's diameter, total, so nothing the system can physically pass
        falls off the edge. Zero when there are no optics, which the tab
        reads as "frame the data instead"."""
        if not self.project.optics:
            return 0.0
        return 0.75 * max(o.diameter_full for o in self.project.optics)

    # -- file menu ------------------------------------------------------------
    def on_new(self) -> None:
        self.project = Project()
        self.current_path = None
        self._load_project_into_ui()
        self.statusBar().showMessage("New project")

    def on_open(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open Project", "", "Beam Project (*.json)")
        if not path:
            return
        self.project = Project.load(path)
        self.current_path = path
        self._load_project_into_ui()
        self.statusBar().showMessage(f"Opened {path}")

    def on_save(self) -> None:
        if self.current_path is None:
            self.on_save_as()
            return
        self.project.save(self.current_path)
        self.statusBar().showMessage(f"Saved {self.current_path}")

    def on_save_as(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Project", "", "Beam Project (*.json)")
        if not path:
            return
        self.project.save(path)
        self.current_path = path
        self.statusBar().showMessage(f"Saved {path}")
