import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.gui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_explicit_view_range_applies_without_reset_view_click(qapp):
    """Changing the View box's z/x range fields must snap the canvas to the
    new range immediately -- previously this only took effect after
    clicking "Reset View"."""
    w = MainWindow()
    w.config_tab.lock_aspect_check.setChecked(False)
    w.config_tab.auto_x_check.setChecked(False)
    w.config_tab.x_min_spin.setValue(-10.0)
    w.config_tab.x_max_spin.setValue(10.0)
    w.config_tab.auto_z_check.setChecked(False)
    w.config_tab.z_min_spin.setValue(-500.0)
    w.config_tab.z_max_spin.setValue(2500.0)

    (z_lo, z_hi), (x_lo, x_hi) = w.plot_view.getViewBox().viewRange()
    assert z_lo == pytest.approx(-500.0, abs=1.0)
    assert z_hi == pytest.approx(2500.0, abs=1.0)
    assert x_lo == pytest.approx(-10.0, abs=1.0)
    assert x_hi == pytest.approx(10.0, abs=1.0)


def test_trailing_padding_change_applies_without_reset_view_click(qapp):
    """Changing 'plot padding past output' must extend the visible z range
    immediately when in auto z-range mode."""
    w = MainWindow()
    w.config_tab.lock_aspect_check.setChecked(False)
    (_, z_hi_before), _ = w.plot_view.getViewBox().viewRange()

    w.config_tab.trailing_min_spin.setValue(5000.0)

    (_, z_hi_after), _ = w.plot_view.getViewBox().viewRange()
    assert z_hi_after > z_hi_before + 1000.0


def _pin_past_demo_lens(w, offset: float = 200.0):
    optic = w.project.optics[0]
    found = w.plot_view.beam_at(optic.z + optic.thickness_center + offset)
    assert found is not None
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)
    return z


def test_optimize_buttons_start_disabled(qapp):
    w = MainWindow()
    assert not w.beam_tab.optimize_flatness_btn.isEnabled()
    assert not w.beam_tab.optimize_focus_btn.isEnabled()
    assert w.beam_tab.optimize_flatness_btn.toolTip()


def test_pinning_target_past_lens_enables_optimize_buttons(qapp):
    w = MainWindow()
    _pin_past_demo_lens(w)
    assert w.beam_tab.optimize_flatness_btn.isEnabled()
    assert w.beam_tab.optimize_focus_btn.isEnabled()


def test_optimize_focus_click_moves_optic_and_syncs_form(qapp):
    w = MainWindow()
    optic = w.project.optics[0]
    original_z = optic.z
    w.optics_tab.select_optic(optic.id)
    _pin_past_demo_lens(w)

    w.beam_tab.optimize_focus_btn.click()

    assert optic.z != original_z
    assert w.optics_tab.z_spin.value() == pytest.approx(optic.z, abs=1e-3)
    assert w.plot_view._optic_items[optic.id].pos().x() == pytest.approx(optic.z, abs=1e-3)
    assert "Optimise for focus" in w.statusBar().currentMessage()


def test_optimize_flatness_click_moves_optic_without_raising(qapp):
    w = MainWindow()
    optic = w.project.optics[0]
    original_z = optic.z
    _pin_past_demo_lens(w)

    w.beam_tab.optimize_flatness_btn.click()

    assert optic.z != original_z
    assert "Optimise for flatness" in w.statusBar().currentMessage()


def test_locked_governing_optic_disables_buttons(qapp):
    w = MainWindow()
    w.project.optics[0].lock_z = True
    _pin_past_demo_lens(w)

    assert not w.beam_tab.optimize_flatness_btn.isEnabled()
    assert "locked" in w.beam_tab.optimize_flatness_btn.toolTip()


def test_tightening_precision_disables_buttons_on_infeasible_setup(qapp):
    w = MainWindow()
    optic = w.project.optics[0]
    from telescope_simulator.model.optics import Optic

    # A previous optic leaves only a small gap before the governing lens;
    # the target sits just past the governing lens's own back vertex --
    # comfortable room at the default 10um precision, but not at 1mm.
    prev = Optic(name="Prev", diameter_full=25.4, thickness_center=1.0, z=optic.z - 1.5)
    w.project.optics.append(prev)
    w.optics_tab.set_optics(w.project.optics)
    w.plot_view.set_project(w.project)

    target_z = optic.z + optic.thickness_center + 0.05
    found = w.plot_view.beam_at(target_z)
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)
    assert w.beam_tab.optimize_flatness_btn.isEnabled()

    w.beam_tab.target_precision_spin.setValue(1000.0)  # 1mm >> available room

    assert not w.beam_tab.optimize_flatness_btn.isEnabled()
    assert "No room" in w.beam_tab.optimize_flatness_btn.toolTip()


