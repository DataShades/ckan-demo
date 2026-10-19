from __future__ import annotations

import itertools
import math

import pytest

from ckan_demo import director as director_module
from ckan_demo.director import Cue, Director, Options, key_caps, move_duration, pointer_path, reading_time


class FakePage:
    def __init__(self, clock):
        self.clock = clock
        self.waits: list[float] = []
        self.captions: list[str | None] = []
        self.positions: list[str] = []
        self.avoided: list[dict] = []
        self.cards: list[list[str] | None] = []
        self.badges: list[list] = []
        self.spotlights: list[list | None] = []
        self.pressed: list[str] = []
        self.moves: list[tuple[float, float]] = []
        self.syncs: list[bool] = []
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
        elif "spotlight" in script:
            self.spotlights.append(arg)
        elif "keys" in script:
            self.badges.append(arg)
        elif "avoid" in script:
            self.avoided.append(arg)
        elif "card" in script:
            self.cards.append(arg)
        elif "sync" in script:
            self.syncs.append("true" in script)

    def on(self, event, handler):
        self.handlers = {**getattr(self, "handlers", {}), event: handler}

    def move(self, x, y, steps=1):
        self.moves.append((x, y))

    def press(self, key):
        self.pressed.append(key)

    def goto(self, url, wait_until=None):
        self.clock.now += 1.5  # loading


# Lead-in after the first goto: the fake page's 1.5 s load, then the sync marker.
LOADED = 1.5 + Director.SYNC_SECONDS

BOX = {"x": 100, "y": 1000, "width": 80, "height": 30}


class FakeLocator:
    def __init__(self, scrolled=0):
        self.scrolled = scrolled  # what the page's reveal() reports
        self.reveals: list = []

    def wait_for(self, state):
        pass

    def evaluate(self, script, arg):
        self.reveals.append(arg)
        return self.scrolled

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

    assert page.cards == [["CKAN", "Find open data", "", False]]  # no pause hides it
    d.caption("Start with a search")
    assert page.cards == [["CKAN", "Find open data", "", False], None]
    assert page.waits == [3, 1, 0.5]  # hold, pause, fade out


def test_card_after_the_first_page_load_opens_the_clip(clock):
    d = _director(clock)
    page = d._page

    d.goto("/")
    assert d.lead_in == pytest.approx(LOADED)
    d.card("", "Find open data", hold=3)

    assert page.cards == [["", "Find open data", "", True]]  # no fade-in
    assert page.waits == [Director.SYNC_SECONDS, Director.CARD_MARGIN, 3]
    assert d.lead_in == pytest.approx(LOADED + Director.CARD_MARGIN)  # the page is cut


@pytest.mark.parametrize("before", ["caption", "page", "second card"])
def test_card_after_anything_else_fades_in(clock, before):
    d = _director(clock)
    d.goto("/")
    if before == "caption":
        d.caption("Hi")
    elif before == "page":
        d.page  # noqa: B018
    else:
        d.card("", "First", hold=0)

    d.card("", "Find open data", hold=0)

    assert d._page.cards[-1] == ["", "Find open data", "", False]
    assert d.lead_in == pytest.approx(LOADED + (Director.CARD_MARGIN if before == "second card" else 0))


def test_using_the_page_hides_the_card_once(clock):
    d = _director(clock)
    page = d._page
    d.card("", "The end")

    assert d.page is page
    d.page  # noqa: B018

    assert page.cards == [["", "The end", "", False], None]


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


def test_spotlight_dims_around_the_element_then_lifts(clock):
    d = _director(clock, speed=2)

    d.spotlight(FakeLocator(), hold=3, padding=12)

    assert d._page.spotlights == [[BOX, 12], None]
    assert d._page.waits == [1.5, 0.2]  # the hold, then the fade-out


def test_spotlight_hides_a_card_first(clock):
    d = _director(clock)
    d.card("", "Title", hold=0)

    d.spotlight(FakeLocator())

    assert d._page.cards[-1] is None


def test_pointer_path_ends_on_target_and_eases_in_and_out():
    path = pointer_path((0, 0), (1000, 0), 30)

    assert len(path) == 30
    assert path[-1] == pytest.approx((1000, 0))
    xs = [0] + [x for x, _ in path]
    steps = [b - a for a, b in itertools.pairwise(xs)]
    assert all(step > 0 for step in steps)
    assert steps[0] < steps[15] / 5 and steps[-1] < steps[15] / 5  # slow at both ends


