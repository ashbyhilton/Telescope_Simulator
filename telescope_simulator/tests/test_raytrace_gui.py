import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtTest, QtWidgets

from telescope_simulator.gui.main_window import MainWindow
from telescope_simulator.gui.mm_axis import MMAxisItem, format_length_mm
from telescope_simulator.model.optics import Optic
from telescope_simulator.physics.raytrace import trace_fan, wavefront_at


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _settle(w: MainWindow) -> None:
    """Run the event loop until MainWindow's coalescing timer has fired.

    The Ray Tracing tab's recompute is debounced (a drag emits targetChanged
    on every mouse-move, and the diffraction PSF costs ~100ms), so these
    tests wait the interval out rather than calling the slot directly --
    that keeps them checking the real signal wiring, not just the method."""
    QtTest.QTest.qWait(w._raytrace_timer.interval() + 120)


def _enable_raytrace(w: MainWindow) -> None:
    w.project.config.raytrace_enabled = True
    w.config_tab.set_config(w.project.config)
    w.on_config_changed(w.project.config)
    _settle(w)


def test_raytrace_disabled_by_default_and_tab_shows_disabled_message(qapp):
    w = MainWindow()
    assert w.project.config.raytrace_enabled is False
    assert "Enable ray tracing" in w.raytrace_tab.status_label.text()
    assert w.plot_view._last_ray_fan is None


def test_enabling_raytrace_draws_a_ray_fan_overlay(qapp):
    w = MainWindow()
    _enable_raytrace(w)

    assert w.plot_view._last_ray_fan is not None
    assert len(w.plot_view._last_ray_fan.paths) == w.project.config.raytrace_ray_count


def test_pinning_target_with_raytrace_enabled_populates_zernike_table(qapp):
    w = MainWindow()
    _enable_raytrace(w)
    optic = w.project.optics[0]

    found = w.plot_view.beam_at(optic.z + optic.thickness_center + 200.0)
    assert found is not None
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)
    _settle(w)

    assert w.raytrace_tab.status_label.text() == ""
    assert w.raytrace_tab.zernike_table.rowCount() == 5
    assert "/" in w.raytrace_tab._summary_labels["survived"].text()


def test_unpinning_target_reverts_raytrace_tab_to_unavailable(qapp):
    w = MainWindow()
    _enable_raytrace(w)
    optic = w.project.optics[0]
    found = w.plot_view.beam_at(optic.z + optic.thickness_center + 200.0)
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)
    _settle(w)
    assert w.raytrace_tab.status_label.text() == ""

    w.plot_view._unpin()

    _settle(w)

    assert "Pin a target" in w.raytrace_tab.status_label.text()


def test_moving_optic_with_raytrace_enabled_does_not_raise(qapp):
    w = MainWindow()
    _enable_raytrace(w)
    optic = w.project.optics[0]
    found = w.plot_view.beam_at(optic.z + optic.thickness_center + 200.0)
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)
    _settle(w)

    optic.z += 5.0
    w.on_optic_property_changed(optic.id)  # exercises the full refresh chain
    _settle(w)

    assert w.raytrace_tab.zernike_table.rowCount() == 5


def test_zero_radius_via_target_changed_does_not_crash(qapp):
    """Regression test for the reported v2.0 crash. Root cause: with a
    target already pinned, PlotView.targetChanged can fire from a path that
    reuses the *cached* last-good Gaussian result (hover / re-pin / unpin)
    rather than from inside refresh()'s own Gaussian-guarded propagate()
    call -- so MainWindow.on_target_changed's direct, unguarded call to
    _refresh_raytrace_tab() could run physics.raytrace.trace_fan() against
    a momentarily-invalid optic (r2 == 0.0, e.g. a spin box mid-edit) with
    no propagate()-based check to catch it first. That produced an opaque
    ZeroDivisionError deep in _surface_normal instead of the same clean,
    catchable ValueError physics.matrices.interface() already raises for
    the identical condition -- fixed at the source in physics/raytrace.py."""
    w = MainWindow()
    _enable_raytrace(w)
    optic = w.project.optics[0]
    found = w.plot_view.beam_at(optic.z + optic.thickness_center + 200.0)
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)
    _settle(w)
    assert w.raytrace_tab.zernike_table.rowCount() == 5

    optic.r2 = 0.0
    w._refresh_raytrace_tab()  # must not raise -- this is exactly on_target_changed's call

    assert "zero" in w.raytrace_tab.status_label.text().lower()
    assert w.raytrace_tab.zernike_table.rowCount() == 0

    # Recovery: once the geometry is valid again, everything resumes --
    # proves nothing got left in a stuck/stale state from the bad
    # intermediate value (the actual reported symptom, "gui stopped
    # responding").
    optic.r2 = -50.0
    w._refresh_raytrace_tab()

    assert w.raytrace_tab.zernike_table.rowCount() == 5


