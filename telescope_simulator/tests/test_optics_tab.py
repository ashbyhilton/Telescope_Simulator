import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.gui.tabs.optics_tab import OpticsTab
from telescope_simulator.model.optics import Optic, OpticKind, make_default_optic


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _StubFields:
    def __init__(self, apply_fn=None):
        self._apply_fn = apply_fn or (lambda optic: None)

    def apply(self, optic):
        self._apply_fn(optic)


class _StubSinglePage:
    def __init__(self, apply_fn=None):
        self.fields = _StubFields(apply_fn)


class _StubAddDialog:
    """Stands in for the real modal AddOpticDialog in tests -- exec()'ing a
    real QDialog would block the test's event loop waiting for a click, so
    OpticsTab's add/edit flow is tested against this pre-canned result
    instead of driving the dialog's own widgets end-to-end."""

    def __init__(self, optic=None, group=None, apply_fn=None):
        self._optic = optic
        self._group = group
        self.single_page = _StubSinglePage(apply_fn)

    def exec(self):
        return QtWidgets.QDialog.DialogCode.Accepted

    def is_composite(self) -> bool:
        return self._group is not None

    def result_optic(self):
        return self._optic

    def result_group(self):
        return self._group


def test_typing_zero_into_r1_makes_the_surface_flat(qapp):
    """A radius of curvature of zero *means* flat -- it is the number a user
    reaches for, and it is the one value that has no other sensible meaning
    (a point has no curvature). Typing it ticks Flat and stores an infinite
    radius; the field is never disabled, so Flat is a label rather than a
    mode you have to leave before you can type."""
    tab = OpticsTab()
    optic = make_default_optic(OpticKind.BICONVEX, "Test Lens")
    tab.set_optics([optic])
    tab.select_optic(optic.id)

    assert not tab.r1_flat_check.isChecked()
    tab.r1_spin.setValue(0.0)

    assert math.isinf(optic.r1)
    assert tab.r1_flat_check.isChecked()
    assert tab.r1_spin.isEnabled()

    # ...and typing a real radius takes it straight back out of flat.
    tab.r1_spin.setValue(75.0)

    assert optic.r1 == pytest.approx(75.0)
    assert not tab.r1_flat_check.isChecked()


def test_typing_zero_into_r2_makes_the_surface_flat(qapp):
    tab = OpticsTab()
    optic = make_default_optic(OpticKind.BICONVEX, "Test Lens")
    tab.set_optics([optic])
    tab.select_optic(optic.id)

    assert not tab.r2_flat_check.isChecked()
    tab.r2_spin.setValue(0.0)

    assert math.isinf(optic.r2)
    assert tab.r2_flat_check.isChecked()
    assert tab.r2_spin.isEnabled()

    tab.r2_spin.setValue(75.0)

    # Displayed sign is flipped from the stored physics convention.
    assert optic.r2 == pytest.approx(-75.0)
    assert not tab.r2_flat_check.isChecked()


def test_unticking_flat_snaps_away_from_the_zero_that_means_flat(qapp):
    """Unticking has to land on *some* non-zero radius, or the box would
    still read as flat -- the same repair-at-entry pattern beam_tab.py uses
    for a zero wavefront radius."""
    tab = OpticsTab()
    optic = make_default_optic(OpticKind.PLANO_CONVEX, "Test Lens")
    tab.set_optics([optic])
    tab.select_optic(optic.id)

    tab.r1_flat_check.setChecked(True)
    assert math.isinf(optic.r1)
    assert tab.r1_spin.value() == 0.0

    tab.r1_flat_check.setChecked(False)

    assert tab.r1_spin.value() != 0.0
    assert not math.isinf(optic.r1)


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


def test_add_single_optic_appends_dialog_result(qapp, monkeypatch):
    tab = OpticsTab()
    tab.set_optics([])
    stub_optic = Optic(name="Custom Optic", diameter_full=10.0, r1=30.0, r2=float("inf"))
    monkeypatch.setattr(
        "telescope_simulator.gui.tabs.optics_tab.AddOpticDialog",
        lambda parent=None, existing_group=None: _StubAddDialog(optic=stub_optic),
    )
    tab._on_add_clicked()

    assert tab.optics == [stub_optic]
    assert stub_optic.z == 10.0  # max(default=0.0) + 10.0, unchanged insertion rule
    assert tab.list_widget.count() == 1
    assert tab._selected_id == stub_optic.id


def test_add_composite_group_appends_every_member_as_one_row(qapp, monkeypatch):
    tab = OpticsTab()
    tab.set_optics([])
    m1 = Optic(name="Element 1", thickness_center=4.0, z=0.0)
    m2 = Optic(name="Element 2", thickness_center=3.0, z=6.0)
    m1.group_id = m2.group_id = m1.id
    m1.group_name = m2.group_name = "Doublet"
    monkeypatch.setattr(
        "telescope_simulator.gui.tabs.optics_tab.AddOpticDialog",
        lambda parent=None, existing_group=None: _StubAddDialog(group=[m1, m2]),
    )
    tab._on_add_clicked()

    assert tab.optics == [m1, m2]
    assert tab.list_widget.count() == 1  # one row for the whole group
    assert m1.z == 10.0
    assert m2.z == 16.0  # relative spacing (6.0) preserved under the insertion offset


