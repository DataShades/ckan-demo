"""Records each scene in its own browser context and clip."""

from __future__ import annotations

import json
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
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


def overlay_script(brand: dict[str, str]) -> str:
    """The overlay, with the title card branding it reads when mounting."""
    return f"window.__demoBrand = {json.dumps(brand)};\n{OVERLAY}"


def _prepare_context(context: BrowserContext, options: Options) -> None:
    """Add the overlay and hide the Flask debug toolbar."""
    context.add_init_script(overlay_script(options.brand))
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
            f"could not log in as {user.name!r}. Record with an API token or --ckan-ini so the demo users are created."
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
    jobs: int = 1,
    on_scene: Callable[[str], object] = print,
) -> list[Clip]:
    """Record ``scenes`` to ``<output>/<scene>.webm``, ``jobs`` at a time."""
    options.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not headed)
            try:
                states = {
                    key: _login(browser, options, scenario.users[key], tmp / f"{key}.json")
                    for key in {scene.user for scene in scenes if scene.user}
                }
                if jobs <= 1:
                    clips: list[Clip] = []
                    for scene in scenes:
                        on_scene(f"Recording {scene.name}…")
                        try:
                            clip = _record_scene(
                                browser, options, scene, states.get(scene.user or ""), tmp / scene.name
                            )
                        except Exception as error:
                            raise RecordingError(scene.name, error, clips) from error
                        clips.append(_keep(clip, options, scene))
                    return clips
            finally:
                browser.close()

        return _record_in_parallel(options, scenes, states, tmp, headed=headed, jobs=jobs, on_scene=on_scene)


def _keep(clip: Clip, options: Options, scene: Scene) -> Clip:
    target = options.output / f"{scene.name}.webm"
    shutil.move(clip.path, target)
    return Clip(target, clip.lead_in)


def _record_in_parallel(
    options: Options,
    scenes: list[Scene],
    states: dict[str, Path],
    tmp: Path,
    *,
    headed: bool,
    jobs: int,
    on_scene: Callable[[str], object],
) -> list[Clip]:
    """Each worker thread gets its own Playwright and browser; the sync API
    can't be shared between threads."""

    def work(scene: Scene) -> Clip:
        on_scene(f"Recording {scene.name}…")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not headed)
            try:
                return _record_scene(browser, options, scene, states.get(scene.user or ""), tmp / scene.name)
            finally:
                browser.close()

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(work, scene) for scene in scenes]
        clips: list[Clip] = []
        for scene, future in zip(scenes, futures, strict=True):
            try:
                clips.append(_keep(future.result(), options, scene))
            except Exception as error:
                for pending in futures:
                    pending.cancel()
                raise RecordingError(scene.name, error, clips) from error
    return clips
