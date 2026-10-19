"""Director: scene helpers that move a visible pointer, type at a human pace
and pause to read. ``d.page`` is the Playwright page for anything else.
"""

from __future__ import annotations

import contextlib
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import FloatRect, Locator, Page


def reading_time(text: str) -> float:
    """Seconds a caption needs on screen at ``--speed 1``."""
    # About 180 words a minute, plus a moment to notice the caption.
    base, per_word, minimum = 0.6, 60 / 180, 1.8
    return max(minimum, base + len(text.split()) * per_word)


_KEY_LABELS = {
    "Control": "Ctrl",
    "ControlOrMeta": "Ctrl",
    "Escape": "Esc",
    "Delete": "Del",
    "PageUp": "PgUp",
    "PageDown": "PgDn",
    "ArrowUp": "↑",
    "ArrowDown": "↓",
    "ArrowLeft": "←",
    "ArrowRight": "→",
    " ": "Space",
}


def key_caps(key: str) -> list[str]:
    """Keycap labels for a Playwright key: ``"Control+Enter"`` → ``["Ctrl", "Enter"]``."""
    parts = key.split("+")
    if key.endswith("+"):  # the + key itself: "+" or "Shift++"
        parts = [*parts[:-2], "+"]
    caps = []
    for part in parts:
        code = re.fullmatch(r"(?:Key|Digit)(\w)", part)  # KeyA, Digit1
        name = code[1] if code else part
        caps.append(_KEY_LABELS.get(name, name.upper() if len(name) == 1 else name))
    return caps


def move_duration(distance: float) -> float:
    """Seconds the pointer takes to travel ``distance`` pixels at ``--speed 1``.

    Grows with the log of the distance, like a hand (Fitts's law): long moves
    are faster per pixel than short ones.
    """
    return 0.2 + 0.1 * math.log2(1 + distance / 50)


def pointer_path(start: tuple[float, float], end: tuple[float, float], frames: int) -> list[tuple[float, float]]:
    """``frames`` points from ``start`` (excluded) to ``end``, as a hand moves.

    The path bows slightly to one side and the pointer speeds up then slows
    down (a minimum-jerk profile), instead of Playwright's straight line at
    constant speed. The same move always takes the same path.
    """
    (x0, y0), (x1, y1) = start, end
    dx, dy = x1 - x0, y1 - y0
    distance = math.hypot(dx, dy)
    # Control point: off the midpoint, at a right angle to the line. Bowing
    # by the horizontal direction looks like a wrist pivoting.
    bow = min(0.12 * distance, 60) * (1 if dx >= 0 else -1)
    cx, cy = x0 + dx / 2, y0 + dy / 2
    if distance:
        cx, cy = cx - dy / distance * bow, cy + dx / distance * bow

    points = []
    for i in range(1, frames + 1):
        t = i / frames
        t = t * t * t * (10 - 15 * t + 6 * t * t)
        u = 1 - t
        points.append((u * u * x0 + 2 * u * t * cx + t * t * x1, u * u * y0 + 2 * u * t * cy + t * t * y1))
    return points


CaptionPosition = Literal["bottom", "top", "auto"]
CAPTION_POSITIONS: tuple[CaptionPosition, ...] = ("bottom", "top", "auto")


@dataclass(frozen=True)
class Options:
    """Settings shared by every scene in a run."""

    base_url: str
    width: int = 1920
    height: int = 1080
    captions: bool = True
    speed: float = 1.0
    output: Path = Path("demo-output")
    typing_delay_ms: float = 28


