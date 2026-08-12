from telescope_simulator.gui.mm_axis import format_length_mm


def test_small_value_uses_micrometers():
    assert format_length_mm(0.5) == "500 µm"


def test_millimeter_range_uses_mm():
    assert format_length_mm(35.0) == "35 mm"


def test_large_value_uses_meters_not_scientific_notation():
    text = format_length_mm(3.5e4)
    assert "e" not in text.lower()
    assert text == "35 m"


def test_very_large_value_uses_kilometers():
    text = format_length_mm(2.5e7)
    assert text == "25 km"
