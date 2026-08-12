from telescope_simulator.gui.color_utils import wavelength_to_rgb


def test_infrared_clamps_to_red_edge_color():
    edge = wavelength_to_rgb(700.0)
    assert wavelength_to_rgb(701.0) == edge
    assert wavelength_to_rgb(1064.0) == edge


def test_ultraviolet_clamps_to_violet_edge_color():
    edge = wavelength_to_rgb(400.0)
    assert wavelength_to_rgb(399.0) == edge
    assert wavelength_to_rgb(266.0) == edge


def test_green_band_is_green_dominant():
    r, g, b = wavelength_to_rgb(532.0)
    assert g > r and g > b
    assert all(0 <= c <= 255 for c in (r, g, b))


def test_red_band_is_red_dominant():
    r, g, b = wavelength_to_rgb(650.0)
    assert r > g and r > b


def test_blue_band_is_blue_dominant():
    r, g, b = wavelength_to_rgb(450.0)
    assert b > r and b > g


def test_boundary_values_do_not_raise():
    for wl in (400.0, 700.0, 440.0, 490.0, 510.0, 580.0, 645.0):
        r, g, b = wavelength_to_rgb(wl)
        assert all(0 <= c <= 255 for c in (r, g, b))
