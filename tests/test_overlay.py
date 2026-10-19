"""The overlay's caption placement, in a real headless Chromium (no video)."""

from __future__ import annotations

import pytest

from ckan_demo.director import Director, Options
from ckan_demo.recorder import OVERLAY

PAGE = """
<body style="margin:0; height:100vh">
  <button id="low" style="position:fixed; left:50%; bottom:50px; width:200px; height:40px">Low</button>
  <button id="high" style="position:fixed; left:50%; top:300px; width:200px; height:40px">High</button>
  <button id="corner" style="position:fixed; left:10px; bottom:10px; width:60px; height:30px">Corner</button>
</body>
"""


@pytest.fixture(scope="module")
def chromium():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch()
        except Exception as error:
            pytest.skip(f"no Chromium: {error}")
        yield launched
        launched.close()


@pytest.fixture
def director(chromium):
    page = chromium.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(PAGE)
    page.add_script_tag(content=OVERLAY)  # set_content doesn't run init scripts
    page.mouse.move(640, 360)
    yield Director(page, Options(base_url="http://x", width=1280, height=720, speed=10))
    page.close()


def _edge(d: Director) -> str:
    """Where the caption ends up, once any move has faded in."""
    d._page.wait_for_timeout(400)
    classes = d._page.eval_on_selector("#demo-caption", "el => [...el.classList]")
    assert "shown" in classes
    return "top" if "top" in classes else "bottom"


def test_fixed_positions(director):
    director.caption("At the top", position="top")
    assert _edge(director) == "top"

    director.caption("Back at the bottom")
    director.point(director._page.locator("#low"))
    assert _edge(director) == "bottom"  # only auto moves


def test_auto_moves_out_of_the_way_of_the_next_target(director):
    director.caption("Assign it to yourself", position="auto")
    assert _edge(director) == "bottom"

    director.point(director._page.locator("#high"))
    assert _edge(director) == "bottom"  # nothing covered

    director.point(director._page.locator("#low"))
    assert _edge(director) == "top"

    director.point(director._page.locator("#high"))
    assert _edge(director) == "top"  # stays until the next caption


def test_auto_ignores_targets_beside_the_caption(director):
    director.caption("Short", position="auto")

    director.point(director._page.locator("#corner"))

    assert _edge(director) == "bottom"


def test_auto_starts_at_the_top_when_the_pointer_is_already_under_it(director):
    director.point(director._page.locator("#low"))

    director.caption("Now send it", position="auto")

    assert _edge(director) == "top"


def _keys(d: Director) -> dict:
    return d._page.eval_on_selector(
        "#demo-keys",
        """el => ({shown: el.classList.contains("shown"), text: el.innerText.replace(/\\s+/g, " "),
                  top: el.getBoundingClientRect().top, bottom: el.getBoundingClientRect().bottom})""",
    )


def _caption_box(d: Director) -> dict:
    return d._page.eval_on_selector("#demo-caption", "el => el.getBoundingClientRect().toJSON()")


def test_key_badge_sits_next_to_the_caption_and_fades(director):
    director.caption("Ctrl+Enter sends it")
    director._page.wait_for_timeout(400)

    director.press("Control+Enter")

    badge = _keys(director)
    assert badge["shown"]
    assert badge["text"] == "Ctrl + Enter"
    assert badge["bottom"] < _caption_box(director)["top"]  # just above a bottom caption
    director._page.wait_for_timeout(300)  # 1.8 s at --speed 10, minus the time already waited
    assert not _keys(director)["shown"]


def test_key_badge_goes_below_a_top_caption(director):
    director.caption("At the top", position="top")
    director._page.wait_for_timeout(400)

    director.press("Control+Enter")

    assert _keys(director)["top"] > _caption_box(director)["bottom"]


def test_key_badge_without_a_caption_sits_at_the_bottom(director):
    director.press("Control+Enter")

    assert _keys(director)["shown"]
    assert director._page.eval_on_selector("#demo-keys", "el => getComputedStyle(el).bottom") == "40px"