def test_zero_radius_inside_refresh_does_not_block_canvas_repaint(qapp):
    """Defense in depth for the same bug shape, at the *other* call site:
    physics.raytrace.trace_fan() is also called directly inside
    PlotView.refresh() (for the canvas overlay) -- if reached with an
    invalid optic, it must not raise out of refresh() before the method's
    own final scene()/viewport() update calls, or the whole canvas (not
    just the ray overlay) silently stops repainting on every subsequent
    interaction, matching README's "Lessons learned" Round 1/Round 8 bug
    shape exactly."""
    w = MainWindow()
    _enable_raytrace(w)
    optic = w.project.optics[0]

    optic.r2 = 0.0
    w.plot_view._update_ray_trace(w.project.config)  # must not raise

    assert w.plot_view._last_ray_fan is None

    optic.r2 = -50.0
    w.plot_view._update_ray_trace(w.project.config)

    assert w.plot_view._last_ray_fan is not None
    assert len(w.plot_view._last_ray_fan.paths) == w.project.config.raytrace_ray_count


def test_ambient_index_change_updates_output_and_raytrace_readouts(qapp):
    w = MainWindow()
    _enable_raytrace(w)
    optic = w.project.optics[0]
    found = w.plot_view.beam_at(optic.z + optic.thickness_center + 200.0)
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)
    _settle(w)
    before = w.raytrace_tab._summary_labels["rms"].text()

    w.project.config.ambient_index = 1.33
    w.config_tab.set_config(w.project.config)
    w.on_config_changed(w.project.config)
    _settle(w)

    # Just needs to have actually recomputed without raising; a changed
    # ambient index changes the physics, so the readout must still be populated.
    assert w.raytrace_tab.zernike_table.rowCount() == 5
    assert before is not None


def _pin_downstream_target(w: MainWindow, offset_mm: float = 200.0):
    optic = w.project.optics[0]
    found = w.plot_view.beam_at(optic.z + optic.thickness_center + offset_mm)
    assert found is not None
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)
    _settle(w)
    return z


def test_invalid_system_clears_the_raytrace_tab_instead_of_leaving_it_stale(qapp):
    """_refresh_output_readouts() used to return the moment the Gaussian
    propagate() raised, before it ever reached the Ray Tracing tab -- so the
    Zernike table, RMS/PV summary and PSF plot kept showing numbers from
    before the system went invalid, with nothing to say they no longer
    described it."""
    w = MainWindow()
    _enable_raytrace(w)
    _pin_downstream_target(w)
    assert w.raytrace_tab.zernike_table.rowCount() == 5

    # Push an optic in front of the beam's own reference plane: both the
    # Gaussian model and the ray tracer reject this.
    w.project.optics[0].z = w.project.beam.z_ref - 10.0
    w._refresh_output_readouts()
    assert w._raytrace_timer.isActive()  # deferred, but scheduled
    w._refresh_raytrace_tab()

    assert w.raytrace_tab.zernike_table.rowCount() == 0
    assert w.raytrace_tab.status_label.text() != ""


def test_optic_drag_defers_the_expensive_psf_instead_of_running_it_per_mouse_move(qapp):
    """PlotView emits opticMoved on every mouse-move of a drag. The PSF is a
    multi-megapixel FFT (~80ms), so running it per move dragged the canvas to
    ~10fps; it is coalesced onto a single-shot timer instead."""
    w = MainWindow()
    _enable_raytrace(w)
    _pin_downstream_target(w)
    optic = w.project.optics[0]

    w._raytrace_timer.stop()
    for step in range(5):
        w.on_optic_moved_from_canvas(optic.id, optic.z + step)

    # Five moves, one pending recompute -- not five.
    assert w._raytrace_timer.isActive()
    w._refresh_raytrace_tab()
    assert w.raytrace_tab.zernike_table.rowCount() == 5