def test_fit_to_data_updates_beam_and_syncs_beam_tab(qapp):
    w = MainWindow()
    from telescope_simulator.physics.beam import GaussianBeam

    true_beam = GaussianBeam.from_measurement(z_ref=50.0, w_ref=0.5, wavelength_nm=w.project.beam.wavelength_nm, n=1.0)
    # Points straddling the true waist on both sides -- points from only one
    # side leave the fit unable to distinguish the true waist location from
    # a spurious one (w(z) alone doesn't disambiguate direction).
    rows = [(10.0, true_beam), (40.0, true_beam), (60.0, true_beam), (90.0, true_beam)]
    for row, (z, beam) in enumerate(rows):
        w.fit_data_tab.table.item(row, 1).setText(str(z))
        w.fit_data_tab.table.item(row, 2).setText(str(2.0 * beam.w(z)))
    # editing cells emits fitDataChanged live, syncing project.fit_data_points
    assert w.fit_data_tab.fit_btn.isEnabled()

    w.fit_data_tab.fit_btn.click()

    assert w.project.beam.z_ref == pytest.approx(50.0, abs=0.1)
    assert w.project.beam.w_ref == pytest.approx(0.5, abs=0.01)
    assert w.beam_tab.z_ref_spin.value() == pytest.approx(50.0, abs=0.1)
    assert "Fit to data" in w.statusBar().currentMessage()


def test_fit_to_data_shows_error_without_crashing_on_too_few_rows(qapp):
    w = MainWindow()
    w.fit_data_tab.table.item(0, 1).setText("10.0")
    w.fit_data_tab.table.item(0, 2).setText("1.0")

    w.on_fit_requested()  # button itself would be disabled; call handler directly

    assert "at least 3" in w.fit_data_tab.error_label.text()


def test_project_save_load_round_trips_fit_data_points(tmp_path, qapp):
    w = MainWindow()
    w.fit_data_tab.table.item(0, 1).setText("5.0")
    w.fit_data_tab.table.item(0, 2).setText("2.0")

    path = tmp_path / "proj.json"
    w.current_path = str(path)
    w.on_save()

    w2 = MainWindow()
    w2.project = type(w.project).load(str(path))
    w2._load_project_into_ui()

    assert w2.fit_data_tab.table.item(0, 1).text() == "5"


def test_optimize_moves_every_member_of_a_composite_group_and_syncs_canvas(qapp):
    """Optimizing a composite lens must shift every member together (same
    delta) and resync every member's OpticItem on the canvas -- not just
    move the one sub-optic that happens to be 'the optic before the
    target', leaving its group-mates behind."""
    from telescope_simulator.model.optics import Optic

    w = MainWindow()
    demo = w.project.optics[0]

    m1 = Optic(name="E1", diameter_full=25.4, thickness_center=4.0, r1=60.0, r2=float("inf"),
               z=demo.z + demo.thickness_center + 20.0)
    m2 = Optic(name="E2", diameter_full=25.4, thickness_center=3.0, r1=float("inf"), r2=-40.0,
               z=m1.z + m1.thickness_center + 3.0)
    m1.group_id = m2.group_id = m1.id
    m1.group_name = m2.group_name = "Doublet"
    w.project.optics.append(m1)
    w.project.optics.append(m2)
    w.optics_tab.set_optics(w.project.optics)
    w.plot_view.set_project(w.project)

    original_gap = m2.z - (m1.z + m1.thickness_center)
    original_m1_z = m1.z

    found = w.plot_view.beam_at(m2.z + m2.thickness_center + 200.0)
    assert found is not None
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)

    w.optics_tab.select_optic(m1.id)
    w.beam_tab.optimize_flatness_btn.click()

    assert m1.z != original_m1_z
    new_gap = m2.z - (m1.z + m1.thickness_center)
    assert new_gap == pytest.approx(original_gap)
    assert w.plot_view._optic_items[m1.id].pos().x() == pytest.approx(m1.z, abs=1e-3)
    assert w.plot_view._optic_items[m2.id].pos().x() == pytest.approx(m2.z, abs=1e-3)
    assert w.optics_tab.group_z_spin.value() == pytest.approx(m1.z, abs=1e-3)


def test_clamped_optimize_shows_status_message_without_crashing(qapp):
    w = MainWindow()
    optic = w.project.optics[0]
    from telescope_simulator.model.optics import Optic

    neighbor = Optic(name="Neighbor", diameter_full=25.4, thickness_center=1.0, z=optic.z + 5.0)
    w.project.optics.append(neighbor)
    w.optics_tab.set_optics(w.project.optics)
    w.plot_view.set_project(w.project)

    target_z = neighbor.z - 0.05  # in the tight gap right before the neighbor
    found = w.plot_view.beam_at(target_z)
    assert found is not None
    beam, label, z = found
    w.plot_view._pin_at(z, beam, label)

    w.beam_tab.optimize_flatness_btn.click()

    assert optic.z < neighbor.z
    assert "Optimise for flatness" in w.statusBar().currentMessage()
