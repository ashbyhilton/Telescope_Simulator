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


def _finite_span(xs):
    finite = [x for x in xs if x == x and abs(x) != float("inf")]
    return min(finite), max(finite)


def test_beam_is_drawn_to_the_window_edges_not_to_its_own_padding(qapp):
    """A beam curve that stops in mid-canvas reads as the beam ending there,
    which it doesn't -- each segment's GaussianBeam is analytic well outside
    the range a particular propagate() bounded it to. The drawn span follows
    the window, in both directions."""
    project = default_demo_project()
    view = PlotView()
    view.set_project(project)

    view.setXRange(-900.0, 1800.0, padding=0)

    z = view._beam_upper.getData()[0]
    assert z.min() == pytest.approx(-900.0, abs=1.0)
    assert z.max() == pytest.approx(1800.0, abs=1.0)
    # The axis line has to keep up too, or it stops short of its own beam.
    axis_z = view._axis_line.getData()[0]
    assert axis_z[0] == pytest.approx(-900.0, abs=1.0)
    assert axis_z[-1] == pytest.approx(1800.0, abs=1.0)


def test_rays_are_drawn_to_the_window_edges_in_both_directions(qapp):
    project = default_demo_project()
    project.config.raytrace_enabled = True
    view = PlotView()
    view.set_project(project)

    view.setXRange(-700.0, 1400.0, padding=0)

    ray_z, _ = view._ray_fan_curve.getData()
    lo, hi = _finite_span(ray_z)
    assert lo == pytest.approx(-700.0, abs=1.0)  # extrapolated back before the launch plane
    assert hi == pytest.approx(1400.0, abs=1.0)


def test_extending_the_view_does_not_move_the_reset_view_range(qapp):
    """The drawn span follows the window, but "reset view" must keep framing
    the *physical* extent -- otherwise each pan would widen the range that
    reset restores, and the view would creep outward every time."""
    project = default_demo_project()
    view = PlotView()
    view.set_project(project)
    physical_before = view._plotted_z_range

    view.setXRange(-5000.0, 9000.0, padding=0)

    assert view._plotted_z_range == physical_before


def test_a_vignetted_ray_still_stops_where_the_physics_stops_it(qapp):
    """Extending rays to the window must not extend the ones that were
    blocked -- a vignetting stop point is a real physical endpoint, not a
    drawing limit."""
    project = default_demo_project()
    project.config.raytrace_enabled = True
    # A stop *downstream* of the first optic. Shrinking the first one instead
    # would vignette nothing: trace_fan sizes the fan to the first optic's
    # clear aperture, so the fan would simply shrink with it.
    last = max(project.optics, key=lambda o: o.z)
    project.optics.append(Optic(
        name="Stop", diameter_full=0.2, thickness_center=1.0,
        r1=float("inf"), r2=float("inf"), n=1.5,
        z=last.z + last.thickness_center + 20.0,
    ))
    view = PlotView()
    view.set_project(project)
    view.setXRange(-500.0, 1200.0, padding=0)

    stop_z, _ = view._ray_stop_markers.getData()
    assert len(stop_z) > 0
    assert max(stop_z) < 1200.0


def test_target_can_be_pinned_out_in_the_extended_part_of_the_canvas(qapp):
    # The beam is drawn out there, so a click out there has to answer with a
    # beam rather than silently doing nothing.
    project = default_demo_project()
    view = PlotView()
    view.set_project(project)
    view.setXRange(-100.0, 2500.0, padding=0)

    found = view.beam_at(2000.0)

    assert found is not None
    beam, _label, z = found
    assert z == pytest.approx(2000.0)
    assert beam.w(z) > 0.0


def test_clicking_again_retargets_without_unpinning_first(qapp):
    """Retargeting used to be a two-click job: _on_scene_mouse_clicked bailed
    out whenever a target was already pinned, so the old marker had to be
    cleared before a new one could be placed."""
    project = default_demo_project()
    view = PlotView()
    view.set_project(project)
    emitted = []
    view.targetChanged.connect(emitted.append)
    view.setXRange(-100.0, 600.0, padding=0)  # so both targets are on drawn beam

    beam, label, z1 = view.beam_at(200.0)
    view._pin_at(z1, beam, label)
    beam, label, z2 = view.beam_at(260.0)
    view._pin_at(z2, beam, label)

    assert view._pinned is True
    assert view._pinned_z == pytest.approx(z2)
    assert emitted[-1].pinned is True
    assert emitted[-1].z == pytest.approx(z2)
    assert z2 != pytest.approx(z1)
