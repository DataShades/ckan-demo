from __future__ import annotations

import pytest

from ckan_demo import director as director_module
from ckan_demo.director import Director, Options, reading_time


class FakePage:
    def __init__(self, clock):
        self.clock = clock
        self.waits: list[float] = []
        self.captions: list[str | None] = []

    def wait_for_timeout(self, ms):
        self.waits.append(ms / 1000)
        self.clock.now += ms / 1000

    def evaluate(self, script, arg=None):
        if "caption" in script:
            self.captions.append(arg)


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