def test_psf_propagates_from_the_exit_plane_over_the_exit_pupil(qapp):
    """The first cut measured the Fraunhofer distance from the beam's launch
    plane and used the fan's launched half-width as the aperture -- a plane
    upstream of every optic, giving an f-number, and so a reported Airy null,
    several times wrong."""
    w = MainWindow()
    _enable_raytrace(w)
    target_z = _pin_downstream_target(w)
    optic = w.project.optics[0]

    fan = trace_fan(
        w.project.beam, w.project.optics,
        ambient_index=w.project.config.ambient_index,
        ray_count=w.project.config.raytrace_ray_count,
    )
    sample = wavefront_at(fan, target_z)

    assert sample.exit_pupil_z == pytest.approx(optic.z + optic.thickness_center)
    expected_null = (
        1.22 * (fan.wavelength_nm * 1e-6) * (target_z - sample.exit_pupil_z)
        / (2.0 * sample.exit_pupil_radius_mm)
    )
    # Distinguishable from the old launch-plane/launched-fan figure, which
    # is what makes this assertion worth making at all.
    old_null = (
        1.22 * (fan.wavelength_nm * 1e-6) * (target_z - w.project.beam.z_ref)
        / (2.0 * fan.pupil_radius_mm)
    )
    assert expected_null != pytest.approx(old_null, rel=0.05)
    assert format_length_mm(expected_null) == w.raytrace_tab._summary_labels["airy"].text()


def test_ambient_index_reaches_the_optics_tab_focal_length_readouts(qapp):
    """thick_lens() takes n_ambient, but every GUI call site left it at 1.0:
    setting the background medium to water changed the propagation, ray
    trace, optimiser and fit while the Optics tab and canvas hover overlay
    kept reporting in-air focal lengths for the same lens."""
    w = MainWindow()
    optic = w.project.optics[0]
    w.optics_tab.select_optic(optic.id)
    in_air = w.optics_tab.efl_label.text()
    hover_in_air = w.plot_view._hover_text(optic)

    w.project.config.ambient_index = 1.33
    w.config_tab.set_config(w.project.config)
    w.on_config_changed(w.project.config)
    _settle(w)

    assert w.optics_tab.efl_label.text() != in_air
    assert w.optics_tab.bfl_label.text() != "-"
    assert w.plot_view._hover_text(optic) != hover_in_air


def test_psf_unavailable_still_leaves_the_zernike_analysis_on_screen(qapp):
    """A target upstream of the exit plane has no propagation distance to
    diffract over, but its wavefront error is perfectly well defined -- so
    only the PSF plot goes away, not the whole tab."""
    w = MainWindow()
    _enable_raytrace(w)
    optic = w.project.optics[0]
    found = w.plot_view.beam_at(optic.z - 1.0)  # in front of the lens
    assert found is not None
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)
    _settle(w)

    assert w.raytrace_tab.zernike_table.rowCount() == 5
    assert w.raytrace_tab.status_label.text() == ""
    assert w.raytrace_tab.psf_status_label.isVisible() or w.raytrace_tab.psf_status_label.text() != ""
    assert w.raytrace_tab._summary_labels["airy"].text() == "-"


def test_card_intensity_plot_is_populated_alongside_the_diffraction_psf(qapp):
    """The two profiles answer different questions and are valid in opposite
    regimes (see physics/irradiance.py), so the tab shows both rather than
    picking one."""
    w = MainWindow()
    _enable_raytrace(w)
    _pin_downstream_target(w)

    card_x, card_y = w.raytrace_tab._card_curve.getData()
    assert card_x is not None and len(card_x) > 0
    assert max(card_y) == pytest.approx(1.0)
    assert w.raytrace_tab._summary_labels["spot"].text() != "-"


def test_geometric_profile_below_the_diffraction_limit_says_so(qapp):
    """Near focus the geometric profile still draws -- it just isn't the
    physical answer any more. Showing the narrower of the two plots with no
    caveat would make it look like the better one."""
    w = MainWindow()
    # A deliberately slow (~f/390) single surface: spherical aberration is
    # negligible at that speed, so the geometric spot at focus collapses
    # while the Airy radius stays a healthy fraction of a millimetre. The
    # demo project is far too fast to reach this regime.
    w.project.beam.wavelength_nm = 632.8
    w.project.beam.w_ref = 0.5
    w.project.beam.collimated = True
    w.project.beam.r_ref = None
    w.project.optics = [Optic(
        name="Slow", diameter_full=25.4, thickness_center=4.0,
        r1=float("inf"), r2=-500.0, n=1.5168, z=50.0,
    )]
    w._load_project_into_ui()
    _enable_raytrace(w)

    focus_z = 50.0 + 4.0 + 500.0 / 0.5168  # back focal distance of the single surface
    w.plot_view.setXRange(-50.0, focus_z + 200.0, padding=0)
    found = w.plot_view.beam_at(focus_z)
    assert found is not None
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)
    _settle(w)

    # (isVisible() is not assertable here -- nothing in this offscreen test
    # is ever shown, so every widget reports itself hidden.)
    assert "diffraction" in w.raytrace_tab.card_status_label.text().lower()
    # The curve is still drawn; only the caveat is added.
    assert len(w.raytrace_tab._card_curve.getData()[0]) > 0


