import math

import pytest

from telescope_simulator.model.optics import (
    Optic,
    center_thickness_from_edge,
    edge_thickness_from_center,
    group_key,
    layout_group_z,
    surface_sag,
)


def test_surface_sag_is_zero_for_flat():
    assert surface_sag(float("inf"), 5.0) == 0.0
    assert surface_sag(float("-inf"), 5.0) == 0.0


def test_surface_sag_matches_hand_computed_value():
    # R=50mm, x=10mm: R - sqrt(R^2 - x^2) = 50 - sqrt(2500 - 100) = 50 - sqrt(2400).
    expected = 50.0 - math.sqrt(2400.0)
    assert surface_sag(50.0, 10.0) == pytest.approx(expected)
    # Concave (R<0) surface has the opposite-signed sag.
    assert surface_sag(-50.0, 10.0) == pytest.approx(-expected)


def test_edge_thickness_of_flat_flat_window_equals_center_thickness():
    edge = edge_thickness_from_center(float("inf"), float("inf"), 20.0, 5.0)
    assert edge == pytest.approx(5.0)


def test_edge_thickness_of_symmetric_biconvex_lens_matches_hand_derivation():
    # R1=50 (convex front), R2=-50 (convex back), diameter=20mm, center=5mm.
    # Edge thickness = center - 2*(R - sqrt(R^2 - (d/2)^2)) for this
    # symmetric case, since both surfaces bulge outward by the same sag.
    r = 50.0
    half_d = 10.0
    sag = r - math.sqrt(r * r - half_d * half_d)
    expected_edge = 5.0 - 2.0 * sag
    edge = edge_thickness_from_center(r1=r, r2=-r, diameter_full=2 * half_d, thickness_center=5.0)
    assert edge == pytest.approx(expected_edge)
    assert edge < 5.0  # thinner at the edge than the center, as expected for biconvex


def test_center_thickness_from_edge_round_trips_through_edge_thickness_from_center():
    r1, r2, diameter, center = 50.0, -80.0, 15.0, 6.0
    edge = edge_thickness_from_center(r1, r2, diameter, center)
    recovered_center = center_thickness_from_edge(r1, r2, diameter, edge)
    assert recovered_center == pytest.approx(center)


def test_layout_group_z_chains_thickness_and_spacing():
    elements = [
        Optic(name="A", thickness_center=4.0),
        Optic(name="B", thickness_center=3.0),
        Optic(name="C", thickness_center=2.0),
    ]
    spacings = [1.0, 5.0]
    zs = layout_group_z(elements, spacings, anchor_z=10.0)
    assert zs == pytest.approx([10.0, 15.0, 23.0])  # 10 -> +4+1=15 -> +3+5=23


def test_group_key_is_own_id_when_standalone_and_group_id_when_grouped():
    standalone = Optic(name="Solo")
    assert group_key(standalone) == standalone.id

    a = Optic(name="A")
    b = Optic(name="B")
    a.group_id = b.group_id = a.id
    assert group_key(a) == a.id
    assert group_key(b) == a.id
