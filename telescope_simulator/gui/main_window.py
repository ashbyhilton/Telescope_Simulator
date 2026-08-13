from __future__ import annotations

from typing import Optional

from pyqtgraph.Qt import QtWidgets

from ..model.beam_spec import InputBeamSpec
from ..model.config import SystemConfig
from ..model.project import Project, default_demo_project
from ..physics.fit import FitUnavailable, fit_beam_to_data
from ..physics.optimize import (
    OptimizeUnavailable,
    find_governing_optic,
    optimize_for_flatness,
    optimize_for_focus,
)
from ..physics.system import OpticalSystem
from .app_settings import AppSettings
from .plot_view import PlotView, TargetInfo
from .tabs.beam_tab import BeamTab
from .tabs.config_tab import ConfigTab
from .tabs.fit_data_tab import FitDataTab
from .tabs.optics_tab import OpticsTab
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

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.beam_tab, "Beam")
        tabs.addTab(self.optics_tab, "Optics")
        tabs.addTab(self.config_tab, "Config")
        tabs.addTab(self.fit_data_tab, "Fit to data")
        tabs.setMinimumWidth(360)
        tabs.setMaximumWidth(460)

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

    def _load_project_into_ui(self) -> None:
        self.beam_tab.set_beam(self.project.beam)
        self.optics_tab.set_optics(self.project.optics)
        self.config_tab.set_config(self.project.config)
        self.fit_data_tab.set_points(self.project.fit_data_points)
        self.plot_view.set_project(self.project)
        self._refresh_output_readouts()
        self._current_target = None
        self._recompute_optimize_eligibility()

    # -- canvas -> model --------------------------------------------------
    def on_optic_selected_from_canvas(self, optic_id: int) -> None:
        self.optics_tab.select_optic(optic_id)

    def on_optic_moved_from_canvas(self, optic_id: int, z: float, x: float) -> None:
        self.optics_tab.update_optic_position(optic_id, z, x)
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
        self.plot_view.getViewBox().setAspectLocked(config.lock_aspect_ratio, ratio=config.aspect_ratio)
        self.plot_view.refresh()

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
            )
        except OptimizeUnavailable as exc:
            self.statusBar().showMessage(f"Optimise for {label}: {exc}")
            self._recompute_optimize_eligibility()
            return

        optic = next((o for o in self.project.optics if o.id == result.optic_id), None)
        if optic is None:
            return
        optic.z = result.z
        # Union of what a canvas drag and an Optics-tab edit each already do
        # individually (see on_optic_moved_from_canvas/on_optic_property_changed)
        # -- this change originates in neither of those views, so both halves
        # are needed: sync the Optics tab's form, and fully resync the canvas
        # (which also re-derives the pinned target panel via refresh()).
        self.optics_tab.update_optic_position(optic.id, optic.z, optic.x)
        self.plot_view.refresh_optic(optic.id)
        self._refresh_output_readouts()
        self._recompute_optimize_eligibility()

        if result.clamped:
            self.statusBar().showMessage(
                f"Optimise for {label}: '{optic.name}' hit the edge of its available "
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
            result = fit_beam_to_data(self.project.beam, self.project.optics, points)
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
            result = OpticalSystem(self.project.beam, self.project.optics).propagate()
        except ValueError as exc:
            self.beam_tab.show_error(str(exc))
            return
        self.beam_tab.set_output_result(result)

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
