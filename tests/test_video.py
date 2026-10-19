from __future__ import annotations

from pathlib import Path

import pytest

from ckan_demo import video
from ckan_demo.recorder import Clip


def test_join_command_trims_each_lead_in_and_concatenates_in_order():
    clips = [Clip(Path("a.webm"), 0.5), Clip(Path("b.webm"), 1.234)]

    command = video.join_command(clips, Path("out.mp4"))

    assert command[command.index("-i") + 1] == "a.webm"
    graph = command[command.index("-filter_complex") + 1]
    assert "[0:v]trim=start=0.50,setpts=PTS-STARTPTS,fps=30[v0]" in graph
    assert "[1:v]trim=start=1.23,setpts=PTS-STARTPTS,fps=30[v1]" in graph
    assert graph.endswith("[v0][v1]concat=n=2:v=1:a=0[out]")
    assert command[-1] == "out.mp4"
    assert "libx264" in command


def test_gif_command_scales_and_uses_a_palette():
    command = video.gif_command(Path("in.mp4"), Path("out.gif"), width=640)

    graph = command[command.index("-filter_complex") + 1]
    assert "scale=640:-1" in graph
    assert "palettegen" in graph
    assert "paletteuse" in graph


def test_missing_ffmpeg_is_reported(monkeypatch):
    monkeypatch.setattr(video.shutil, "which", lambda name: None)

    with pytest.raises(video.FfmpegMissing):
        video.join([Clip(Path("a.webm"), 0)], Path("out.mp4"))
