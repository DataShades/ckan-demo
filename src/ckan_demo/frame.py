"""A browser window around each scene: rounded, with a soft shadow, on a
coloured background.

Scenes are recorded at the window's content size, so nothing is scaled. The
window is one transparent-holed PNG, drawn by Chromium so CSS colours and
gradients look as they do on the title cards, and laid over every scene
when the clips are joined.
"""

from __future__ import annotations

import base64
import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_BACKGROUND = ("#1e3a8a", "#7c3aed")
DEFAULT_PADDING = 0.06  # of the video height, on every side
MAX_PADDING = 0.2


def _even(value: float) -> int:
    """H.264's 4:2:0 chroma needs even sizes and offsets."""
    return max(2, round(value / 2) * 2)


@dataclass(frozen=True)
class Layout:
    """Where the window and the recorded page sit in the video, in pixels."""

    width: int  # the video
    height: int
    x: int  # the window's top left
    y: int
    bar: int  # title bar height, above the page
    radius: int
    content_width: int  # the page: what the browser records
    content_height: int

    @classmethod
    def fit(cls, width: int, height: int, padding: float = DEFAULT_PADDING) -> Layout:
        """The window centred in a ``width`` by ``height`` video."""
        if not 0 <= padding <= MAX_PADDING:
            raise ValueError(f"frame padding must be between 0 and {MAX_PADDING:g}, not {padding:g}")
        margin = _even(height * padding) if padding else 0
        bar = _even(height * 0.036)
        content_width, content_height = width - 2 * margin, height - 2 * margin - bar
        if content_width < 2 or content_height < 2:  # noqa: PLR2004
            raise ValueError(f"a {width}x{height} video is too small for a frame")
        return cls(
            width=width,
            height=height,
            x=margin,
            y=margin,
            bar=bar,
            radius=max(4, round(height * 0.012)),
            content_width=content_width // 2 * 2,
            content_height=content_height // 2 * 2,
        )

    @property
    def content_x(self) -> int:
        return self.x

    @property
    def content_y(self) -> int:
        return self.y + self.bar


def _hole(layout: Layout) -> str:
    """Mask that hides everything over the page: the whole video minus the
    page area, whose bottom corners follow the window's."""
    x, y, w, h, r = layout.content_x, layout.content_y, layout.content_width, layout.content_height, layout.radius
    page = f"M{x} {y}H{x + w}V{y + h - r}A{r} {r} 0 0 1 {x + w - r} {y + h}H{x + r}A{r} {r} 0 0 1 {x} {y + h - r}Z"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" height="{layout.height}">'
        f'<path fill-rule="evenodd" d="M0 0H{layout.width}V{layout.height}H0Z{page}"/></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def page_html(layout: Layout, *, background: str, address: str = "") -> str:
    """The frame as a page; ``background`` is a CSS background."""
    hole = _hole(layout)
    scale = layout.height / 1080
    window_height = layout.bar + layout.content_height
    dot = round(12 * scale)
    pill = f'<div class="address">{html.escape(address)}</div>' if address else '<div class="address empty"></div>'
    return f"""<!doctype html>
<style>
  html, body {{ margin: 0; width: {layout.width}px; height: {layout.height}px; overflow: hidden;
                background: transparent; }}
  .scene {{ position: absolute; inset: 0; background: {background};
            -webkit-mask: url("{hole}") no-repeat; mask: url("{hole}") no-repeat; }}
  .window {{ position: absolute; left: {layout.x}px; top: {layout.y}px;
             width: {layout.content_width}px; height: {window_height}px;
             border-radius: {layout.radius}px; background: #ececef;
             box-shadow: 0 0 0 1px rgb(0 0 0 / 0.08),
                         0 {round(20 * scale)}px {round(50 * scale)}px rgb(0 0 0 / 0.35); }}
  .bar {{ position: relative; height: {layout.bar}px; box-sizing: border-box;
          display: flex; align-items: center; gap: {round(8 * scale)}px; padding: 0 {round(14 * scale)}px;
          border-bottom: 1px solid rgb(0 0 0 / 0.08); }}
  .dot {{ width: {dot}px; height: {dot}px; border-radius: 50%; }}
  .address {{ position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
              min-width: {round(layout.content_width * 0.3)}px; max-width: 60%;
              height: {round(layout.bar * 0.62)}px; line-height: {round(layout.bar * 0.62)}px;
              padding: 0 {round(14 * scale)}px; border-radius: {round(layout.bar * 0.31)}px;
              background: #fff; color: #5f6368; text-align: center; white-space: nowrap; overflow: hidden;
              font: {round(14 * scale)}px system-ui, -apple-system, "Segoe UI", sans-serif; }}
  .address.empty {{ background: rgb(255 255 255 / 0.7); }}
</style>
<div class="scene">
  <div class="window">
    <div class="bar">
      <div class="dot" style="background:#ff5f57"></div>
      <div class="dot" style="background:#febc2e"></div>
      <div class="dot" style="background:#28c840"></div>
      {pill}
    </div>
  </div>
</div>
"""


def render(layout: Layout, path: Path, *, background: str, address: str = "") -> Path:
    """Draw the frame to a PNG, transparent over the page area."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": layout.width, "height": layout.height}, device_scale_factor=1)
            page.set_content(page_html(layout, background=background, address=address))
            page.screenshot(path=str(path), omit_background=True)
        finally:
            browser.close()
    return path