class Director:
    """Helpers for one scene. Times are seconds at ``--speed 1``."""

    # Pointer positions per second while it moves.
    FPS = 60

    def __init__(self, page: Page, options: Options) -> None:
        self._page = page
        self.options = options
        self.x = options.width / 2
        self.y = options.height / 2
        self.started = time.monotonic()
        # Loading time before the first page; cut when joining.
        self.lead_in = 0.0
        # Current caption and when it appeared.
        self._caption: str | None = None
        self._caption_position: CaptionPosition = "bottom"
        self._caption_shown_at = 0.0
        self._card_shown = False

    @property
    def page(self) -> Page:
        """The Playwright page. Using it hides a title card that's still up."""
        self._hide_card()
        return self._page

    # ── Pacing and narration ────────────────────────────────────────────────

    def pause(self, seconds: float) -> None:
        """Hold still."""
        self._page.wait_for_timeout(seconds * 1000 / self.options.speed)

    def caption(
        self, text: str | None, hold: float | Literal["read"] = 0, *, position: CaptionPosition = "bottom"
    ) -> None:
        """Show a caption (``None`` hides it), then hold.

        ``hold`` is seconds, or ``"read"`` for the caption's reading time. The
        previous caption first stays up until it's been readable. Pacing is
        the same with ``--no-captions``.

        ``position`` is ``"bottom"``, ``"top"`` or ``"auto"``: at the bottom,
        moving to the top when the pointer is about to go somewhere the
        caption covers.
        """
        if isinstance(hold, str) and hold != "read":
            raise ValueError(f'hold must be a number of seconds or "read", not {hold!r}')
        if position not in CAPTION_POSITIONS:
            raise ValueError(f"position must be one of {', '.join(CAPTION_POSITIONS)}, not {position!r}")

        self._hide_card()
        self.wait_for_reading()
        if self.options.captions:
            self._page.evaluate("([text, position]) => window.__demo.caption(text, position)", [text, position])
        self._caption = text
        self._caption_position = position
        self._caption_shown_at = time.monotonic()

        if hold == "read":
            hold = reading_time(text) if text else 0
        if hold:
            self.pause(hold)

    def wait_for_reading(self) -> None:
        """Wait until the current caption has been up for its reading time."""
        if not self._caption:
            return
        needed = reading_time(self._caption) / self.options.speed
        remaining = needed - (time.monotonic() - self._caption_shown_at)
        if remaining > 0:
            self._page.wait_for_timeout(remaining * 1000)

    def card(self, kicker: str, title: str, text: str = "", hold: float = 3.0) -> None:
        """Show a full-screen title card for ``hold`` seconds.

        It stays up until the next action or use of ``d.page``, so a card
        that ends the scene ends the clip.
        """
        self.wait_for_reading()
        self._page.evaluate("([k, t, x]) => window.__demo.card(k, t, x)", [kicker, title, text])
        self._card_shown = True
        self.pause(hold)

    def _hide_card(self) -> None:
        """Fade out the title card, if one is up."""
        if not self._card_shown:
            return
        self._card_shown = False
        self._page.evaluate("() => window.__demo.card()")
        self.pause(0.5)

    # ── Navigation ──────────────────────────────────────────────────────────

    def goto(self, path: str) -> None:
        """Open a path or URL and wait for the network to go idle."""
        url = path if "://" in path else self.options.base_url + path
        self._hide_card()
        self._page.goto(url, wait_until="networkidle")
        self._page.mouse.move(self.x, self.y)
        if not self.lead_in:
            self.lead_in = time.monotonic() - self.started

    @contextlib.contextmanager
    def navigates(self) -> Iterator[None]:
        """Wrap an action that loads a new page."""
        with self._page.expect_navigation():
            yield
        self._page.wait_for_load_state("networkidle")

    # ── Pointer and keyboard ────────────────────────────────────────────────

    def point(self, locator: Locator) -> None:
        """Move the pointer to the middle of ``locator``."""
        self._hide_card()
        box = self._reveal(locator)
        if self._caption and self._caption_position == "auto" and self.options.captions:
            self._page.evaluate("box => window.__demo.avoid(box)", box)
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self._move(x, y)
        self.pause(0.25)

    def _reveal(self, locator: Locator) -> FloatRect:
        """Scroll ``locator`` into view smoothly and return its box."""
        locator.wait_for(state="visible")
        if locator.evaluate("(el, speed) => window.__demo.reveal(el, speed)", self.options.speed):
            self.pause(0.15)  # settle before the pointer moves
        # Instant fallback for scrolling boxes inside the page, like dialogs.
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if box is None:
            raise AssertionError(f"{locator} is not visible")
        return box

    def _move(self, x: float, y: float) -> None:
        """Move the pointer to ``x, y`` along :func:`pointer_path`, in real time."""
        duration = move_duration(math.dist((self.x, self.y), (x, y))) / self.options.speed
        frames = max(2, round(duration * self.FPS))
        start = time.monotonic()
        for i, (px, py) in enumerate(pointer_path((self.x, self.y), (x, y), frames), 1):
            self._page.mouse.move(px, py)
            # Against the clock, so slow mouse events don't stretch the move.
            remaining = start + duration * i / frames - time.monotonic()
            if remaining > 0:
                self._page.wait_for_timeout(remaining * 1000)
        self.x, self.y = x, y

    def spotlight(self, locator: Locator, hold: float = 2.0, *, padding: int = 8) -> None:
        """Dim everything except ``locator`` for ``hold`` seconds.

        The pointer and caption stay on top. Nothing on the page moves, so a
        caption shown before it reads alongside.
        """
        self._hide_card()
        box = self._reveal(locator)
        self._page.evaluate("([box, padding]) => window.__demo.spotlight(box, padding)", [box, padding])
        self.pause(hold)
        self._page.evaluate("() => window.__demo.spotlight(null)")
        self.pause(0.4)  # the fade-out

    def click(self, locator: Locator) -> None:
        self.point(locator)
        locator.click()
        self.pause(0.4)

    def type(self, locator: Locator, text: str, *, clear: bool = False) -> None:
        """Click a field and type ``text`` key by key."""
        self.click(locator)
        if clear:
            locator.press("ControlOrMeta+A")
            locator.press("Delete")
        locator.press_sequentially(text, delay=self.options.typing_delay_ms / self.options.speed)
        self.pause(0.4)

    def select(self, locator: Locator, *, value: str | None = None, label: str | None = None) -> None:
        """Pick an option in a native ``<select>``.

        Native dropdowns don't show in the video, so this points at the field
        and sets the value.
        """
        self.point(locator)
        if label is not None:
            locator.select_option(label=label)
        else:
            locator.select_option(value)
        self.pause(0.6)

    def press(self, key: str, *, badge: bool | None = None) -> None:
        """Press a key (``"Enter"``) or shortcut (``"Control+Enter"``).

        Shortcuts show a key badge just before they're pressed, so the viewer
        sees what was pressed; ``badge=`` turns it on or off for any key.
        """
        self._hide_card()
        caps = key_caps(key)
        if len(caps) > 1 if badge is None else badge:
            self._page.evaluate("([caps, ms]) => window.__demo.keys(caps, ms)", [caps, 1800 / self.options.speed])
            self.pause(0.5)
        self._page.keyboard.press(key)
        self.pause(0.3)

    # ── Screenshots ─────────────────────────────────────────────────────────

    def screenshot(self, name: str, locator: Locator | None = None) -> Path:
        """Save ``screenshots/<name>.png`` without the pointer, caption or card."""
        path = self.options.output / "screenshots" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._page.evaluate("() => document.documentElement.classList.add('demo-screenshot')")
        try:
            (locator or self._page).screenshot(path=str(path), animations="disabled")
        finally:
            self._page.evaluate("() => document.documentElement.classList.remove('demo-screenshot')")
        return path
