"""The overlay's captions, badges, cards and scrolling, in a real headless Chromium (no video)."""

from __future__ import annotations

import pytest

from ckan_demo.config import Brand
from ckan_demo.director import Director, Options
from ckan_demo.recorder import OVERLAY, overlay_script

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


def _spotlight(d: Director) -> dict:
    return d._page.eval_on_selector(
        "#demo-spotlight",
        "el => ({shown: el.classList.contains('shown'), box: el.getBoundingClientRect().toJSON()})",
    )


def test_spotlight_frames_the_element_and_fades(director):
    page = director._page
    target = page.locator("#high")
    box = target.bounding_box()
    page.evaluate("box => window.__demo.spotlight(box, 8)", box)

    spot = _spotlight(director)
    assert spot["shown"]
    assert spot["box"]["x"] == pytest.approx(box["x"] - 8)
    assert spot["box"]["width"] == pytest.approx(box["width"] + 16)

    director.spotlight(target, hold=0.5)

    assert not _spotlight(director)["shown"]


def test_spotlight_stays_under_the_caption_and_pointer(director):
    z = director._page.evaluate(
        "() => ['#demo-spotlight', '#demo-caption', '#demo-cursor'].map("
        "s => +getComputedStyle(document.querySelector(s)).zIndex)"
    )
    assert z[0] < z[1] < z[2]


TALL_PAGE = """
<html style="scroll-behavior: smooth">
<body style="margin:0">
  <button id="top" style="height:40px">Top</button>
  <div style="height:3000px"></div>
  <button id="far" style="height:40px">Far</button>
  <div style="height:1000px"></div>
</body>
</html>
"""


@pytest.fixture
def tall(chromium):
    page = chromium.new_page(viewport={"width": 1280, "height": 720})
    page.set_content(TALL_PAGE)
    page.add_script_tag(content=OVERLAY)
    yield page
    page.close()


def test_reveal_scrolls_gradually_and_centres(tall):
    far = tall.locator("#far")

    mid, end = far.evaluate(
        """async el => {
            const done = window.__demo.reveal(el, 1);
            await new Promise(r => setTimeout(r, 250));
            const mid = window.scrollY;
            await done;
            return [mid, window.scrollY];
        }"""
    )

    assert 0 < mid < end  # moving, not a jump
    box = far.bounding_box()
    assert box["y"] + box["height"] / 2 == pytest.approx(360, abs=2)


def test_reveal_leaves_visible_elements_alone(tall):
    assert tall.locator("#top").evaluate("el => window.__demo.reveal(el, 1)") == 0
    assert tall.evaluate("() => window.scrollY") == 0


def test_point_reveals_before_moving(tall):
    d = Director(tall, Options(base_url="http://x", width=1280, height=720, speed=10))

    d.point(tall.locator("#far"))

    assert tall.evaluate("() => window.scrollY") > 2000
    assert d.y == pytest.approx(360, abs=2)


def _card(page, brand: dict[str, str]) -> dict:
    page.set_content("<body></body>")
    page.add_script_tag(content=overlay_script(brand))
    page.evaluate("() => window.__demo.card('Kicker', 'Title', 'Text')")
    return page.evaluate(
        """() => {
            const style = (selector, property) => getComputedStyle(document.querySelector(selector))[property];
            const logo = document.querySelector('#demo-card .logo');
            return {
                background: style('#demo-card', 'backgroundImage') + ' ' + style('#demo-card', 'backgroundColor'),
                title: style('#demo-card h1', 'color'),
                text: style('#demo-card p', 'color'),
                kicker: style('#demo-card .kicker', 'color'),
                logo: logo && logo.src,
            };
        }"""
    )


def test_card_defaults_to_the_built_in_gradient(chromium):
    page = chromium.new_page()
    card = _card(page, {})
    page.close()

    assert "linear-gradient" in card["background"]
    assert "rgb(30, 58, 138)" in card["background"]  # #1e3a8a
    assert card["title"] == "rgb(248, 250, 252)"
    assert card["kicker"] == "rgb(147, 197, 253)"
    assert card["logo"] is None


def test_card_takes_the_brand(chromium, tmp_path):
    logo = tmp_path / "logo.svg"
    logo.write_text("<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>")
    brand = Brand(logo=logo, background=("#ffffff",), text="#000000", accent="rgb(200 0 0)").overlay()

    page = chromium.new_page()
    card = _card(page, brand)
    page.close()

    assert card["background"] == "none rgb(255, 255, 255)"
    assert card["title"] == "rgb(0, 0, 0)"
    assert card["text"] in ("rgba(0, 0, 0, 0.8)", "color(srgb 0 0 0 / 0.8)")
    assert card["kicker"] == "rgb(200, 0, 0)"
    assert card["logo"].startswith("data:image/svg+xml;base64,")


def test_instant_card_skips_the_fade_in(chromium):
    page = chromium.new_page()
    page.set_content("<body></body>")
    page.add_script_tag(content=OVERLAY)

    opacity = page.evaluate(
        """() => {
            window.__demo.card('', 'Title', '', true);
            return getComputedStyle(document.getElementById('demo-card')).opacity;
        }"""
    )
    page.close()

    assert opacity == "1"
