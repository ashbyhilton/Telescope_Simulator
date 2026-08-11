"""The central interactive x-z canvas: beam envelope, optic silhouettes,
waist/Rayleigh annotations, native pan/zoom (from pg.ViewBox), and
click/drag selection of optics."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

from ..model.project import Project
from ..physics.system import OpticalSystem, SystemResult
from .optic_item import OpticItem


class PlotView(pg.PlotWidget):
    opticSelected = QtCore.Signal(int)  # optic id, or -1 for deselect
    opticMoved = QtCore.Signal(int, float, float)  # id, z, x

    def __init__(self, parent=None):
        super().__init__(parent)
        self.showGrid(x=True, y=True, alpha=0.2)
        self.setLabel("bottom", "z", units="mm")
        self.setLabel("left", "x", units="mm")
        self.getViewBox().setAspectLocked(False)

        self._beam_upper = self.plot(pen=pg.mkPen((80, 140, 200), width=2))
        self._beam_lower = self.plot(pen=pg.mkPen((80, 140, 200), width=2))
        self._beam_fill = pg.FillBetweenItem(self._beam_upper, self._beam_lower, brush=pg.mkBrush(80, 140, 200, 60))
        self.addItem(self._beam_fill)
        self._axis_line = self.plot(pen=pg.mkPen((120, 120, 120), width=1, style=QtCore.Qt.PenStyle.DashLine))
        self._waist_markers = pg.ScatterPlotItem(size=9, brush=pg.mkBrush(230, 60, 60, 220), pen=None)
        self.addItem(self._waist_markers)

        self._optic_items: Dict[int, OpticItem] = {}
        self._rayleigh_regions: List[pg.LinearRegionItem] = []
        self._selected_id: Optional[int] = None
        self.project: Optional[Project] = None

    # -- project wiring -----------------------------------------------
    def set_project(self, project: Project) -> None:
        self.project = project
        self.getViewBox().setAspectLocked(project.config.equal_aspect)
        self._sync_optic_items()
        self.refresh()

    def _sync_optic_items(self) -> None:
        if self.project is None:
            return
        current_ids = {o.id for o in self.project.optics}
        for oid in list(self._optic_items.keys()):
            if oid not in current_ids:
                self.removeItem(self._optic_items.pop(oid))
        for optic in self.project.optics:
            item = self._optic_items.get(optic.id)
            if item is None:
                item = OpticItem(optic)
                item.sigClicked.connect(self._on_item_clicked)
                item.sigDragged.connect(self._on_item_dragged)
                self._optic_items[optic.id] = item
                self.addItem(item)
            else:
                item.optic = optic
                item.sync_from_optic()

    def refresh_optic(self, optic_id: int) -> None:
        item = self._optic_items.get(optic_id)
        if item is not None:
            item.sync_from_optic()
        self.refresh()

    def set_selected(self, optic_id: int) -> None:
        self._selected_id = optic_id if optic_id >= 0 else None
        for oid, item in self._optic_items.items():
            item.set_selected(oid == self._selected_id)

    # -- interaction ----------------------------------------------------
    def _on_item_clicked(self, item: OpticItem) -> None:
        self.set_selected(item.optic.id)
        self.opticSelected.emit(item.optic.id)

    def _on_item_dragged(self, item: OpticItem, new_z: float, new_x: float) -> None:
        item.optic.z = new_z
        item.optic.x = new_x
        item.sync_from_optic()
        self.opticMoved.emit(item.optic.id, new_z, new_x)
        self.refresh()

    # -- rendering --------------------------------------------------------
    def refresh(self) -> None:
        if self.project is None:
            return
        try:
            trailing = self._trailing_length()
            result = OpticalSystem(self.project.beam, self.project.optics).propagate(trailing_length=trailing)
        except ValueError:
            return

        z_all, w_all = self._sample_result(result)
        self._beam_upper.setData(z_all, w_all)
        self._beam_lower.setData(z_all, -w_all)
        self._axis_line.setData([z_all[0], z_all[-1]], [0.0, 0.0])

        waists = self._find_waists(result)
        cfg = self.project.config
        if cfg.show_waist_markers and waists:
            self._waist_markers.setData([z for z, _ in waists], [0.0] * len(waists))
        else:
            self._waist_markers.setData([], [])
        self._update_rayleigh_shading(waists if cfg.show_rayleigh_shading else [])

    def _trailing_length(self) -> float:
        cfg = self.project.config
        probe = OpticalSystem(self.project.beam, self.project.optics).propagate()
        zr = probe.output_rayleigh_range
        return max(cfg.plot_trailing_padding_zr_multiple * zr, cfg.plot_trailing_padding_min_mm)

    def _sample_result(self, result: SystemResult):
        cfg = self.project.config
        n_pts = max(cfg.beam_curve_points_per_segment, 2)
        zs, ws = [], []

        lead_start = self.project.beam.z_ref - cfg.plot_leading_padding_mm
        first_seg = result.segments[0]
        if lead_start < first_seg.z_start:
            z_lead = np.linspace(lead_start, first_seg.z_start, n_pts)
            zs.append(z_lead)
            ws.append(first_seg.beam.w(z_lead))

        for seg in result.segments:
            z_seg = np.linspace(seg.z_start, seg.z_end, n_pts)
            zs.append(z_seg)
            ws.append(seg.beam.w(z_seg))
        return np.concatenate(zs), np.concatenate(ws)

    def _find_waists(self, result: SystemResult):
        pts = []
        for seg in result.segments:
            zw = seg.beam.z_waist
            if seg.z_start - 1e-9 <= zw <= seg.z_end + 1e-9:
                pts.append((zw, seg.beam.rayleigh_range))
        return pts

    def _update_rayleigh_shading(self, waists) -> None:
        for region in self._rayleigh_regions:
            self.removeItem(region)
        self._rayleigh_regions = []
        for zw, zr in waists:
            region = pg.LinearRegionItem(values=(zw - zr, zw + zr), movable=False, brush=pg.mkBrush(255, 190, 100, 40))
            region.setZValue(-10)
            for line in region.lines:
                line.setPen(pg.mkPen((255, 170, 80, 120)))
            self.addItem(region)
            self._rayleigh_regions.append(region)
