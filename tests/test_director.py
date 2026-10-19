from __future__ import annotations

import pytest

from ckan_demo import director as director_module
from ckan_demo.director import Director, Options, key_caps, reading_time


class FakePage:
    def __init__(self, clock):
        self.clock = clock
        self.waits: list[float] = []
        self.captions: list[str | None] = []
        self.positions: list[str] = []
        self.avoided: list[dict] = []
        self.cards: list[list[str] | None] = []
        self.badges: list[list] = []
        self.pressed: list[str] = []
        self.mouse = self
        self.keyboard = self

    def wait_for_timeout(self, ms):
        self.waits.append(ms / 1000)
        self.clock.now += ms / 1000

    def evaluate(self, script, arg=None):
        if "caption" in script:
            text, position = arg
            self.captions.append(text)
            self.positions.append(position)
        elif "keys" in script:
            self.badges.append(arg)
        elif "avoid" in script:
            self.avoided.append(arg)
        elif "card" in script:
            self.cards.append(arg)

    def move(self, x, y, steps=1):
        pass

    def press(self, key):
        self.pressed.append(key)


BOX = {"x": 100, "y": 1000, "width": 80, "height": 30}


class FakeLocator:
    def scroll_into_view_if_needed(self):
        pass

    def bounding_box(self):
        return BOX


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(director_module.time, "monotonic", fake)
    return fake


def _director(clock, **options):
    return Director(FakePage(clock), Options(base_url="http://x", **options))


def test_reading_time_grows_with_words_and_has_a_floor():
    assert reading_time("Hi") == pytest.approx(1.8)
    assert reading_time("Use the filters on the left to narrow it down") == pytest.approx(0.6 + 10 / 3)


def test_next_caption_waits_until_the_previous_one_was_read(clock):
    d = _director(clock)
    d.caption("Use the filters on the left to narrow it down")  # needs ~3.93 s
    clock.now += 1.0  # one second of clicking

    d.caption("Next")

    assert d.page.waits == [pytest.approx(reading_time("Use the filters on the left to narrow it down") - 1.0)]
    assert d.page.captions == ["Use the filters on the left to narrow it down", "Next"]


def test_no_wait_when_actions_already_took_long_enough(clock):
    d = _director(clock)
    d.caption("Start with a search")
    clock.now += 10

    d.caption(None)

    assert d.page.waits == []


def test_hold_counts_towards_reading_time(clock):
    d = _director(clock)
    d.caption("Start with a search", hold=5)

    d.caption("Next")

    assert d.page.waits == [5]  # the hold, and nothing more


def test_speed_shortens_reading_time(clock):
    d = _director(clock, speed=2)
    d.caption("Hi")

    d.caption(None)

    assert d.page.waits == [pytest.approx(reading_time("Hi") / 2)]


def test_pacing_is_the_same_without_captions(clock):
    d = _director(clock, captions=False)
    d.caption("Start with a search")

    d.caption(None)

    assert d.page.captions == []
    assert d.page.waits == [pytest.approx(reading_time("Start with a search"))]


def test_hold_read_holds_for_the_captions_reading_time(clock):
    d = _director(clock)
    text = "Use the filters on the left to narrow it down"

    d.caption(text, hold="read")

    assert d.page.waits == [pytest.approx(reading_time(text))]
    d.caption(None)  # already read: no extra wait
    assert len(d.page.waits) == 1


def test_hold_read_follows_speed(clock):
    d = _director(clock, speed=2)

    d.caption("Start with a search", hold="read")

    assert d.page.waits == [pytest.approx(reading_time("Start with a search") / 2)]


def test_hold_read_on_hiding_the_caption_does_nothing(clock):
    d = _director(clock)

    d.caption(None, hold="read")

    assert d.page.waits == []


def test_hold_rejects_other_words(clock):
    with pytest.raises(ValueError, match='"read"'):
        _director(clock).caption("Hi", hold="long")


def test_card_stays_up_until_the_next_action(clock):
    d = _director(clock)
    page = d._page

    d.card("CKAN", "Find open data", hold=3)
    d.pause(1)

    assert page.cards == [["CKAN", "Find open data", ""]]  # no pause hides it
    d.caption("Start with a search")
    assert page.cards == [["CKAN", "Find open data", ""], None]
    assert page.waits == [3, 1, 0.5]  # hold, pause, fade out


def test_using_the_page_hides_the_card_once(clock):
    d = _director(clock)
    page = d._page
    d.card("", "The end")

    assert d.page is page
    d.page  # noqa: B018

    assert page.cards == [["", "The end", ""], None]


def test_captions_default_to_the_bottom(clock):
    d = _director(clock)

    d.caption("Hi")
    d.caption("There", position="top")

    assert d.page.positions == ["bottom", "top"]


def test_caption_position_is_checked(clock):
    with pytest.raises(ValueError, match="bottom, top, auto"):
        _director(clock).caption("Hi", position="left")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("position", "captions", "avoided"),
    [("auto", True, [BOX]), ("bottom", True, []), ("top", True, []), ("auto", False, [])],
)
def test_only_auto_captions_get_out_of_the_pointers_way(clock, position, captions, avoided):
    d = _director(clock, captions=captions)
    d.caption("Assign it to yourself", position=position)

    d.point(FakeLocator())

    assert d._page.avoided == avoided


def test_no_avoiding_once_the_caption_is_hidden(clock):
    d = _director(clock)
    d.caption("Assign it to yourself", position="auto")
    d.caption(None)

    d.point(FakeLocator())

    assert d._page.avoided == []


@pytest.mark.parametrize(
    ("key", "caps"),
    [
        ("Control+Enter", ["Ctrl", "Enter"]),
        ("ControlOrMeta+a", ["Ctrl", "A"]),
        ("Shift+Tab", ["Shift", "Tab"]),
        ("Alt+ArrowDown", ["Alt", "↓"]),
        ("Escape", ["Esc"]),
        ("KeyA", ["A"]),
        ("Digit1", ["1"]),
        ("+", ["+"]),
        ("Shift++", ["Shift", "+"]),
    ],
)
def test_key_caps(key, caps):
    assert key_caps(key) == caps


def test_shortcuts_show_a_badge_before_the_press(clock):
    d = _director(clock, speed=2)

    d.press("Control+Enter")

    assert d._page.badges == [[["Ctrl", "Enter"], 900]]  # 1.8 s at --speed 2
    assert d._page.pressed == ["Control+Enter"]
    assert d._page.waits == [0.25, 0.15]  # the badge, then the usual pause


@pytest.mark.parametrize(
    ("key", "badge", "shown"), [("Enter", None, False), ("Enter", True, True), ("Control+a", False, False)]
)
def test_badge_can_be_forced_on_or_off(clock, key, badge, shown):
    d = _director(clock)

    d.press(key, badge=badge)

    assert bool(d._page.badges) == shown
    assert d._page.pressed == [key]


def test_badges_show_without_captions_too(clock):
    d = _director(clock, captions=False)

    d.press("Control+Enter")

    assert d._page.badges
