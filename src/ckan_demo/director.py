"""Director: scene helpers that move a visible pointer, type at a human pace
and pause to read. ``d.page`` is the Playwright page for anything else.
"""

from __future__ import annotations

import contextlib
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from playwright.sync_api import Error as PlaywrightError

from ckan_demo import extensions

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from playwright.sync_api import FloatRect, FrameLocator, Locator, Page

    from ckan_demo.extensions import Extension


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
class Cue:
    """A caption's text and when it was up, in seconds since the scene began
    (the clock ``lead_in`` uses)."""

    start: float
    end: float
    text: str


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
    brand: dict[str, str] = field(default_factory=dict)


# Run in a popup framed by Director.open_popup: tells the page its size,
# which the page can't read from another origin, now and when it changes.
POPUP_SIZE = """body => {
    const post = () => {
        const rect = body.getBoundingClientRect();
        const style = getComputedStyle(body);
        const width = rect.width + parseFloat(style.marginLeft) + parseFloat(style.marginRight);
        const height = rect.height + parseFloat(style.marginTop) + parseFloat(style.marginBottom);
        parent.postMessage({ demoPopupSize: [Math.ceil(width), Math.ceil(height)] }, "*");
    };
    new ResizeObserver(post).observe(body);
    post();
}"""


class Director:
    """Helpers for one scene. Times are seconds at ``--speed 1``."""

    # Pointer positions per second while it moves.
    FPS = 60
    # Seconds an opening card is up before the clip starts: the video lags
    # the page a little.
    CARD_MARGIN = 0.2
    # How long the sync marker stays up: several frames at the video's 25 fps.
    SYNC_SECONDS = 0.3

    def __init__(self, page: Page, options: Options, extensions: Sequence[Extension] = ()) -> None:
        self._page = page
        self.options = options
        self._extensions = list(extensions)
        self._held: list[str] = []  # keys down in hold()
        self.x = options.width / 2
        self.y = options.height / 2
        self.started = time.monotonic()
        # Loading time before the first page; cut when joining.
        self.lead_in = 0.0
        # When the sync marker showed, for lining the video up with this clock.
        self.sync_at: float | None = None
        # Current caption and when it appeared.
        self._caption: str | None = None
        self._caption_position: CaptionPosition = "bottom"
        self._caption_shown_at = 0.0
        self._card_shown = False
        # Nothing has happened since the first page loaded.
        self._opening = False
        # Captions shown so far, for subtitles; recorded with --no-captions too.
        self.cues: list[Cue] = []
        self._open_cue: tuple[float, str] | None = None  # start and text of the one on screen
        # A new document starts without the overlay's caption, so its cue ends
        # there. History updates (htmx boosts) keep the page and the caption.
        page.on("domcontentloaded", lambda _: self.end_cue())

    @property
    def page(self) -> Page:
        """The Playwright page. Using it hides a title card that's still up."""
        self._hide_card()
        return self._page

    def extension(self, name: str | None = None) -> Extension:
        """A browser extension the scenario loads: by its manifest name or
        folder, or the only one. See :class:`~ckan_demo.extensions.Extension`."""
        return extensions.find(self._extensions, name)

    def open_popup(self, name: str | None = None, *, height: int | None = None) -> FrameLocator:
        """Open an extension's toolbar popup, framed at the top right of the
        page as the browser shows it (the browser's own is out of the video).
        Returns its frame, to point at and click what's in it. It fits its
        content as that changes; ``height`` fixes it instead."""
        extension = self.extension(name)
        self._hide_card()
        self._page.evaluate("([url, height]) => window.__demo.popup(url, height)", [extension.popup_url, height])
        frame = self._page.frame_locator("#demo-popup")
        frame.locator("body").evaluate(POPUP_SIZE)
        self._page.wait_for_function("() => document.getElementById('demo-popup')?.classList.contains('shown')")
        self.pause(0.6)
        return frame

    def close_popup(self) -> None:
        """Close the popup :meth:`open_popup` opened."""
        self._page.evaluate("() => window.__demo.popup(null)")
        self.pause(0.4)

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
        self.end_cue()
        self._caption = text
        self._caption_position = position
        self._caption_shown_at = time.monotonic()
        if text:
            self._open_cue = (self._caption_shown_at - self.started, text)

        if hold == "read":
            hold = reading_time(text) if text else 0
        if hold:
            self.pause(hold)

    def end_cue(self) -> None:
        """Close the current caption's subtitle: it was replaced, hidden,
        covered by a card, or the scene ended."""
        if self._open_cue:
            start, text = self._open_cue
            self.cues.append(Cue(start, time.monotonic() - self.started, text))
            self._open_cue = None

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
        that ends the scene ends the clip. One right after the scene's first
        ``goto`` opens the clip: it's up from the first frame.
        """
        self.wait_for_reading()
        self.end_cue()  # the card covers the caption
        # Straight after the first page load, the card appears at once and
        # the clip starts on it, so the page doesn't show before it.
        opening, self._opening = self._opening, False
        self._page.evaluate(
            "([k, t, x, instant]) => window.__demo.card(k, t, x, instant)", [kicker, title, text, opening]
        )
        self._card_shown = True
        if opening:
            self._page.wait_for_timeout(self.CARD_MARGIN * 1000)
            self.lead_in = time.monotonic() - self.started
        self.pause(hold)

    def _hide_card(self) -> None:
        """Fade out the title card, if one is up. Every action starts here."""
        self._opening = False
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
            self._sync()
            self.lead_in = time.monotonic() - self.started
            self._opening = True

    def _sync(self) -> None:
        """Flash the sync marker, noting when it showed. It's over before the
        lead-in ends, so it's cut with it."""
        self._page.evaluate("() => window.__demo.sync(true)")
        self.sync_at = time.monotonic() - self.started
        self._page.wait_for_timeout(self.SYNC_SECONDS * 1000)  # a few video frames
        self._page.evaluate("() => window.__demo.sync(false)")

    @contextlib.contextmanager
    def navigates(self) -> Iterator[None]:
        """Wrap an action that loads a new page."""
        with self._page.expect_navigation():
            yield
        self._page.wait_for_load_state("networkidle")

    # ── Pointer and keyboard ────────────────────────────────────────────────

    def point(self, target: Locator | FloatRect) -> None:
        """Move the pointer to the middle of ``target``: an element, or a box
        in viewport pixels (``{"x", "y", "width", "height"}``) for what
        locators can't reach, like an extension's closed shadow root."""
        self._hide_card()
        box = target if isinstance(target, dict) else self._reveal(target)
        if self._caption and self._caption_position == "auto" and self.options.captions:
            self._page.evaluate("box => window.__demo.avoid(box)", box)
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self._move(x, y)
        self.pause(0.25)

    def _reveal(self, locator: Locator) -> FloatRect:
        """Scroll ``locator`` into view smoothly and return its box."""
        locator.wait_for(state="visible")
        if locator.evaluate("(el, speed) => window.__demo?.reveal(el, speed)", self.options.speed):
            self.pause(0.15)  # settle before the pointer moves
        # Instant fallback for scrolling boxes inside the page, like dialogs,
        # and for frames, which have no overlay.
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if box is None:
            raise AssertionError(f"{locator} is not visible")
        return box

    def _move(self, x: float, y: float) -> None:
        """Move the pointer to ``x, y`` along :func:`pointer_path`, in real time."""
        duration = move_duration(math.dist((self.x, self.y), (x, y))) / self.options.speed
        frames = max(2, round(duration * self.FPS))
        # The overlay follows mouse events, which a frame on the page takes
        # while the pointer is over it.
        follow = len(self._page.frames) > 1
        start = time.monotonic()
        for i, (px, py) in enumerate(pointer_path((self.x, self.y), (x, y), frames), 1):
            self._page.mouse.move(px, py)
            if follow:
                self._page.evaluate("([x, y]) => window.__demo.follow(x, y)", [px, py])
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

    def zoom(
        self,
        area: Locator | tuple[float, float, float, float],
        hold: float = 2.0,
        *,
        zoom_in: float = 0.8,
        zoom_out: float = 0.6,
        scale: float | None = None,
        padding: int = 24,
    ) -> None:
        """Zoom into ``area`` over ``zoom_in`` seconds, hold for ``hold``,
        then zoom back out over ``zoom_out``.

        ``area`` is an element, or ``(x, y, width, height)`` in viewport
        pixels. It fills as much of the frame as fits with ``padding`` around
        it, up to 3 times, or ``scale`` sets the factor. The page is re-rendered
        larger, so text stays sharp. The pointer moves with the page; the
        caption keeps its size, so one shown before reads alongside.
        """
        if scale is not None and scale < 1:
            raise ValueError(f"scale must be 1 or more, not {scale!r}")
        if min(hold, zoom_in, zoom_out) < 0:
            raise ValueError("hold, zoom_in and zoom_out are seconds, 0 or more")
        self._hide_card()
        if isinstance(area, tuple):
            x, y, width, height = area
            box = {"x": x, "y": y, "width": width, "height": height}
        else:
            box = self._reveal(area)
        options = {"scale": scale, "padding": padding}
        speed = self.options.speed
        self._page.evaluate(
            "([box, ms, options]) => window.__demo.zoom(box, ms, options)", [box, zoom_in * 1000 / speed, options]
        )
        self.pause(hold)
        self._page.evaluate("ms => window.__demo.zoom(null, ms)", zoom_out * 1000 / speed)

    def click(self, target: Locator | FloatRect) -> None:
        """Point at ``target`` (see :meth:`point`) and click it. Keys held
        with :meth:`hold` apply, e.g. Shift+click."""
        self.point(target)
        self._tap(down=True)
        if isinstance(target, dict):
            self._page.mouse.click(self.x, self.y)
        else:
            target.click()
        self._tap(down=False)
        self.pause(0.4)

    def _tap(self, *, down: bool) -> None:
        """Show a click the overlay can't see: one a frame on the page gets."""
        if len(self._page.frames) == 1:
            return
        # The click may have started loading another page.
        with contextlib.suppress(PlaywrightError):
            self._page.evaluate("([x, y, down]) => window.__demo.tap(x, y, down)", [self.x, self.y, down])

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

    @contextlib.contextmanager
    def hold(self, key: str, *, badge: bool = True) -> Iterator[None]:
        """Hold ``key`` down (``"Shift"``) while the block runs, with its key
        badge up the whole time. Holds can nest: ``Shift`` + ``Alt``."""
        self._hide_card()
        self._held.append(key)
        if badge:
            self._show_held()
            self.pause(0.4)
        self._page.keyboard.down(key)
        try:
            yield
        finally:
            self._page.keyboard.up(key)
            self._held.remove(key)
            if badge:
                self._show_held()
        self.pause(0.3)

    def _show_held(self) -> None:
        caps = [cap for key in self._held for cap in key_caps(key)]
        self._page.evaluate("caps => window.__demo.keys(caps)", caps)

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