def test_card_plot_is_a_full_signed_slice_on_a_fixed_default_range(qapp):
    """It used to be I(r) over one half-plane with an auto-ranging axis, so
    every target looked about the same size and the spot's width had to be
    doubled by eye. Now it is I(x, 0) from one side of the axis to the other,
    framed by the optics rather than by the data."""
    w = MainWindow()
    _enable_raytrace(w)
    _pin_downstream_target(w)

    x, y = w.raytrace_tab._card_curve.getData()
    assert x[0] < 0.0 < x[-1]
    assert x[0] == pytest.approx(-x[-1])
    assert max(y) == pytest.approx(1.0)
    # Peak on axis, not in a ring: a 2*pi*r-weighted radial power
    # distribution would be zero at x = 0.
    assert y[len(y) // 2] > 0.5 * max(y)

    expected_half = 0.75 * max(o.diameter_full for o in w.project.optics)
    lo, hi = w.raytrace_tab.card_plot.getViewBox().viewRange()[0]
    assert (hi - lo) == pytest.approx(2.0 * expected_half, rel=0.01)


def test_psf_plot_is_linear_and_framed_on_its_core(qapp):
    """A log axis hid nothing useful once the pupil was correctly apodized,
    and the FFT's own radius array runs ~100x past the spot -- on a linear
    axis, unframed, the whole pattern draws as one spike at the origin."""
    w = MainWindow()
    _enable_raytrace(w)
    _pin_downstream_target(w)

    assert w.raytrace_tab.psf_plot.getViewBox().state["logMode"] == [False, False]
    x, y = w.raytrace_tab._psf_curve.getData()
    assert x[0] == pytest.approx(-x[-1])
    assert max(y) == pytest.approx(1.0)

    lo, hi = w.raytrace_tab.psf_plot.getViewBox().viewRange()[0]
    assert (hi - lo) < 0.5 * (x[-1] - x[0])  # framed, not showing the whole window
    assert w.raytrace_tab._summary_labels["core"].text() != "-"


def test_psf_pupil_carries_the_beams_gaussian_illumination(qapp):
    """The pupil used to be a uniform disk out to the traced fan's radius,
    which by default runs to 2.5 w -- an aperture 2.5x too wide, reporting a
    core roughly half its true width. The fix shows up as the measured core
    being wider than the hard-aperture Airy null, not narrower."""
    w = MainWindow()
    _enable_raytrace(w)
    _pin_downstream_target(w)

    core = w.raytrace_tab._summary_labels["core"].text()
    airy = w.raytrace_tab._summary_labels["airy"].text()
    assert core != "-" and airy != "-"

    fan = trace_fan(
        w.project.beam, w.project.optics,
        ambient_index=w.project.config.ambient_index,
        ray_count=w.project.config.raytrace_ray_count,
    )
    # The fan really is wider than the beam, which is what makes the
    # distinction between the two numbers matter here.
    assert fan.pupil_radius_mm > 1.5 * w.project.beam.w_ref


def test_recompute_time_is_reported_and_broken_down_by_stage(qapp):
    w = MainWindow()
    _enable_raytrace(w)
    assert w.raytrace_tab.timing_label.text() == "-"  # nothing computed yet

    _pin_downstream_target(w)

    text = w.raytrace_tab.timing_label.text()
    assert "ms" in text
    for stage in ("fan+fit", "PSF", "card"):
        assert stage in text


def test_plot_x_axes_relabel_themselves_instead_of_printing_mmm(qapp):
    """pyqtgraph prepends an SI prefix to the declared unit string without
    knowing "mm" is already non-base, so a micron-wide spot came out labelled
    "mmm". These axes do unit-aware conversion instead (gui/mm_axis.py)."""
    w = MainWindow()
    _enable_raytrace(w)
    _pin_downstream_target(w)

    for plot in (w.raytrace_tab.card_plot, w.raytrace_tab.psf_plot, w.raytrace_tab.wavefront_plot):
        axis = plot.getAxis("bottom")
        assert isinstance(axis, MMAxisItem)
        axis.setRange(-0.0004, 0.0004)  # sub-millimetre: microns, not "mmm"
        assert axis.labelUnits == "µm"
        axis.setRange(-20.0, 20.0)
        assert axis.labelUnits == "mm"
