import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pyqtgraph.Qt import QtWidgets

from telescope_simulator.gui.tabs.beam_tab import BeamTab
from telescope_simulator.model.beam_spec import InputBeamSpec


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_unchecking_collimated_never_leaves_r_ref_at_zero(qapp):
    """Regression test: unchecking 'Collimated' used to leave r_ref_spin at
    its default 0.0, which GaussianBeam.from_measurement() cannot handle --
    the crash happened inside _update_input_characteristics(), before
    beamChanged.emit() in the same method, so every downstream refresh
    silently stopped working from that point on."""
    tab = BeamTab()
    tab.set_beam(InputBeamSpec(collimated=True))  # MainWindow always calls set_beam()
    # before a user can interact -- the checkbox otherwise defaults to
    # unchecked regardless of the model, so unchecking it wouldn't even
    # fire a real toggled() transition without this.
    seen = []
    tab.beamChanged.connect(lambda beam: seen.append(beam))

    assert tab.r_ref_spin.value() == 0.0  # default, untouched
    tab.collimated_check.setChecked(False)

    assert tab.r_ref_spin.value() != 0.0
    assert tab.beam.r_ref != 0.0
    assert seen, "beamChanged must still fire after unchecking Collimated"


def test_typing_zero_into_r_ref_directly_does_not_stick(qapp):
    tab = BeamTab()
    tab.set_beam(InputBeamSpec(collimated=False, r_ref=500.0))
    seen = []
    tab.beamChanged.connect(lambda beam: seen.append(beam))

    tab.r_ref_spin.setValue(0.0)

    assert tab.r_ref_spin.value() != 0.0
    assert tab.beam.r_ref != 0.0
    assert seen
