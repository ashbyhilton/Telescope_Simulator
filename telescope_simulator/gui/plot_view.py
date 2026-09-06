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
from ..physics.raytrace import RayFanResult, trace_fan
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

        self._ray_fan_curve = pg.PlotCurveItem(pen=pg.mkPen((235, 130, 20), width=1))
        self.addItem(self._ray_fan_curve)
        self._ray_stop_markers = pg.ScatterPlotItem(
            size=7, symbol="x", brush=None, pen=pg.mkPen((210, 30, 30, 230), width=1.5),
        )
        self.addItem(self._ray_stop_markers)
        self._last_ray_fan: Optional[RayFanResult] = None

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
        # The physically-derived span (input padding .. output Rayleigh
        # padding). Still what "reset view" frames; no longer what the curves
        # are drawn over -- see _draw_z_range().
        self._plotted_z_range: Optional[Tuple[float, float]] = None
        self._drawn_z_range: Optional[Tuple[float, float]] = None
        self._plotted_w_abs_max: float = 1.0
        self._pinned = False
        self._pinned_z: Optional[float] = None
        self._pinned_info: Optional[TargetInfo] = None
        self._shown_once = False

        self.scene().sigMouseMoved.connect(self._on_scene_mouse_moved)
        self.scene().sigMouseClicked.connect(self._on_scene_mouse_clicked)
        # Panning or zooming exposes z the curves weren't drawn over, so the
        # beam and rays are re-extended to fill the new window. Safe against
        # recursion: this only ever calls setData, never setRange, and the
        # view box has auto-ranging disabled.
        self.getViewBox().sigXRangeChanged.connect(self._on_x_range_changed)

    # -- project wiring -----------------------------------------------
    def set_aspect_locked(self, locked: bool, ratio: float) -> None:
        """Apply the aspect lock without moving the view when releasing it.

        A ViewBox keeps the range it was *asked* for alongside the wider one
        the aspect lock makes it actually show, and dropping the lock snaps
        straight back to the request -- so unticking the box jumped the
        canvas to whatever range predated the constraint, which reads as the
        checkbox having changed something about the system rather than about
        the view. Re-asserting what was on screen keeps "unlock" meaning only
        "stop constraining"."""
        vb = self.getViewBox()
        was_locked = bool(vb.state.get("aspectLocked"))
        (z_lo, z_hi), (x_lo, x_hi) = vb.viewRange()
        vb.setAspectLocked(locked, ratio=ratio)
        if was_locked and not locked:
            self.setRange(xRange=(z_lo, z_hi), yRange=(x_lo, x_hi), padding=0)

    def set_project(self, project: Project) -> None:
        self.project = project
        self._unpin()
        self.set_aspect_locked(project.config.lock_aspect_ratio, project.config.aspect_ratio)
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

    def _hover_text(self, optic) -> str:
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
            # In the project's background medium, not unconditionally in air
            # -- otherwise this overlay contradicts the Optics tab's own EFL
            # readout for the same lens whenever the medium isn't air.
            ambient = self.project.config.ambient_index if self.project is not None else 1.0
            m = thick_lens(optic.thickness_center, optic.n, optic.r1, optic.r2, ambient)
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
        # No `self._pinned` guard: a left click moves the target to wherever
        # it lands, whether or not one is already pinned. Requiring the old
        # marker to be cleared first made every retarget a two-click job for
        # no benefit. Clicking the marker itself still unpins -- that path
        # accepts the event before it reaches here, so it can't re-pin in the
        # same click. The button check matters more now that clicks are
        # consequential even when pinned: a right click is pyqtgraph's
        # context menu, not a retarget.
        if ev.isAccepted() or self.project is None:
            return
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
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
        covers `z`, clamped to the range the beam is currently drawn over.

        Beyond the ends of propagate()'s segment list, the first/last
        segment's beam is still exact (it's an analytic GaussianBeam, not a
        sampled curve), so a target pinned out in the extended part of the
        canvas is answered from it -- the same out-of-window extrapolation
        physics.system.segment_covering already documents. Without that, a
        click on visibly-drawn beam out past the last segment would silently
        do nothing."""
        if self._last_result is None:
            return None
        z_lo, z_hi = self._drawn_z_range or self._plotted_z_range or (z, z)
        z = min(max(z, z_lo), z_hi)
        segments = self._last_result.segments
        for seg in segments:
            if seg.z_start - 1e-9 <= z <= seg.z_end + 1e-9:
                return seg.beam, seg.label, z
        if z < segments[0].z_start:
            return segments[0].beam, segments[0].label, z
        return segments[-1].beam, segments[-1].label, z

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
            result = OpticalSystem(
                self.project.beam, self.project.optics, ambient_index=self.project.config.ambient_index,
            ).propagate(trailing_length=trailing)
        except ValueError:
            return
        self._last_result = result

        # The physical span first (it frames "reset view" and is what the
        # window range gets compared against), then the wider span actually
        # drawn.
        self._plotted_z_range = self._physical_z_range(result)
        self._drawn_z_range = self._draw_z_range()
        z_all, w_all = self._sample_result(result, *self._drawn_z_range)
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
        self._update_ray_trace(cfg)

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
        probe = OpticalSystem(
            self.project.beam, self.project.optics, ambient_index=cfg.ambient_index,
        ).propagate()
        zr = probe.output_rayleigh_range
        return max(cfg.plot_trailing_padding_zr_multiple * zr, cfg.plot_trailing_padding_min_mm)

    def _physical_z_range(self, result: SystemResult) -> Tuple[float, float]:
        """The span the beam is *physically* described over: the configured
        leading padding before the input plane, out to the end of
        propagate()'s trailing segment."""
        cfg = self.project.config
        lead = min(self.project.beam.z_ref - cfg.plot_leading_padding_mm, result.segments[0].z_start)
        return (float(lead), float(result.segments[-1].z_end))

    def _draw_z_range(self) -> Tuple[float, float]:
        """The span the curves are drawn over: the current window, widened to
        at least the physical span.

        A beam that stops in mid-air partway across the canvas reads as the
        beam ending there, which it doesn't -- every segment's GaussianBeam
        (and every RaySegment's line) is analytic and exact outside the
        window a particular propagate() happened to bound it to, exactly as
        physics.system.segment_covering and RaySegment.opl_at already rely
        on. So the picture is extended to the frame instead of the frame
        being fitted to the picture."""
        lo, hi = self._plotted_z_range or (0.0, 1.0)
        try:
            view_lo, view_hi = self.getViewBox().viewRange()[0]
        except Exception:
            return (lo, hi)
        if not (math.isfinite(view_lo) and math.isfinite(view_hi)) or view_hi <= view_lo:
            return (lo, hi)
        return (min(lo, float(view_lo)), max(hi, float(view_hi)))

    def _on_x_range_changed(self, *_args) -> None:
        """Re-extend the drawn curves after a pan/zoom, without re-running
        the physics: the beam and ray results are unchanged by moving the
        window, only the range they need to cover is."""
        if self.project is None or self._last_result is None:
            return
        new_range = self._draw_z_range()
        if self._drawn_z_range is not None and new_range == self._drawn_z_range:
            return
        self._drawn_z_range = new_range
        z_all, w_all = self._sample_result(self._last_result, *new_range)
        self._beam_upper.setData(z_all, w_all)
        self._beam_lower.setData(z_all, -w_all)
        self._axis_line.setData([z_all[0], z_all[-1]], [0.0, 0.0])
        self._draw_ray_fan(*new_range)

    def _sample_result(self, result: SystemResult, z_lo: float, z_hi: float):
        cfg = self.project.config
        n_pts = max(cfg.beam_curve_points_per_segment, 2)
        zs, ws = [], []

        first_seg = result.segments[0]
        if z_lo < first_seg.z_start:
            z_lead = np.linspace(z_lo, first_seg.z_start, n_pts)
            zs.append(z_lead)
            ws.append(first_seg.beam.w(z_lead))

        for seg in result.segments:
            z_seg = np.linspace(seg.z_start, seg.z_end, n_pts)
            zs.append(z_seg)
            ws.append(seg.beam.w(z_seg))

        last_seg = result.segments[-1]
        if z_hi > last_seg.z_end:
            z_tail = np.linspace(last_seg.z_end, z_hi, n_pts)
            zs.append(z_tail)
            ws.append(last_seg.beam.w(z_tail))
        return np.concatenate(zs), np.concatenate(ws)

    def _find_waists(self, result: SystemResult):
        pts = []
        for seg in result.segments:
            zw = seg.beam.z_waist
            if seg.z_start - 1e-9 <= zw <= seg.z_end + 1e-9:
                pts.append((zw, seg.beam.rayleigh_range))
        return pts

    def _update_ray_trace(self, cfg) -> None:
        """Overlays the real (Snell's-law) ray fan on top of the Gaussian
        beam curve when enabled -- see physics/raytrace.py. Each ray is
        drawn as its own polyline; NaN-separated so pyqtgraph draws them as
        disjoint segments within one PlotCurveItem instead of connecting one
        ray's endpoint to the next ray's start. A surviving ray's trailing
        leg is clipped to the currently plotted z range (its own physics.py
        RaySegment stays exact/unbounded; only the drawing is truncated,
        same relationship the Gaussian curve already has to its own
        underlying beam segments)."""
        if not cfg.raytrace_enabled or self.project is None or self._drawn_z_range is None:
            self._last_ray_fan = None
            self._ray_fan_curve.setData([], [])
            self._ray_stop_markers.setData([], [])
            return

        # Defensive, per README's "Lessons learned": this is a display-only
        # addition sitting inside refresh(), *before* the pinned-target
        # re-emit and the final scene()/viewport() update calls below -- an
        # unguarded failure here (e.g. a transient r1/r2 == 0.0 mid-edit,
        # same bug shape as Round 1/Round 8) would silently abort the rest
        # of refresh() every time it's called from then on, freezing the
        # whole canvas (not just the ray overlay) without the app ever
        # crashing. Never let this block anything after it.
        try:
            fan = trace_fan(
                self.project.beam, self.project.optics,
                ambient_index=cfg.ambient_index, ray_count=cfg.raytrace_ray_count,
            )
        except ValueError:
            self._last_ray_fan = None
            self._ray_fan_curve.setData([], [])
            self._ray_stop_markers.setData([], [])
            return
        self._last_ray_fan = fan
        self._draw_ray_fan(*self._drawn_z_range)

    def _draw_ray_fan(self, z_lo: float, z_hi: float) -> None:
        """Build the ray polylines over [z_lo, z_hi] from the cached fan.

        Both ends are extrapolated to the window: a surviving ray's trailing
        leg out to z_hi, and its incoming leg back to z_lo (the launch
        direction is a straight line before the input plane just as much as
        after it). A vignetted/TIR ray still stops where the physics stops
        it -- that endpoint is real, not a drawing limit."""
        fan = self._last_ray_fan
        if fan is None:
            self._ray_fan_curve.setData([], [])
            self._ray_stop_markers.setData([], [])
            return

        zs: List[float] = []
        rs: List[float] = []
        stop_zs: List[float] = []
        stop_rs: List[float] = []
        for path in fan.paths:
            for i, seg in enumerate(path.segments[:-1]):
                start_z = min(seg.z0, z_lo) if i == 0 else seg.z0
                zs.extend([start_z, seg.z1, float("nan")])
                rs.extend([seg.r_at(start_z), seg.r1, float("nan")])
            last = path.segments[-1]
            start_z = min(last.z0, z_lo) if len(path.segments) == 1 else last.z0
            # A surviving ray's trailing RaySegment runs to a nominal
            # +1e7 mm, so this clips it down to the window rather than
            # extending it -- the window is the shorter of the two either way.
            end_z = min(last.z1, z_hi) if path.status == "ok" else last.z1
            zs.extend([start_z, end_z, float("nan")])
            rs.extend([last.r_at(start_z), last.r_at(end_z) if path.status == "ok" else last.r1, float("nan")])
            if path.status != "ok":
                stop_zs.append(last.z1)
                stop_rs.append(last.r1)

        self._ray_fan_curve.setData(zs, rs, connect="finite")
        self._ray_stop_markers.setData(stop_zs, stop_rs)

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
