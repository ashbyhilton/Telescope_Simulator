from __future__ import annotations

from typing import Optional

from pyqtgraph.Qt import QtWidgets

from ..model.beam_spec import InputBeamSpec
from ..model.config import SystemConfig
from ..model.project import Project, default_demo_project
from ..physics.system import OpticalSystem
from .plot_view import PlotView
from .tabs.beam_tab import BeamTab
from .tabs.config_tab import ConfigTab
from .tabs.optics_tab import OpticsTab


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gaussian Beam Propagation Simulator")
        self.resize(1280, 800)

        self.project: Project = default_demo_project()
        self.current_path: Optional[str] = None

        self.plot_view = PlotView()
        self.beam_tab = BeamTab()
        self.optics_tab = OpticsTab()
        self.config_tab = ConfigTab()

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.beam_tab, "Beam")
        tabs.addTab(self.optics_tab, "Optics")
        tabs.addTab(self.config_tab, "Config")
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

    def _load_project_into_ui(self) -> None:
        self.beam_tab.set_beam(self.project.beam)
        self.optics_tab.set_optics(self.project.optics)
        self.config_tab.set_config(self.project.config)
        self.plot_view.set_project(self.project)
        self._refresh_output_readouts()

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
        self.plot_view.getViewBox().setAspectLocked(config.equal_aspect)
        self.plot_view.refresh()

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
