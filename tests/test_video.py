from __future__ import annotations

from pathlib import Path

import pytest

from ckan_demo import video
from ckan_demo.recorder import Clip
from ckan_demo.video import Transition

PREP = "setpts=PTS-STARTPTS,fps=30,settb=AVTB,format=yuv420p"


def _graph(command: list[str]) -> str:
    return command[command.index("-filter_complex") + 1]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("cut", Transition("cut", 0.0)),
        ("fade", Transition("fade", 0.4)),
        ("fade:0.25", Transition("fade", 0.25)),
        (" crossfade : 1 ", Transition("crossfade", 1.0)),
        ("crossfade", Transition("crossfade", 0.6)),
    ],
)
def test_transition_parse(value, expected):
    assert Transition.parse(value) == expected


@pytest.mark.parametrize("value", ["dissolve", "fade:", "fade:0", "cut:1", "fade:-1", ""])
def test_transition_parse_rejects(value):
    with pytest.raises(ValueError, match=r"transition|duration|cut"):
        Transition.parse(value)


def test_transition_str_round_trips():
    for value in ("cut", "fade:0.4", "crossfade:0.6"):
        assert str(Transition.parse(value)) == value


def test_cut_trims_lead_ins_and_concatenates_in_order():
    clips = [Clip(Path("a.webm"), 0.5), Clip(Path("b.webm"), 1.234)]

    command = video.join_command(clips, Path("out.mp4"), transition=Transition.parse("cut"))

    assert command[command.index("-i") + 1] == "a.webm"
    graph = _graph(command)
    assert f"[0:v]trim=start=0.50,{PREP}[v0]" in graph
    assert f"[1:v]trim=start=1.23,{PREP}[v1]" in graph
    assert graph.endswith("[v0][v1]concat=n=2:v=1:a=0[out]")
    assert command[-1] == "out.mp4"
    assert "libx264" in command


def test_fade_goes_through_black():
    clips = [Clip(Path("a.webm"), 0.5), Clip(Path("b.webm"), 0.0)]

    graph = _graph(video.join_command(clips, Path("o.mp4"), durations=[10.5, 6.0], transition=Transition("fade", 0.4)))

    # Clip a: 10 s after its 0.5 s lead-in, so it fades out from 9.6 s.
    assert f"[0:v]trim=start=0.50,{PREP},fade=t=in:st=0:d=0.4,fade=t=out:st=9.60:d=0.4[v0]" in graph
    assert f"[1:v]trim=start=0.00,{PREP},fade=t=in:st=0:d=0.4,fade=t=out:st=5.60:d=0.4[v1]" in graph
    assert graph.endswith("concat=n=2:v=1:a=0[out]")


def test_very_short_clips_only_fade_in():
    graph = _graph(
        video.join_command([Clip(Path("a.webm"), 0.0)], Path("o.mp4"), durations=[0.6], transition=Transition())
    )

    assert "fade=t=in" in graph
    assert "fade=t=out" not in graph


def test_crossfade_overlaps_scenes_at_the_right_offsets():
    clips = [Clip(Path(f"{name}.webm"), 0.0) for name in "abc"]

    graph = _graph(
        video.join_command(clips, Path("o.mp4"), durations=[10.0, 6.0, 8.0], transition=Transition("crossfade", 0.6))
    )

    # b starts blending 0.6 s before a ends; c 0.6 s before (10 + 6 - 0.6) ends.
    assert "[v0][v1]xfade=transition=fade:duration=0.60:offset=9.40[x1]" in graph
    assert "[x1][v2]xfade=transition=fade:duration=0.60:offset=14.80[out]" in graph
    assert "concat" not in graph
    assert "fade=t=" not in graph


def test_crossfade_shrinks_for_short_clips():
    clips = [Clip(Path("a.webm"), 0.0), Clip(Path("b.webm"), 0.0)]

    graph = _graph(
        video.join_command(clips, Path("o.mp4"), durations=[5.0, 0.8], transition=Transition("crossfade", 0.6))
    )

    assert "xfade=transition=fade:duration=0.40:offset=4.60[out]" in graph


def test_a_single_clip_has_nothing_to_crossfade():
    graph = _graph(
        video.join_command(
            [Clip(Path("a.webm"), 0.0)], Path("o.mp4"), durations=[5.0], transition=Transition("crossfade", 0.6)
        )
    )

    assert "xfade" not in graph
    assert graph.endswith("concat=n=1:v=1:a=0[out]")


def test_without_durations_scenes_are_cut():
    graph = _graph(video.join_command([Clip(Path("a.webm"), 0.0)], Path("o.mp4"), transition=Transition()))

    assert "fade" not in graph


def test_gif_command_scales_and_uses_a_palette():
    graph = _graph(video.gif_command(Path("in.mp4"), Path("out.gif"), width=640))

    assert "scale=640:-1" in graph
    assert "palettegen" in graph
    assert "paletteuse" in graph


def test_missing_ffmpeg_is_reported(monkeypatch):
    monkeypatch.setattr(video.shutil, "which", lambda name: None)

    with pytest.raises(video.FfmpegMissing, match="ffprobe"):
        video.join([Clip(Path("a.webm"), 0)], Path("out.mp4"))
    with pytest.raises(video.FfmpegMissing, match="ffmpeg"):
        video.join([Clip(Path("a.webm"), 0)], Path("out.mp4"), transition=Transition.parse("cut"))
