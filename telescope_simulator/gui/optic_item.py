"""Interactive canvas representation of a single Optic: draws its true
spherical-sag silhouette and handles click/drag using pyqtgraph's
scene-level mouse event convention (mouseClickEvent/mouseDragEvent), the
same mechanism pg.ROI and pg.InfiniteLine use so that dragging an item
takes priority over the ViewBox's own pan gesture.
"""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from ..model.optics import Optic


def _surface_z(x: np.ndarray, radius: float, offset: float) -> np.ndarray:
    """Sag of a spherical surface with vertex at local z=`offset`. Radius
    sign convention: positive if the center of curvature is on the +z side
    of the vertex (see physics/matrices.py)."""
    if math.isinf(radius):
        return np.full_like(x, offset)
    r_eff = abs(radius)
    x_clamped = np.clip(x, -0.999 * r_eff, 0.999 * r_eff)
    return offset + radius - math.copysign(1.0, radius) * np.sqrt(r_eff * r_eff - x_clamped * x_clamped)


class OpticItem(pg.GraphicsObject):
    sigClicked = QtCore.Signal(object)
    sigDragged = QtCore.Signal(object, float, float)
    sigDragFinished = QtCore.Signal(object)

    GLASS_BRUSH = QtGui.QBrush(QtGui.QColor(140, 190, 230, 120))
    GLASS_PEN = QtGui.QPen(QtGui.QColor(60, 110, 150))
    SELECTED_PEN = QtGui.QPen(QtGui.QColor(255, 140, 0))

    def __init__(self, optic: Optic):
        super().__init__()
        self.optic = optic
        self.selected = False
        self._polygon = QtGui.QPolygonF()
        self._bounds = QtCore.QRectF()
        self._press_optic_zx = None
        self._press_data_pos = None
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        # Explicit, not relying on Qt's default: rules out any pixmap-cache
        # layer (device- or item-coordinate) as a source of stale-looking
        # geometry after rapid drag/property updates.
        self.setCacheMode(QtWidgets.QGraphicsItem.CacheMode.NoCache)
        self.GLASS_PEN.setWidth(0)
        # setWidth(1) here would be a *non-cosmetic* 1mm-wide pen -- it scales
        # with the canvas's zoom transform, unlike GLASS_PEN's width-0 (Qt's
        # cosmetic-hairline special case), so the selected outline rendered
        # many pixels wide at typical zoom. setCosmetic keeps it a crisp,
        # fixed on-screen width regardless of zoom, matching GLASS_PEN.
        self.SELECTED_PEN.setWidthF(1.5)
        self.SELECTED_PEN.setCosmetic(True)
        self.sync_from_optic()

    def sync_from_optic(self) -> None:
        """Full resync: rebuilds the surface polygon from the optic's
        current shape fields, then repositions/rotates it. Call this after
        any edit that could change shape (diameter/thickness/r1/r2), not on
        every drag mouse-move — see `set_position()`."""
        self.prepareGeometryChange()
        self._build_polygon()
        self.setPos(self.optic.z, self.optic.x)
        self.setRotation(self.optic.angle_deg)
        self.update()

    def set_position(self, z: float, x: float) -> None:
        """Position-only update for drag moves: the optic's shape fields
        aren't touched by dragging, so this skips `prepareGeometryChange()`
        and the polygon rebuild `sync_from_optic()` does on every call --
        Qt's own item-move handling already invalidates the old/new scene
        regions for a plain `setPos()`, without needing to also declare a
        (here, unchanged) geometry change on every mouse-move."""
        self.setPos(z, x)

    def _build_polygon(self, n_samples: int = 48) -> None:
        optic = self.optic
        half_d = max(optic.diameter_full, 1e-6) / 2.0
        xs = np.linspace(-half_d, half_d, n_samples)
        front = _surface_z(xs, optic.r1, 0.0)
        back = _surface_z(xs, optic.r2, optic.thickness_center)

        pts = [QtCore.QPointF(float(z), float(x)) for z, x in zip(front, xs)]
        pts += [QtCore.QPointF(float(z), float(x)) for z, x in zip(back[::-1], xs[::-1])]
        self._polygon = QtGui.QPolygonF(pts)
        self._bounds = self._polygon.boundingRect()

    def boundingRect(self) -> QtCore.QRectF:
        return self._bounds

    def shape(self) -> QtGui.QPainterPath:
        path = QtGui.QPainterPath()
        path.addPolygon(self._polygon)
        return path

    def paint(self, painter: QtGui.QPainter, option, widget=None) -> None:
        painter.setBrush(self.GLASS_BRUSH)
        painter.setPen(self.SELECTED_PEN if self.selected else self.GLASS_PEN)
        painter.drawPolygon(self._polygon)

    def set_selected(self, selected: bool) -> None:
        if self.selected != selected:
            self.selected = selected
            self.update()

    def mouseClickEvent(self, ev) -> None:
        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            ev.accept()
            self.sigClicked.emit(self)

    def mouseDragEvent(self, ev) -> None:
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        view = self.getViewBox()
        if view is None:
            return
        if ev.isStart():
            self._press_optic_zx = (self.optic.z, self.optic.x)
            self._press_data_pos = view.mapSceneToView(ev.buttonDownScenePos())
            self.sigClicked.emit(self)

        data_pos = view.mapSceneToView(ev.scenePos())
        dz = data_pos.x() - self._press_data_pos.x()
        dx = data_pos.y() - self._press_data_pos.y()
        z0, x0 = self._press_optic_zx
        new_z = z0 if self.optic.lock_z else z0 + dz
        new_x = x0 if self.optic.lock_x else x0 + dx
        self.sigDragged.emit(self, new_z, new_x)

        if ev.isFinish():
            self.sigDragFinished.emit(self)
