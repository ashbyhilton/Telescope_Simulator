import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.gui.tabs.optics_tab import OpticsTab
from telescope_simulator.model.optics import OpticKind, describe_shape, make_default_optic


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_typing_zero_into_r1_does_not_stick_with_flat_unchecked(qapp):
    tab = OpticsTab()
    optic = make_default_optic(OpticKind.BICONVEX, "Test Lens")
    tab.set_optics([optic])
    tab.select_optic(optic.id)

    assert not tab.r1_flat_check.isChecked()
    tab.r1_spin.setValue(0.0)

    assert optic.r1 != 0.0
    assert not tab.r1_flat_check.isChecked()


def test_typing_zero_into_r2_does_not_stick_with_flat_unchecked(qapp):
    tab = OpticsTab()
    optic = make_default_optic(OpticKind.BICONVEX, "Test Lens")
    tab.set_optics([optic])
    tab.select_optic(optic.id)

    assert not tab.r2_flat_check.isChecked()
    tab.r2_spin.setValue(0.0)

    assert optic.r2 != 0.0
    assert not tab.r2_flat_check.isChecked()


def test_shape_label_tracks_hand_edited_roc_not_stale_kind(qapp):
    tab = OpticsTab()
    # Created as plano-concave (R1=-50, R2=inf); hand-edit into a
    # plano-convex shape (R1 flat, R2 displayed as +50 = convex per the
    # tab's positive-is-convex convention) without touching `optic.kind`,
    # the way a user can from the Optics tab form.
    optic = make_default_optic(OpticKind.PLANO_CONCAVE, "Lens 1")
    tab.set_optics([optic])
    tab.select_optic(optic.id)

    tab.r1_flat_check.setChecked(True)
    tab.r2_flat_check.setChecked(False)
    tab.r2_spin.setValue(50.0)

    assert optic.kind is OpticKind.PLANO_CONCAVE
    assert tab.shape_label.text() == "Plano-convex"


def test_r2_spin_displays_positive_for_convex_back_surface(qapp):
    """The R2 spinbox shows the opposite sign of the physics-convention
    Optic.r2 it's bound to, so positive always reads as convex (matching
    R1) instead of depending on which surface it is."""
    tab = OpticsTab()
    # BICONVEX preset stores r2=-50 internally (physics convention: R2<0 is
    # a convex back surface) -- the tab should display +50.
    optic = make_default_optic(OpticKind.BICONVEX, "Biconvex Lens")
    tab.set_optics([optic])
    tab.select_optic(optic.id)

    assert optic.r2 == -50.0
    assert tab.r2_spin.value() == pytest.approx(50.0)


def test_add_dropdown_offers_only_flat_plate_and_singlet_lens(qapp):
    tab = OpticsTab()
    labels = [tab.kind_combo.itemText(i) for i in range(tab.kind_combo.count())]
    assert labels == ["Flat plate", "Singlet lens"]


def test_add_singlet_lens_defaults_to_plano_convex_shape(qapp):
    tab = OpticsTab()
    tab.set_optics([])
    tab.kind_combo.setCurrentIndex(tab.kind_combo.findText("Singlet lens"))
    tab._on_add_clicked()

    assert len(tab.optics) == 1
    optic = tab.optics[0]
    assert optic.name == "Singlet Lens 1"
    assert describe_shape(optic.r1, optic.r2) == "Plano-convex"


def test_add_flat_plate_defaults_to_flat_window(qapp):
    tab = OpticsTab()
    tab.set_optics([])
    tab.kind_combo.setCurrentIndex(tab.kind_combo.findText("Flat plate"))
    tab._on_add_clicked()

    assert len(tab.optics) == 1
    optic = tab.optics[0]
    assert optic.name == "Flat Plate 1"
    assert describe_shape(optic.r1, optic.r2) == "Plano-plano (flat window)"


def test_bfl_matches_efl_in_thin_lens_limit(qapp):
    """For a thin lens, the back vertex and the principal plane coincide,
    so back focal length must equal effective focal length."""
    tab = OpticsTab()
    optic = make_default_optic(OpticKind.BICONVEX, "Thin Lens")
    optic.thickness_center = 1e-6
    tab.set_optics([optic])
    tab.select_optic(optic.id)

    assert tab.bfl_label.text() == tab.efl_label.text()


def test_bfl_differs_from_efl_for_a_thick_lens(qapp):
    tab = OpticsTab()
    optic = make_default_optic(OpticKind.BICONVEX, "Thick Lens")
    optic.thickness_center = 20.0
    tab.set_optics([optic])
    tab.select_optic(optic.id)

    assert tab.bfl_label.text() != "-"
    assert tab.bfl_label.text() != tab.efl_label.text()
