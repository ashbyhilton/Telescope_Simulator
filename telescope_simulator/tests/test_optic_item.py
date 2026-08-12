import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.gui.optic_item import OpticItem
from telescope_simulator.model.optics import OpticKind, make_default_optic


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_selected_pen_is_cosmetic(qapp):
    """A non-cosmetic pen scales with the canvas's zoom transform and
    rendered as a bulky outline at typical zoom levels; the selection
    outline must stay a fixed on-screen width like the unselected pen."""
    optic = make_default_optic(OpticKind.BICONVEX, "Lens")
    item = OpticItem(optic)

    assert item.GLASS_PEN.width() == 0
    assert item.SELECTED_PEN.isCosmetic()
