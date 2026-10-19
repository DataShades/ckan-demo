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

    # 10.5 s clip minus 0.5 s lead-in: fade out at 9.6 s.
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

    # Each blend starts 0.6 s before the end so far.
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


def test_music_is_trimmed_faded_and_mixed_under_a_copied_video():
    command = video.music_command(Path("v.mp4"), Path("song.mp3"), Path("out.mp4"), length=20.0, volume=-15)

    assert command[command.index("-stream_loop") + 1] == "-1"  # loops a short song
    assert command[command.index("-stream_loop") + 3] == "song.mp3"
    graph = _graph(command)
    assert "atrim=duration=20.000" in graph
    assert "volume=-15dB" in graph
    assert "afade=t=in:st=0:d=1.00" in graph
    assert "afade=t=out:st=17.000:d=3.00" in graph
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-t") + 1] == "20.000"


def test_music_fades_shrink_for_short_videos():
    graph = _graph(video.music_command(Path("v.mp4"), Path("s.mp3"), Path("o.mp4"), length=3.0))

    assert "afade=t=in:st=0:d=0.75" in graph
    assert "afade=t=out:st=2.000:d=1.00" in graph


def _ffmpeg_or_skip() -> None:
    if not (video.shutil.which("ffmpeg") and video.shutil.which("ffprobe")):
        pytest.skip("needs ffmpeg")


def _streams(path: Path) -> list[str]:
    result = video.subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.split()


@pytest.mark.parametrize("song_seconds", [1, 10])
def test_add_music_matches_the_video_length(tmp_path, song_seconds):
    _ffmpeg_or_skip()
    clip, song = tmp_path / "demo.mp4", tmp_path / "song.wav"
    run = video.subprocess.run
    run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=30:d=4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)  # fmt: skip
    run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={song_seconds}",
         str(song)], check=True)  # fmt: skip

    video.add_music(clip, song)

    assert sorted(_streams(clip)) == ["audio", "video"]
    assert video.duration(clip) == pytest.approx(4.0, abs=0.1)
    assert sorted(tmp_path.iterdir()) == sorted([clip, song])  # no leftover partial file


def test_add_music_failure_keeps_the_silent_video(tmp_path):
    _ffmpeg_or_skip()
    clip = tmp_path / "demo.mp4"
    video.subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=64x64:d=1",
                          "-pix_fmt", "yuv420p", str(clip)], check=True)  # fmt: skip
    before = clip.read_bytes()
    not_audio = tmp_path / "song.mp3"
    not_audio.write_text("not audio")

    with pytest.raises(video.subprocess.CalledProcessError):
        video.add_music(clip, not_audio)

    assert clip.read_bytes() == before
    assert not (tmp_path / "demo.music.mp4").exists()