def test_composite_row_selection_shows_group_summary_not_form(qapp):
    tab = OpticsTab()
    m1 = Optic(name="Element 1", thickness_center=4.0, z=0.0)
    m2 = Optic(name="Element 2", thickness_center=3.0, z=6.0)
    m1.group_id = m2.group_id = m1.id
    m1.group_name = m2.group_name = "Doublet"
    tab.set_optics([m1, m2])

    tab.select_optic(m1.id)

    assert not tab.group_box.isHidden()
    assert tab.form.isHidden()
    assert "Element 1" in tab.group_members_label.text()
    assert "Element 2" in tab.group_members_label.text()


def test_removing_composite_row_removes_every_member(qapp):
    tab = OpticsTab()
    m1 = Optic(name="Element 1", thickness_center=4.0, z=0.0)
    m2 = Optic(name="Element 2", thickness_center=3.0, z=6.0)
    m1.group_id = m2.group_id = m1.id
    tab.set_optics([m1, m2])
    tab.select_optic(m1.id)

    tab._on_remove_clicked()

    assert tab.optics == []


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


def test_edit_single_lens_applies_dialog_fields_in_place(qapp, monkeypatch):
    """'Edit lens...' must edit the existing Optic in place (same id/z),
    not replace it -- matching how the inline form already edits it."""
    tab = OpticsTab()
    optic = make_default_optic(OpticKind.BICONVEX, "Lens 1", z=42.0)
    tab.set_optics([optic])
    tab.select_optic(optic.id)
    original_id = optic.id

    def apply_fn(o):
        o.diameter_full = 30.0
        o.name = "Renamed Lens"

    monkeypatch.setattr(
        "telescope_simulator.gui.tabs.optics_tab.AddOpticDialog",
        lambda parent=None, existing_group=None, existing_single=None: _StubAddDialog(apply_fn=apply_fn),
    )
    tab._on_edit_single_clicked()

    assert optic.id == original_id
    assert optic.diameter_full == 30.0
    assert optic.name == "Renamed Lens"
    assert optic.z == 42.0
    assert tab.list_widget.item(0).text() == "Renamed Lens"


def test_group_z_spin_shifts_every_member_by_same_delta(qapp):
    tab = OpticsTab()
    m1 = Optic(name="E1", thickness_center=4.0, z=0.0)
    m2 = Optic(name="E2", thickness_center=3.0, z=6.0)
    m1.group_id = m2.group_id = m1.id
    tab.set_optics([m1, m2])
    tab.select_optic(m1.id)

    tab.group_z_spin.setValue(50.0)

    assert m1.z == pytest.approx(50.0)
    assert m2.z == pytest.approx(56.0)  # 6.0 spacing preserved


def test_group_lock_check_locks_every_member(qapp):
    tab = OpticsTab()
    m1 = Optic(name="E1", thickness_center=4.0, z=0.0)
    m2 = Optic(name="E2", thickness_center=3.0, z=6.0)
    m1.group_id = m2.group_id = m1.id
    tab.set_optics([m1, m2])
    tab.select_optic(m1.id)

    tab.group_lock_check.setChecked(True)

    assert m1.lock_z is True
    assert m2.lock_z is True


def test_group_efl_matches_independent_two_thin_lens_formula(qapp):
    """Checked against the textbook two-thin-lens combined-focal-length
    formula (1/f = 1/f1 + 1/f2 - d/(f1*f2)), not against this app's own
    thick_lens()/propagation() re-composed a second way -- an independent
    result, per this repo's testing convention."""
    tab = OpticsTab()
    n = 1.5168
    r1a, r2a = 100.0, float("inf")
    r1b, r2b = float("inf"), -100.0
    gap = 50.0
    thin = 1e-6
    m1 = Optic(name="L1", thickness_center=thin, r1=r1a, r2=r2a, n=n, z=0.0)
    m2 = Optic(name="L2", thickness_center=thin, r1=r1b, r2=r2b, n=n, z=thin + gap)
    m1.group_id = m2.group_id = m1.id

    f1 = 1.0 / ((n - 1.0) * (1.0 / r1a))
    f2 = 1.0 / ((n - 1.0) * (1.0 / abs(r2b)))
    inv_f_expected = 1.0 / f1 + 1.0 / f2 - gap / (f1 * f2)
    f_expected = 1.0 / inv_f_expected

    m = tab._composite_matrix([m1, m2])
    power = -m[1, 0]
    assert (1.0 / power) == pytest.approx(f_expected, rel=1e-3)
