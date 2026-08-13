import pytest

from telescope_simulator.model.beam_spec import InputBeamSpec
from telescope_simulator.model.fit_data import FitDataPoint
from telescope_simulator.model.optics import Optic
from telescope_simulator.physics.beam import GaussianBeam
from telescope_simulator.physics.fit import FitUnavailable, fit_beam_to_data
from telescope_simulator.physics.system import OpticalSystem

WAVELENGTH_NM = 632.8


def _points_from_beam(beam: GaussianBeam, zs):
    return [FitDataPoint(z_mm=z, diameter_mm=2.0 * beam.w(z)) for z in zs]


def _seed_spec() -> InputBeamSpec:
    # Deliberately wrong guess, far from the true (z_waist, w0) below, so a
    # passing test demonstrates the search actually converges rather than
    # trivially returning its seed.
    return InputBeamSpec(wavelength_nm=WAVELENGTH_NM, z_ref=0.0, w_ref=2.0, collimated=True)


def test_recovers_known_waist_with_no_optics():
    true_beam = GaussianBeam.from_measurement(z_ref=50.0, w_ref=0.5, wavelength_nm=WAVELENGTH_NM, n=1.0)
    points = _points_from_beam(true_beam, [10.0, 40.0, 60.0, 90.0])

    result = fit_beam_to_data(_seed_spec(), [], points)

    assert result.z_waist_mm == pytest.approx(50.0, abs=0.05)
    assert result.w0_mm == pytest.approx(0.5, abs=0.005)
    assert result.objective_value == pytest.approx(0.0, abs=1e-6)


def test_recovers_known_waist_through_a_lens():
    lens = Optic(name="L1", diameter_full=25.4, thickness_center=4.0, r1=50.0, r2=-50.0, n=1.5168, z=100.0)
    true_input = InputBeamSpec(wavelength_nm=WAVELENGTH_NM, z_ref=-20.0, w_ref=0.5, collimated=True)
    result_ref = OpticalSystem(true_input, [lens]).propagate()

    # Sample measurement points from the output segment, past the lens --
    # a full-system fit must account for the lens between input and data.
    output_seg = result_ref.segments[-1]
    zs = [output_seg.z_start + 5.0, output_seg.z_start + 15.0, output_seg.z_start + 30.0]
    points = [FitDataPoint(z_mm=z, diameter_mm=2.0 * output_seg.beam.w(z)) for z in zs]

    seed = InputBeamSpec(wavelength_nm=WAVELENGTH_NM, z_ref=-20.0, w_ref=1.5, collimated=True)
    result = fit_beam_to_data(seed, [lens], points)

    assert result.z_waist_mm == pytest.approx(-20.0, abs=0.1)
    assert result.w0_mm == pytest.approx(0.5, abs=0.01)


def test_fewer_than_three_valid_points_raises():
    points = [FitDataPoint(z_mm=0.0, diameter_mm=1.0), FitDataPoint(z_mm=10.0, diameter_mm=1.2)]
    with pytest.raises(FitUnavailable, match="at least 3"):
        fit_beam_to_data(_seed_spec(), [], points)


def test_partially_filled_rows_are_ignored_not_crashing():
    true_beam = GaussianBeam.from_measurement(z_ref=50.0, w_ref=0.5, wavelength_nm=WAVELENGTH_NM, n=1.0)
    points = _points_from_beam(true_beam, [10.0, 40.0, 60.0])
    points += [FitDataPoint(z_mm=20.0, diameter_mm=None), FitDataPoint(z_mm=None, diameter_mm=None)]

    result = fit_beam_to_data(_seed_spec(), [], points)

    assert result.z_waist_mm == pytest.approx(50.0, abs=0.05)