def test_pointer_path_bows_a_little_to_one_side():
    path = pointer_path((0, 0), (1000, 0), 30)
    off_line = max(abs(y) for _, y in path)

    assert 10 < off_line <= 60
    assert path == pointer_path((0, 0), (1000, 0), 30)  # the same every time


def test_pointer_path_short_and_zero_moves():
    assert all(point == pytest.approx((5, 5)) for point in pointer_path((5, 5), (5, 5), 3))
    assert max(abs(y - 5) for _, y in pointer_path((5, 5), (25, 5), 10)) < 3


def test_long_moves_take_longer_but_are_faster_per_pixel():
    assert move_duration(0) == pytest.approx(0.2)
    assert move_duration(100) < move_duration(1000) < 1
    assert move_duration(1000) / 1000 < move_duration(100) / 100


def test_point_moves_in_real_time_and_follows_speed(clock):
    d = _director(clock, speed=2)
    start = (d.x, d.y)

    d.point(FakeLocator())

    target = (BOX["x"] + BOX["width"] / 2, BOX["y"] + BOX["height"] / 2)
    assert d._page.moves[-1] == pytest.approx(target)
    assert len(d._page.moves) > 10
    moving = sum(d._page.waits[:-1])  # the last wait is the pause after
    assert moving == pytest.approx(move_duration(math.dist(start, target)) / 2)
    assert (d.x, d.y) == target


def test_point_scrolls_smoothly_at_the_runs_speed(clock):
    d = _director(clock, speed=2)
    locator = FakeLocator(scrolled=800)

    d.point(locator)

    assert locator.reveals == [2]
    assert d._page.waits[0] == pytest.approx(0.075)  # settling after the scroll


def test_no_settling_pause_when_nothing_scrolled(clock):
    d = _director(clock, speed=2)

    d.point(FakeLocator())

    assert d._page.waits[0] != pytest.approx(0.075)


def test_captions_become_cues_timed_from_the_scene_start(clock):
    d = _director(clock)
    clock.now += 2
    d.caption("Start with a search", hold=1)
    d.pause(3)
    d.caption("Filter it", hold=1)
    d.caption(None)

    # Hiding "Filter it" waits until it's been up its 1.8 s reading time.
    assert d.cues == [Cue(2.0, 6.0, "Start with a search"), Cue(6.0, pytest.approx(7.8), "Filter it")]


def test_cues_are_recorded_without_captions_too(clock):
    d = _director(clock, captions=False)
    d.caption("Start with a search")
    d.end_cue()

    assert d.page.captions == []
    assert [cue.text for cue in d.cues] == ["Start with a search"]


def test_a_card_ends_the_cue_it_covers(clock):
    d = _director(clock)
    d.caption("Bye", hold=2)
    d.card("", "The end", hold=3)
    d.end_cue()  # the scene ends: nothing left open

    assert d.cues == [Cue(0.0, 2.0, "Bye")]


def test_end_cue_without_a_caption_does_nothing(clock):
    d = _director(clock)
    d.end_cue()
    d.caption("Once")
    d.end_cue()
    d.end_cue()

    assert len(d.cues) == 1


def test_a_page_load_ends_the_cue_as_it_wipes_the_caption(clock):
    d = _director(clock)
    d.caption("Start with a search")
    clock.now += 1.2
    d._page.handlers["domcontentloaded"](d._page)  # the click opened a new page
    clock.now += 5
    d.caption("Here's what matches")

    assert d.cues[0] == Cue(0.0, pytest.approx(1.2), "Start with a search")
    assert [cue.text for cue in d.cues] == ["Start with a search"]  # the next one is still up


def test_the_first_page_load_flashes_the_sync_marker_inside_the_lead_in(clock):
    d = _director(clock)
    d.goto("/")
    d.goto("/next")

    assert d.sync_at == pytest.approx(1.5)  # right after loading
    assert d.lead_in == pytest.approx(d.sync_at + Director.SYNC_SECONDS)  # gone before the cut ends
    assert d._page.syncs == [True, False]  # once per scene
