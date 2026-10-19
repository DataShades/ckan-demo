"""Records each scene in its own browser context and clip."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import Browser, BrowserContext, sync_playwright

from ckan_demo.director import Director, Options

if TYPE_CHECKING:
    from collections.abc import Callable

    from ckan_demo.scenario import Scenario, Scene, User

OVERLAY = files("ckan_demo").joinpath("overlay.js").read_text()


@dataclass(frozen=True)
class Clip:
    path: Path
    lead_in: float  # loading time at the start, cut when joining


class RecordingError(Exception):
    """A scene failed; ``clips`` are the ones recorded before it."""

    def __init__(self, scene: str, error: BaseException, clips: list[Clip]) -> None:
        super().__init__(f"scene {scene!r} failed: {error}")
        self.scene = scene
        self.clips = clips


def _prepare_context(context: BrowserContext, options: Options) -> None:
    """Add the overlay and hide the Flask debug toolbar."""
    context.add_init_script(OVERLAY)
    context.add_cookies([{"name": "fldt", "value": "hide", "url": options.base_url}])


def _login(browser: Browser, options: Options, user: User, path: Path) -> Path:
    """Log in once, off camera, and save the session."""
    context = browser.new_context(base_url=options.base_url)
    _prepare_context(context, options)
    page = context.new_page()
    page.goto("/user/login")
    page.locator("#field-login").fill(user.name)
    page.locator("#field-password").fill(user.password)
    page.locator("form").filter(has=page.locator("#field-password")).locator("button[type=submit]").click()
    page.wait_for_load_state("networkidle")
    if "/user/login" in page.url:
        context.close()
        raise RuntimeError(
            f"could not log in as {user.name!r}. Run `ckan-demo setup` (with an API token) to create the demo users."
        )
    context.storage_state(path=str(path))
    context.close()
    return path


def _record_scene(browser: Browser, options: Options, scene: Scene, state: Path | None, video_dir: Path) -> Clip:
    size = {"width": options.width, "height": options.height}
    context = browser.new_context(
        base_url=options.base_url,
        viewport=size,
        record_video_dir=str(video_dir),
        record_video_size=size,
        storage_state=str(state) if state else None,
    )
    _prepare_context(context, options)

    page = context.new_page()
    director = Director(page, options)
    try:
        scene.play(director)
        director.wait_for_reading()  # let a final caption be read
    finally:
        context.close()  # writes the video

    if page.video is None:  # pragma: no cover
        raise RuntimeError("Playwright did not record a video")
    return Clip(Path(page.video.path()), director.lead_in)


def record(
    scenario: Scenario,
    options: Options,
    scenes: list[Scene],
    *,
    headed: bool = False,
    on_scene: Callable[[str], object] = print,
) -> list[Clip]:
    """Record ``scenes`` to ``<output>/<scene>.webm``."""
    options.output.mkdir(parents=True, exist_ok=True)
    clips: list[Clip] = []

    with sync_playwright() as playwright, tempfile.TemporaryDirectory() as tmp:
        browser = playwright.chromium.launch(headless=not headed)
        try:
            states = {
                key: _login(browser, options, scenario.users[key], Path(tmp) / f"{key}.json")
                for key in {scene.user for scene in scenes if scene.user}
            }
            for scene in scenes:
                on_scene(f"Recording {scene.name}…")
                try:
                    clip = _record_scene(browser, options, scene, states.get(scene.user or ""), Path(tmp) / scene.name)
                except Exception as error:
                    raise RecordingError(scene.name, error, clips) from error
                target = options.output / f"{scene.name}.webm"
                shutil.move(clip.path, target)
                clips.append(Clip(target, clip.lead_in))
        finally:
            browser.close()

    return clips
