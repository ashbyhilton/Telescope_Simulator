"""Light/dark theme switching. pyqtgraph plots don't follow the Qt palette
automatically, so the PlotView's background/axis colors are updated
alongside the QApplication's palette."""
from __future__ import annotations

import pyqtgraph as pg
from pyqtgraph.Qt import QtGui, QtWidgets

_DARK_COLORS = {
    QtGui.QPalette.ColorRole.Window: (53, 53, 53),
    QtGui.QPalette.ColorRole.WindowText: (220, 220, 220),
    QtGui.QPalette.ColorRole.Base: (35, 35, 35),
    QtGui.QPalette.ColorRole.AlternateBase: (53, 53, 53),
    QtGui.QPalette.ColorRole.ToolTipBase: (220, 220, 220),
    QtGui.QPalette.ColorRole.ToolTipText: (220, 220, 220),
    QtGui.QPalette.ColorRole.Text: (220, 220, 220),
    QtGui.QPalette.ColorRole.Button: (53, 53, 53),
    QtGui.QPalette.ColorRole.ButtonText: (220, 220, 220),
    QtGui.QPalette.ColorRole.BrightText: (255, 60, 60),
    QtGui.QPalette.ColorRole.Link: (100, 170, 255),
    QtGui.QPalette.ColorRole.Highlight: (70, 130, 180),
    QtGui.QPalette.ColorRole.HighlightedText: (0, 0, 0),
}


def _dark_palette() -> QtGui.QPalette:
    palette = QtGui.QPalette()
    for role, rgb in _DARK_COLORS.items():
        palette.setColor(role, QtGui.QColor(*rgb))
    palette.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.Text, QtGui.QColor(127, 127, 127))
    palette.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(127, 127, 127))
    return palette


def apply_theme(app: QtWidgets.QApplication, plot_view, dark: bool) -> None:
    app.setStyle("Fusion")
    app.setPalette(_dark_palette() if dark else app.style().standardPalette())

    if dark:
        plot_view.setBackground((30, 30, 30))
        axis_pen = pg.mkPen((200, 200, 200))
    else:
        plot_view.setBackground("w")
        axis_pen = pg.mkPen((0, 0, 0))

    for name in ("bottom", "left"):
        axis = plot_view.getAxis(name)
        axis.setPen(axis_pen)
        axis.setTextPen(axis_pen)
