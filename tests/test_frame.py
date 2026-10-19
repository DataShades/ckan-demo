"""The browser frame: layout, and the image Chromium draws."""

from __future__ import annotations

import pytest

from ckan_demo.frame import Layout, page_html, render


def test_layout_centres_the_window_and_records_only_the_page():
    layout = Layout.fit(1920, 1080, 0.06)

    assert (layout.x, layout.y, layout.bar) == (64, 64, 38)
    assert (layout.content_x, layout.content_y) == (64, 102)
    assert (layout.content_width, layout.content_height) == (1792, 914)
    assert layout.content_y + layout.content_height == 1080 - 64


@pytest.mark.parametrize("size", [(1281, 721), (1280, 720), (853, 480)])
def test_layout_sizes_and_offsets_are_even(size):
    layout = Layout.fit(*size)

    values = (layout.content_x, layout.content_y, layout.content_width, layout.content_height)
    assert all(value % 2 == 0 for value in values)


def test_no_padding_fills_the_video_below_the_bar():
    layout = Layout.fit(1280, 720, 0)

    assert (layout.x, layout.y, layout.content_width) == (0, 0, 1280)
    assert layout.content_height == 720 - layout.bar


@pytest.mark.parametrize(("size", "padding", "message"), [((1920, 1080), 0.5, "between 0"), ((8, 40), 0.2, "small")])
def test_bad_layouts(size, padding, message):
    with pytest.raises(ValueError, match=message):
        Layout.fit(*size, padding)


def test_address_is_escaped():
    assert "a&lt;b" in page_html(Layout.fit(640, 360), background="navy", address="a<b")


def test_render_leaves_the_page_area_transparent(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    image_api = pytest.importorskip("PIL.Image")
    layout = Layout.fit(640, 360, 0.1)
    try:
        path = render(layout, tmp_path / "frame.png", background="rgb(255 0 0)", address="demo.ckan.org")
    except sync_api.Error as error:
        pytest.skip(f"no Chromium: {error}")

    with image_api.open(path) as image:
        assert image.size == (640, 360)
        pixel = image.convert("RGBA").getpixel
        assert pixel((2, 2)) == (255, 0, 0, 255)  # background
        middle = (layout.content_x + layout.content_width // 2, layout.content_y + layout.content_height // 2)
        assert pixel(middle)[3] == 0  # page
        assert pixel((layout.content_x + 1, layout.content_y + layout.content_height - 1))[3] > 0  # rounded corner
        assert pixel((layout.x + layout.content_width // 4, layout.y + layout.bar // 2))[3] == 255  # title bar
