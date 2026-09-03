import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.model.optics import Optic
from telescope_simulator.model.project import default_demo_project
from telescope_simulator.gui.plot_view import PlotView


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_drag_moves_item_without_rebuilding_polygon(qapp):
    """A drag only repositions an OpticItem; its shape fields (and hence its
    cached polygon) are untouched, so `_on_item_dragged` must use
    `set_position()` rather than the full `sync_from_optic()` rebuild. The
    model is strictly axis-aligned, so a drag only ever moves z."""
    project = default_demo_project()
    view = PlotView()
    view.set_project(project)
    optic = project.optics[0]
    item = view._optic_items[optic.id]
    bounds_before = item._bounds

    view._on_item_dragged(item, 250.0)

    assert optic.z == 250.0
    assert item.pos().x() == 250.0
    assert item.pos().y() == 0.0
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

    view._on_item_dragged(item, 250.0)
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

    view._on_item_dragged(item, optic.z + 30.0)

    assert seen[-1].pinned
    assert seen[-1].beam.q_at(z) != stale_q


def test_group_drag_moves_every_member_by_the_same_delta(qapp):
    """A composite-lens group is a rigid unit: dragging any one member must
    shift every sibling sharing the same group_id by the same z delta, so
    the group's internal spacing never changes from a drag."""
    project = default_demo_project()
    lead = project.optics[0]
    lead.group_id = lead.id
    lead.group_name = "Doublet"
    follower = Optic(
        name="Doublet element 2", diameter_full=lead.diameter_full, thickness_center=3.0,
        z=lead.z + lead.thickness_center + 2.0, group_id=lead.group_id, group_name="Doublet",
    )
    project.optics.append(follower)

    view = PlotView()
    view.set_project(project)
    lead_item = view._optic_items[lead.id]
    lead_z_before = lead.z
    follower_z_before = follower.z
    separation_before = follower_z_before - lead_z_before

    view._on_item_dragged(lead_item, lead_z_before + 40.0)

    assert lead.z == pytest.approx(lead_z_before + 40.0)
    assert follower.z == pytest.approx(follower_z_before + 40.0)
    assert follower.z - lead.z == pytest.approx(separation_before)
    assert view._optic_items[follower.id].pos().x() == pytest.approx(follower.z)
