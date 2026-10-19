"""The Director: drives one page the way a person would, on camera.

Playwright's video has no mouse pointer, and scripted clicks are instant, so
every helper glides a drawn pointer to its target first, types at a human
pace and leaves time to read. Use ``d.page`` for anything else Playwright
can do.
"""

from __future__ import annotations

import contextlib
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Locator, Page


# Comfortable on-screen reading: about 180 words a minute, plus a moment to
# notice the caption, and never less than a couple of seconds.
_READING_BASE = 0.6
_READING_PER_WORD = 60 / 180
_READING_MIN = 1.8


def reading_time(text: str) -> float:
    """Seconds a caption needs on screen, at ``--speed 1``."""
    return max(_READING_MIN, _READING_BASE + len(text.split()) * _READING_PER_WORD)


@dataclass(frozen=True)
class Options:
    """How a run looks; shared by every scene."""

    base_url: str
    width: int = 1920
    height: int = 1080
    captions: bool = True
    speed: float = 1.0
    output: Path = Path("demo-output")
    typing_delay_ms: float = 28


class Director:
    """Helpers for one scene. Times are in seconds at ``--speed 1``."""

    def __init__(self, page: Page, options: Options) -> None:
        self.page = page
        self.options = options
        self.x = options.width / 2
        self.y = options.height / 2
        self.started = time.monotonic()
        # Seconds of video before the first page finished loading; the join
        # cuts them so a clip doesn't open on a blank page.
        self.lead_in = 0.0
        # The caption on screen and when it appeared, so it isn't replaced
        # before it could be read.
        self._caption: str | None = None
        self._caption_shown_at = 0.0

    # ── Pacing and narration ────────────────────────────────────────────────

    def pause(self, seconds: float) -> None:
        """Hold still, so viewers can read what just happened."""
        self.page.wait_for_timeout(seconds * 1000 / self.options.speed)

    def caption(self, text: str | None, hold: float | Literal["read"] = 0) -> None:
        """Show a caption at the bottom (``None`` hides it), then hold.

        ``hold`` keeps the page still for that many seconds; ``"read"`` holds
        for the caption's own reading time (see :func:`reading_time`), so the
        viewer reads it before the next action starts, however the wording
        changes.

        Either way, the previous caption is first left up until it could be
        read; time spent on actions since it appeared counts. The pacing is
        the same with ``--no-captions``, so a voice-over has the same room.
        """
        if isinstance(hold, str) and hold != "read":
            raise ValueError(f'hold must be a number of seconds or "read", not {hold!r}')

        self.wait_for_reading()
        if self.options.captions:
            self.page.evaluate("text => window.__demo.caption(text)", text)
        self._caption = text
        self._caption_shown_at = time.monotonic()

        if hold == "read":
            hold = reading_time(text) if text else 0
        if hold:
            self.pause(hold)

    def wait_for_reading(self) -> None:
        """Hold until the caption on screen has been up for its reading time."""
        if not self._caption:
            return
        needed = reading_time(self._caption) / self.options.speed
        remaining = needed - (time.monotonic() - self._caption_shown_at)
        if remaining > 0:
            self.page.wait_for_timeout(remaining * 1000)

    def card(self, kicker: str, title: str, text: str = "", hold: float = 3.0) -> None:
        """Cover the page with a title card for ``hold`` seconds."""
        self.wait_for_reading()
        self.page.evaluate("([k, t, x]) => window.__demo.card(k, t, x)", [kicker, title, text])
        self.pause(hold)
        self.page.evaluate("() => window.__demo.card()")
        self.pause(0.5)

    # ── Navigation ──────────────────────────────────────────────────────────

    def goto(self, path: str) -> None:
        """Open a portal page (path or absolute URL) and wait until it settles."""
        url = path if "://" in path else self.options.base_url + path
        self.page.goto(url, wait_until="networkidle")
        self.page.mouse.move(self.x, self.y)
        if not self.lead_in:
            self.lead_in = time.monotonic() - self.started

    @contextlib.contextmanager
    def navigates(self) -> Iterator[None]:
        """Wrap an action that loads a new page; waits for it to settle."""
        with self.page.expect_navigation():
            yield
        self.page.wait_for_load_state("networkidle")

    # ── Pointer and keyboard ────────────────────────────────────────────────

    def point(self, locator: Locator) -> None:
        """Glide the pointer to the middle of ``locator``."""
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if box is None:
            raise AssertionError(f"{locator} is not visible")
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        steps = max(12, min(45, int(math.dist((self.x, self.y), (x, y)) / 14)))
        self.page.mouse.move(x, y, steps=steps)
        self.x, self.y = x, y
        self.pause(0.25)

    def click(self, locator: Locator) -> None:
        self.point(locator)
        locator.click()
        self.pause(0.4)

    def type(self, locator: Locator, text: str, *, clear: bool = False) -> None:
        """Click into a field and type ``text`` key by key."""
        self.click(locator)
        if clear:
            locator.press("ControlOrMeta+A")
            locator.press("Delete")
        locator.press_sequentially(text, delay=self.options.typing_delay_ms / self.options.speed)
        self.pause(0.4)

    def select(self, locator: Locator, *, value: str | None = None, label: str | None = None) -> None:
        """Choose an option in a native ``<select>``.

        The browser's own dropdown isn't captured on video, so point at the
        field and change it; the new value shows in the field.
        """
        self.point(locator)
        if label is not None:
            locator.select_option(label=label)
        else:
            locator.select_option(value)
        self.pause(0.6)

    def press(self, key: str) -> None:
        self.page.keyboard.press(key)
        self.pause(0.3)

    # ── Stills ──────────────────────────────────────────────────────────────

    def screenshot(self, name: str, locator: Locator | None = None) -> Path:
        """Save a PNG next to the video (for READMEs and docs), without the
        pointer or caption."""
        path = self.options.output / "screenshots" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.evaluate("() => document.documentElement.classList.add('demo-still')")
        try:
            (locator or self.page).screenshot(path=str(path), animations="disabled")
        finally:
            self.page.evaluate("() => document.documentElement.classList.remove('demo-still')")
        return path
