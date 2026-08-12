from telescope_simulator.gui.color_utils import PALE_PINK, VIOLET, wavelength_to_rgb


def test_infrared_is_pale_pink():
    assert wavelength_to_rgb(701.0) == PALE_PINK
    assert wavelength_to_rgb(1064.0) == PALE_PINK


def test_ultraviolet_is_violet():
    assert wavelength_to_rgb(399.0) == VIOLET
    assert wavelength_to_rgb(266.0) == VIOLET


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
