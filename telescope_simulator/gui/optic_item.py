"""Interactive canvas representation of a single Optic: draws its true
spherical-sag silhouette and handles click/drag using pyqtgraph's
scene-level mouse event convention (mouseClickEvent/mouseDragEvent), the
same mechanism pg.ROI and pg.InfiniteLine use so that dragging an item
takes priority over the ViewBox's own pan gesture.
"""
from __future__ import annotations

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from ..model.optics import Optic
from .lens_geometry import build_lens_polygon


class OpticItem(pg.GraphicsObject):
    sigClicked = QtCore.Signal(object)
    sigDragged = QtCore.Signal(object, float)
    sigDragFinished = QtCore.Signal(object)
    sigHoverEnter = QtCore.Signal(object)
    sigHoverLeave = QtCore.Signal(object)

    GLASS_BRUSH = QtGui.QBrush(QtGui.QColor(140, 190, 230, 120))
    GLASS_PEN = QtGui.QPen(QtGui.QColor(60, 110, 150))
    SELECTED_PEN = QtGui.QPen(QtGui.QColor(255, 140, 0))

    def __init__(self, optic: Optic):
        super().__init__()
        self.optic = optic
        self.selected = False
        self._polygon = QtGui.QPolygonF()
        self._bounds = QtCore.QRectF()
        self._press_optic_z = None
        self._press_data_pos = None
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
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
        current shape fields, then repositions it. Call this after any edit
        that could change shape (diameter/thickness/r1/r2), not on every
        drag mouse-move — see `set_position()`. The model is strictly
        axis-aligned (no transverse offset/tilt), so position is z-only."""
        self.prepareGeometryChange()
        self._build_polygon()
        self.setPos(self.optic.z, 0.0)
        self.update()

    def set_position(self, z: float) -> None:
        """Position-only update for drag moves: the optic's shape fields
        aren't touched by dragging, so this skips `prepareGeometryChange()`
        and the polygon rebuild `sync_from_optic()` does on every call --
        Qt's own item-move handling already invalidates the old/new scene
        regions for a plain `setPos()`, without needing to also declare a
        (here, unchanged) geometry change on every mouse-move."""
        self.setPos(z, 0.0)

    def _build_polygon(self) -> None:
        self._polygon = build_lens_polygon(self.optic)
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
            self._press_optic_z = self.optic.z
            self._press_data_pos = view.mapSceneToView(ev.buttonDownScenePos())
            self.sigClicked.emit(self)

        data_pos = view.mapSceneToView(ev.scenePos())
        dz = data_pos.x() - self._press_data_pos.x()
        new_z = self._press_optic_z if self.optic.lock_z else self._press_optic_z + dz
        self.sigDragged.emit(self, new_z)

        if ev.isFinish():
            self.sigDragFinished.emit(self)

    def hoverEnterEvent(self, ev) -> None:
        self.sigHoverEnter.emit(self)

    def hoverMoveEvent(self, ev) -> None:
        self.sigHoverEnter.emit(self)

    def hoverLeaveEvent(self, ev) -> None:
        self.sigHoverLeave.emit(self)
