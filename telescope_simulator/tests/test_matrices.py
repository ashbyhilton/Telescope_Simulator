import numpy as np

from telescope_simulator.physics.matrices import interface, propagation, thick_lens


def test_propagation_matrix():
    m = propagation(12.5)
    assert np.allclose(m, [[1.0, 12.5], [0.0, 1.0]])


def test_flat_interface_matches_index_ratio():
    m = interface(1.0, 1.5, float("inf"))
    assert np.allclose(m, [[1.0, 0.0], [0.0, 1.0 / 1.5]])


def test_plano_plano_window_reduces_to_scaled_propagation():
    # Derivable exactly (not just in a limit): a flat-flat window of physical
    # thickness t and index n is equivalent, in this ray-vector convention,
    # to free-space propagation over the "reduced thickness" t/n.
    t, n = 8.0, 1.51
    m = thick_lens(thickness=t, n_lens=n, r1=float("inf"), r2=float("inf"))
    assert np.allclose(m, propagation(t / n))


def test_thick_lens_thin_limit_matches_lensmaker_equation():
    # As thickness -> 0, the thick-lens matrix must reduce to the standard
    # thin-lens matrix [[1, 0], [-1/f, 1]] with 1/f = (n-1)(1/R1 - 1/R2).
    n, r1, r2 = 1.5, 100.0, -100.0
    expected_power = (n - 1.0) * (1.0 / r1 - 1.0 / r2)  # = 1/f
    m = thick_lens(thickness=1e-6, n_lens=n, r1=r1, r2=r2)
    assert np.isclose(m[0, 0], 1.0, atol=1e-6)
    assert np.isclose(m[0, 1], 0.0, atol=1e-4)
    assert np.isclose(m[1, 0], -expected_power, rtol=1e-5)
    assert np.isclose(m[1, 1], 1.0, atol=1e-6)


def test_biconcave_defaults_are_diverging_in_thin_limit():
    n, r1, r2 = 1.5, -50.0, 50.0
    m = thick_lens(thickness=1e-6, n_lens=n, r1=r1, r2=r2)
    power = -m[1, 0]  # 1/f
    assert power < 0
