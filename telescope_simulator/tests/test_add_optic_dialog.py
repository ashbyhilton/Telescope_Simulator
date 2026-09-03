import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.gui.dialogs.add_optic_dialog import AddOpticDialog
from telescope_simulator.model.optics import Optic, edge_thickness_from_center


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_single_optic_defaults_and_result(qapp):
    dialog = AddOpticDialog()
    optic = dialog.result_optic()
    assert not dialog.is_composite()
    assert optic.diameter_full > 0
    assert math.isinf(optic.r1) and math.isinf(optic.r2)


def test_single_optic_thickness_and_edge_thickness_are_coupled(qapp):
    dialog = AddOpticDialog()
    fields = dialog.single_page.fields
    fields.diameter_spin.setValue(20.0)
    fields.r1_flat_check.setChecked(False)
    fields.r1_spin.setValue(50.0)
    fields.r2_flat_check.setChecked(False)
    fields.r2_spin.setValue(50.0)  # displayed positive-is-convex -> stored r2 = -50.0
    fields.thickness_spin.setValue(5.0)

    # abs=5e-5: the spin box rounds to 4 decimal places, so its displayed
    # value is only that precise relative to the raw formula result.
    expected_edge = edge_thickness_from_center(50.0, -50.0, 20.0, 5.0)
    assert fields.edge_thickness_spin.value() == pytest.approx(expected_edge, abs=5e-5)

    # Editing edge thickness directly must recompute center thickness, and
    # round-trip back to the same edge thickness.
    fields.edge_thickness_spin.setValue(4.0)
    assert fields.edge_thickness_spin.value() == pytest.approx(4.0)
    optic = dialog.result_optic()
    recovered_edge = edge_thickness_from_center(optic.r1, optic.r2, optic.diameter_full, optic.thickness_center)
    assert recovered_edge == pytest.approx(4.0, abs=5e-5)


def test_composite_page_builds_group_with_shared_id_and_chained_z(qapp):
    dialog = AddOpticDialog()
    dialog.tabs.setCurrentWidget(dialog.composite_page)
    page = dialog.composite_page
    # Seeded with one element; add a second and set a spacing between them.
    page._on_add_element()
    page.list_widget.setCurrentRow(0)
    page.fields.thickness_spin.setValue(4.0)
    page.list_widget.setCurrentRow(1)
    page.fields.thickness_spin.setValue(3.0)
    page.list_widget.setCurrentRow(0)
    page.spacing_spin.setValue(2.0)
    page.group_name_edit.setText("Test Doublet")

    assert dialog.is_composite()
    members = dialog.result_group()
    assert len(members) == 2
    assert members[0].group_id == members[1].group_id == members[0].id
    assert members[0].group_name == members[1].group_name == "Test Doublet"
    assert members[0].z == pytest.approx(0.0)
    assert members[1].z == pytest.approx(4.0 + 2.0)  # element 1 thickness + spacing


def test_composite_page_load_group_prepopulates_existing_members(qapp):
    m1 = Optic(name="Existing 1", thickness_center=4.0, z=100.0)
    m2 = Optic(name="Existing 2", thickness_center=3.0, z=106.0)
    m1.group_id = m2.group_id = m1.id
    m1.group_name = m2.group_name = "Existing Group"

    dialog = AddOpticDialog(existing_group=[m1, m2])
    assert dialog.is_composite()
    assert dialog.composite_page.group_name_edit.text() == "Existing Group"
    assert [o.name for o in dialog.composite_page.elements] == ["Existing 1", "Existing 2"]
    assert dialog.composite_page.spacings == pytest.approx([2.0])  # 106 - (100 + 4)


def test_composite_page_cannot_remove_last_remaining_element(qapp):
    dialog = AddOpticDialog()
    page = dialog.composite_page
    assert len(page.elements) == 1
    page.list_widget.setCurrentRow(0)
    page._on_remove_element()
    assert len(page.elements) == 1


def test_existing_single_prepopulates_single_page(qapp):
    optic = Optic(name="Existing Singlet", diameter_full=12.0, thickness_center=3.0, r1=40.0, r2=float("inf"), n=1.6)
    dialog = AddOpticDialog(existing_single=optic)
    assert not dialog.is_composite()
    assert dialog.single_page.fields.name_edit.text() == "Existing Singlet"
    assert dialog.single_page.fields.diameter_spin.value() == pytest.approx(12.0)


def test_lens_preview_uses_light_colors_on_a_light_palette(qapp):
    """Regression test: the preview used to always use dark-gray text/lines
    with no explicit background, which was fine on the default light
    palette but 'very faint' once dark mode set the app-wide QPalette dark
    (pg.PlotWidget's background follows QPalette when not explicitly set)."""
    from pyqtgraph.Qt import QtGui

    original_palette = qapp.palette()
    try:
        light = QtGui.QPalette()
        light.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(240, 240, 240))
        qapp.setPalette(light)
        dialog = AddOpticDialog()
        assert dialog.single_page.preview._text_color == (70, 70, 70)
    finally:
        qapp.setPalette(original_palette)


def test_lens_preview_uses_high_contrast_colors_on_a_dark_palette(qapp):
    from pyqtgraph.Qt import QtGui

    original_palette = qapp.palette()
    try:
        dark = QtGui.QPalette()
        dark.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(53, 53, 53))
        qapp.setPalette(dark)
        dialog = AddOpticDialog()
        assert dialog.single_page.preview._text_color == (220, 220, 220)
    finally:
        qapp.setPalette(original_palette)
