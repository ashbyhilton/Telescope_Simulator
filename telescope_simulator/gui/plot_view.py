"""The central interactive x-z canvas: beam envelope, optic silhouettes,
waist/Rayleigh annotations, native pan/zoom (from pg.ViewBox), click/drag
selection of optics, and cursor/pinned beam-target tracking."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

from ..model.fit_data import FitDataPoint
from ..model.optics import describe_shape, edge_thickness_from_center, group_key
from ..model.project import Project
from ..physics.beam import GaussianBeam
from ..physics.matrices import thick_lens
from ..physics.system import OpticalSystem, SystemResult
from .color_utils import wavelength_to_rgb
from .mm_axis import MMAxisItem, format_length_mm
from .optic_item import OpticItem

DEFAULT_BEAM_RGB = (80, 140, 200)


@dataclass
class TargetInfo:
    z: float
    beam: GaussianBeam
    label: str
    pinned: bool


class PlotView(pg.PlotWidget):
    opticSelected = QtCore.Signal(int)  # optic id, or -1 for deselect
    opticMoved = QtCore.Signal(int, float)  # id, z
    targetChanged = QtCore.Signal(object)  # TargetInfo

    def __init__(self, parent=None):
        super().__init__(
            parent,
            axisItems={
                "bottom": MMAxisItem(orientation="bottom", base_text="z"),
                "left": MMAxisItem(orientation="left", base_text="x"),
            },
        )
        self.showGrid(x=True, y=True, alpha=0.2)
        self.getViewBox().disableAutoRange()

        self._beam_upper = self.plot(pen=pg.mkPen(DEFAULT_BEAM_RGB, width=2))
        self._beam_lower = self.plot(pen=pg.mkPen(DEFAULT_BEAM_RGB, width=2))
        self._beam_fill = pg.FillBetweenItem(self._beam_upper, self._beam_lower, brush=pg.mkBrush(80, 140, 200, 60))
        self.addItem(self._beam_fill)
        self._axis_line = self.plot(pen=pg.mkPen((120, 120, 120), width=1, style=QtCore.Qt.PenStyle.DashLine))
        self._waist_markers = pg.ScatterPlotItem(size=9, brush=pg.mkBrush(230, 60, 60, 220), pen=None)
        self.addItem(self._waist_markers)
        self._target_marker: Optional[pg.ScatterPlotItem] = None

        self._fit_upper_markers = pg.ScatterPlotItem(size=8, symbol="o", brush=pg.mkBrush(40, 160, 220, 230), pen=None)
        self._fit_lower_markers = pg.ScatterPlotItem(size=8, symbol="o", brush=pg.mkBrush(40, 160, 220, 230), pen=None)
        self.addItem(self._fit_upper_markers)
        self.addItem(self._fit_lower_markers)
        self._fit_labels: List[pg.TextItem] = []
        self._fit_data_points: List[FitDataPoint] = []

        self._optic_items: Dict[int, OpticItem] = {}
        self._hover_overlay = pg.TextItem(
            anchor=(0.0, 1.0), color=(20, 20, 20), fill=(255, 255, 230, 230), border=(120, 120, 90),
        )
        self._hover_overlay.setZValue(100)
        self._hover_overlay.hide()
        self.addItem(self._hover_overlay)
        self._rayleigh_regions: List[pg.LinearRegionItem] = []
        self._selected_id: Optional[int] = None
        self.project: Optional[Project] = None

        self._last_result: Optional[SystemResult] = None
        self._plotted_z_range: Optional[Tuple[float, float]] = None
        self._plotted_w_abs_max: float = 1.0
        self._pinned = False
        self._pinned_z: Optional[float] = None
        self._pinned_info: Optional[TargetInfo] = None
        self._shown_once = False

        self.scene().sigMouseMoved.connect(self._on_scene_mouse_moved)
        self.scene().sigMouseClicked.connect(self._on_scene_mouse_clicked)

    # -- project wiring -----------------------------------------------
    def set_project(self, project: Project) -> None:
        self.project = project
        self._unpin()
        self.getViewBox().setAspectLocked(project.config.lock_aspect_ratio, ratio=project.config.aspect_ratio)
        self._sync_optic_items()
        self.refresh()
        self.apply_default_view()

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
                item.sigHoverEnter.connect(self._on_item_hover_enter)
                item.sigHoverLeave.connect(self._on_item_hover_leave)
                self._optic_items[optic.id] = item
                self.addItem(item)
            else:
                item.optic = optic
                item.sync_from_optic()

    def refresh_optic(self, optic_id: int) -> None:
        self.refresh_optics([optic_id])

    def refresh_optics(self, optic_ids: List[int]) -> None:
        """Batched form of refresh_optic(): resyncs several OpticItems (e.g.
        every member of a composite group after an optimize run moved them
        all) with a single refresh() at the end instead of one per id."""
        for optic_id in optic_ids:
            item = self._optic_items.get(optic_id)
            if item is not None:
                item.sync_from_optic()
        self.refresh()

    def set_selected(self, key: int) -> None:
        """`key` is a `group_key` value: an optic's own id if standalone, or
        its composite group's id -- so selecting one member of a group
        highlights every sibling sharing that group_id."""
        self._selected_id = key if key >= 0 else None
        for item in self._optic_items.values():
            item.set_selected(group_key(item.optic) == self._selected_id)

    # -- interaction: optics ----------------------------------------------
    def _on_item_clicked(self, item: OpticItem) -> None:
        key = group_key(item.optic)
        self.set_selected(key)
        self.opticSelected.emit(key)

    def _on_item_dragged(self, item: OpticItem, new_z: float) -> None:
        # A composite-lens group is a rigid unit: dragging any one member
        # shifts every sibling sharing the same group_key by the same delta,
        # so the group's internal spacings never change from a drag.
        delta = new_z - item.optic.z
        key = group_key(item.optic)
        members = [o for o in self.project.optics if group_key(o) == key]
        for optic in members:
            optic.z += delta
            member_item = self._optic_items.get(optic.id)
            if member_item is not None:
                member_item.set_position(optic.z)
        self.opticMoved.emit(key, min(o.z for o in members))
        self.refresh()

    def _on_item_hover_enter(self, item: OpticItem) -> None:
        self._hover_overlay.setText(self._hover_text(item.optic))
        half_d = max(item.optic.diameter_full, 1e-6) / 2.0
        self._hover_overlay.setPos(item.optic.z, half_d)
        self._hover_overlay.show()

    def _on_item_hover_leave(self, item: OpticItem) -> None:
        self._hover_overlay.hide()

    @staticmethod
    def _hover_text(optic) -> str:
        lines = [optic.name, describe_shape(optic.r1, optic.r2)]
        if optic.group_name:
            lines.insert(0, f"[{optic.group_name}]")
        lines.append(f"Diameter: {format_length_mm(optic.diameter_full)}")
        lines.append(f"Center thickness: {format_length_mm(optic.thickness_center)}")
        edge = edge_thickness_from_center(optic.r1, optic.r2, optic.diameter_full, optic.thickness_center)
        lines.append(f"Edge thickness: {format_length_mm(edge)}")
        r1_text = "flat" if math.isinf(optic.r1) else format_length_mm(optic.r1)
        r2_text = "flat" if math.isinf(optic.r2) else format_length_mm(-optic.r2)
        lines.append(f"R1: {r1_text}   R2: {r2_text}")
        lines.append(f"n: {optic.n:.4g}")
        try:
            m = thick_lens(optic.thickness_center, optic.n, optic.r1, optic.r2)
            power = -m[1, 0]
            efl_text = "∞" if abs(power) < 1e-12 else format_length_mm(1.0 / power)
        except (ValueError, ZeroDivisionError):
            efl_text = "-"
        lines.append(f"EFL: {efl_text}")
        return "\n".join(lines)

    # -- interaction: cursor / pinned target location ----------------------
    def _on_scene_mouse_moved(self, scene_pos) -> None:
        if self._pinned or self.project is None:
            return
        vb = self.getViewBox()
        if not vb.sceneBoundingRect().contains(scene_pos):
            return
        view_pos = vb.mapSceneToView(scene_pos)
        found = self.beam_at(view_pos.x())
        if found is None:
            return
        beam, label, z = found
        self.targetChanged.emit(TargetInfo(z=z, beam=beam, label=label, pinned=False))

    def _on_scene_mouse_clicked(self, ev) -> None:
        if ev.isAccepted() or self._pinned or self.project is None:
            return
        vb = self.getViewBox()
        scene_pos = ev.scenePos()
        if not vb.sceneBoundingRect().contains(scene_pos):
            return
        view_pos = vb.mapSceneToView(scene_pos)
        found = self.beam_at(view_pos.x())
        if found is None:
            return
        beam, label, z = found
        self._pin_at(z, beam, label)

    def _pin_at(self, z: float, beam: GaussianBeam, label: str) -> None:
        self._pinned = True
        self._pinned_z = z
        if self._target_marker is None:
            self._target_marker = pg.ScatterPlotItem(
                size=13, symbol="d", brush=pg.mkBrush(60, 200, 90, 230), pen=pg.mkPen((20, 90, 40), width=1)
            )
            self._target_marker.sigClicked.connect(self._on_marker_clicked)
            self.addItem(self._target_marker)
        self._target_marker.setData([z], [0.0])
        self._pinned_info = TargetInfo(z=z, beam=beam, label=label, pinned=True)
        self.targetChanged.emit(self._pinned_info)

    def _on_marker_clicked(self, *_args) -> None:
        self._unpin()

    def _unpin(self) -> None:
        was_pinned = self._pinned
        self._pinned = False
        self._pinned_z = None
        if self._target_marker is not None:
            self._target_marker.setData([], [])
        if was_pinned and self._pinned_info is not None:
            # Tell listeners (MainWindow's optimize-eligibility tracking) that
            # the pinned target is gone, not just that the marker was cleared
            # -- otherwise a stale pinned TargetInfo lingers downstream.
            self.targetChanged.emit(replace(self._pinned_info, pinned=False))
        self._pinned_info = None

    def beam_at(self, z: float) -> Optional[Tuple[GaussianBeam, str, float]]:
        """Returns (beam, segment label, clamped z) for whichever segment
        covers `z`, clamped to the currently plotted z-range."""
        if self._last_result is None or self._plotted_z_range is None:
            return None
        z_lo, z_hi = self._plotted_z_range
        z = min(max(z, z_lo), z_hi)
        for seg in self._last_result.segments:
            if seg.z_start - 1e-9 <= z <= seg.z_end + 1e-9:
                return seg.beam, seg.label, z
        return None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # The axis labels are set well before the widget has real on-screen
        # geometry (during MainWindow.__init__, before window.show()), so
        # force one more range-apply once shown to guarantee both axes are
        # labeled immediately instead of only after a zoom changes units.
        if not self._shown_once and self.project is not None:
            self._shown_once = True
            self.apply_default_view()

    # -- default / reset view -------------------------------------------
    def apply_default_view(self) -> None:
        if self.project is None or self._plotted_z_range is None:
            return
        cfg = self.project.config
        z_lo = cfg.z_range_min if cfg.z_range_min is not None else self._plotted_z_range[0]
        z_hi = cfg.z_range_max if cfg.z_range_max is not None else self._plotted_z_range[1]
        z_span = max(z_hi - z_lo, 1e-9)

        if cfg.x_range_min is not None and cfg.x_range_max is not None:
            x_lo, x_hi = cfg.x_range_min, cfg.x_range_max
        elif cfg.lock_aspect_ratio:
            half_x = 0.5 * z_span * cfg.aspect_ratio
            x_lo, x_hi = -half_x, half_x
        else:
            half_x = self._plotted_w_abs_max * 1.15
            x_lo, x_hi = -half_x, half_x

        self.setRange(xRange=(z_lo, z_hi), yRange=(x_lo, x_hi), padding=0)

    # -- rendering --------------------------------------------------------
    def refresh(self) -> None:
        if self.project is None:
            return
        try:
            trailing = self._trailing_length()
            result = OpticalSystem(self.project.beam, self.project.optics).propagate(trailing_length=trailing)
        except ValueError:
            return
        self._last_result = result

        z_all, w_all = self._sample_result(result)
        self._plotted_z_range = (float(z_all[0]), float(z_all[-1]))
        self._plotted_w_abs_max = float(np.max(w_all)) if len(w_all) else 1.0

        cfg = self.project.config
        rgb = wavelength_to_rgb(self.project.beam.wavelength_nm)
        pen = pg.mkPen(rgb, width=2)
        self._beam_upper.setPen(pen)
        self._beam_lower.setPen(pen)
        self._beam_fill.setBrush(pg.mkBrush(rgb[0], rgb[1], rgb[2], 60))

        self._beam_upper.setData(z_all, w_all)
        self._beam_lower.setData(z_all, -w_all)
        self._axis_line.setData([z_all[0], z_all[-1]], [0.0, 0.0])

        waists = self._find_waists(result)
        if cfg.show_waist_markers and waists:
            self._waist_markers.setData([z for z, _ in waists], [0.0] * len(waists))
        else:
            self._waist_markers.setData([], [])
        self._update_rayleigh_shading(waists if cfg.show_rayleigh_shading else [])
        self.set_fit_data_points(self.project.fit_data_points)

        if self._pinned and self._pinned_z is not None:
            # A pinned target snapshots a specific GaussianBeam at pin time;
            # re-derive it against the just-recomputed result so the "beam at
            # target location" panel doesn't go stale after an optic is
            # edited or dragged out from under the pin.
            found = self.beam_at(self._pinned_z)
            if found is not None:
                beam, label, z = found
                self._pinned_info = TargetInfo(z=z, beam=beam, label=label, pinned=True)
                self.targetChanged.emit(self._pinned_info)

        # Force a full repaint rather than relying on Qt's dirty-region
        # tracking: item bounding rects can shrink/move sharply when a
        # property edit changes an optic's geometry, and on some platforms
        # partial-update compositing has left stale pixels behind in
        # exactly that situation. Invalidate both the scene's own dirty
        # tracking and the viewport, since either layer caching state could
        # independently be the one holding a stale region.
        self.scene().update()
        self.viewport().update()

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

    def set_fit_data_points(self, points: List[FitDataPoint]) -> None:
        """Draws two small circle markers (z, ±diameter/2) per valid
        Fit-to-data row, plus a point-number text label next to the upper
        marker. Always shown when data is present, like the target-pin
        marker -- no Config-tab visibility toggle, unlike waist markers."""
        self._fit_data_points = points
        for label in self._fit_labels:
            self.removeItem(label)
        self._fit_labels = []

        zs, upper_xs, lower_xs = [], [], []
        for i, p in enumerate(points):
            if not p.is_valid():
                continue
            half = p.diameter_mm / 2.0
            zs.append(p.z_mm)
            upper_xs.append(half)
            lower_xs.append(-half)
            label = pg.TextItem(str(i + 1), anchor=(0.5, 1.0), color=(40, 160, 220))
            label.setPos(p.z_mm, half)
            self.addItem(label)
            self._fit_labels.append(label)

        self._fit_upper_markers.setData(zs, upper_xs)
        self._fit_lower_markers.setData(zs, lower_xs)

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
