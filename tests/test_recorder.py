"""record() with fakes in place of Playwright."""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

import pytest

from ckan_demo import Scenario, recorder
from ckan_demo.director import Options
from ckan_demo.recorder import Clip, RecordingError


class FakeBrowser:
    def close(self):
        pass


@pytest.fixture
def fake_playwright(monkeypatch, tmp_path):
    """Scenes take the time in their name ("slow"/"fast") and write a fake clip."""
    threads: set[int] = set()

    @contextlib.contextmanager
    def fake_sync_playwright():
        class Chromium:
            def launch(self, headless=True):
                return FakeBrowser()

        class Playwright:
            chromium = Chromium()

        yield Playwright()

    def fake_record_scene(browser, options, scene, state, video_dir):
        threads.add(threading.get_ident())
        if "boom" in scene.name:
            raise RuntimeError("locator not found")
        time.sleep(0.2 if "slow" in scene.name else 0.01)
        video_dir.mkdir(parents=True, exist_ok=True)
        path = video_dir / "clip.webm"
        path.write_text(scene.name)
        return Clip(path, 0.1)

    monkeypatch.setattr(recorder, "sync_playwright", fake_sync_playwright)
    monkeypatch.setattr(recorder, "_record_scene", fake_record_scene)
    return threads


def _scenario(*names):
    scenario = Scenario("Demo", independent_scenes=True)
    for name in names:
        scenario.scene(name)(lambda d: None)
    return scenario


def _options(tmp_path):
    return Options(base_url="http://x", output=tmp_path / "out")


def test_parallel_clips_keep_scenario_order(fake_playwright, tmp_path):
    scenario = _scenario("1-slow", "2-fast", "3-fast")

    clips = recorder.record(scenario, _options(tmp_path), scenario.scenes, jobs=3, on_scene=lambda line: None)

    assert [clip.path.name for clip in clips] == ["1-slow.webm", "2-fast.webm", "3-fast.webm"]
    assert [clip.path.read_text() for clip in clips] == ["1-slow", "2-fast", "3-fast"]
    assert len(fake_playwright) == 3, "each scene should run in its own thread"


def test_sequential_by_default(fake_playwright, tmp_path):
    scenario = _scenario("a", "b")

    clips = recorder.record(scenario, _options(tmp_path), scenario.scenes, on_scene=lambda line: None)

    assert [clip.path.name for clip in clips] == ["a.webm", "b.webm"]
    assert len(fake_playwright) == 1


@pytest.mark.parametrize("jobs", [1, 2])
def test_a_failing_scene_is_named(fake_playwright, tmp_path, jobs):
    scenario = _scenario("a", "b-boom", "c")

    with pytest.raises(RecordingError, match="scene 'b-boom' failed: locator not found") as caught:
        recorder.record(scenario, _options(tmp_path), scenario.scenes, jobs=jobs, on_scene=lambda line: None)

    assert [clip.path.name for clip in caught.value.clips] == ["a.webm"]
    assert isinstance(caught.value.clips[0].path, Path)
