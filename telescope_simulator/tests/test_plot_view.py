import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.model.project import default_demo_project
from telescope_simulator.gui.plot_view import PlotView


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_drag_moves_item_without_rebuilding_polygon(qapp):
    """A drag only repositions an OpticItem; its shape fields (and hence its
    cached polygon) are untouched, so `_on_item_dragged` must use
    `set_position()` rather than the full `sync_from_optic()` rebuild."""
    project = default_demo_project()
    view = PlotView()
    view.set_project(project)
    optic = project.optics[0]
    item = view._optic_items[optic.id]
    bounds_before = item._bounds

    view._on_item_dragged(item, 250.0, 3.0)

    assert optic.z == 250.0
    assert optic.x == 3.0
    assert item.pos().x() == 250.0
    assert item.pos().y() == 3.0
    assert item._bounds == bounds_before


def test_property_edit_after_drag_still_rebuilds_polygon(qapp):
    """A real shape edit (e.g. thickness) after a drag must still fully
    resync the polygon -- the drag-time shortcut must not leave the item
    permanently skipping geometry rebuilds."""
    project = default_demo_project()
    view = PlotView()
    view.set_project(project)
    optic = project.optics[0]
    item = view._optic_items[optic.id]

    view._on_item_dragged(item, 250.0, 3.0)
    bounds_after_drag = item._bounds

    optic.thickness_center = 20.0
    view.refresh_optic(optic.id)

    assert item._bounds != bounds_after_drag
    assert item._bounds.width() == pytest.approx(20.0, abs=0.5)


def test_pinned_target_recomputes_after_drag(qapp):
    """A pinned 'beam at target location' must not go stale when the optic
    that governs that segment is moved -- it should re-derive against the
    latest SystemResult on every refresh(), not just at pin time."""
    project = default_demo_project()
    view = PlotView()
    view.set_project(project)
    optic = project.optics[0]
    item = view._optic_items[optic.id]

    seen = []
    view.targetChanged.connect(lambda info: seen.append(info))

    # z=500 sits in the "output" segment (past the lens at z=100), whose
    # beam parameters depend on the lens position -- unlike a point in the
    # air gap *before* the lens, which wouldn't change when the lens moves.
    found = view.beam_at(500.0)
    assert found is not None
    beam, label, z = found
    view._pin_at(z, beam, label)
    assert seen and seen[-1].pinned
    stale_q = seen[-1].beam.q_at(z)

    view._on_item_dragged(item, optic.z + 30.0, 0.0)

    assert seen[-1].pinned
    assert seen[-1].beam.q_at(z) != stale_q


def test_x_offset_shifts_beam_curve(qapp):
    """InputBeamSpec.x_offset was stored/serialized but never consumed
    anywhere -- it must shift the plotted beam envelope's transverse
    center."""
    project = default_demo_project()
    view = PlotView()
    view.set_project(project)
    _, w_before = view._beam_upper.getData()

    project.beam.x_offset = 5.0
    view.refresh()
    z_after, w_after = view._beam_upper.getData()

    assert w_after == pytest.approx(w_before + 5.0)
