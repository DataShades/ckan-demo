from __future__ import annotations

import json
from pathlib import Path

import pytest

from ckan_demo import video
from ckan_demo.director import Cue
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


def test_clip_starts_follow_the_transition():
    assert video.clip_starts([10.0, 6.0, 8.0], Transition("fade", 0.4)) == [0.0, 10.0, 16.0]
    assert video.clip_starts([10.0, 6.0, 8.0], Transition("crossfade", 0.6)) == pytest.approx([0.0, 9.4, 14.8])
    assert video.clip_starts([5.0, 0.8], Transition("crossfade", 0.6)) == pytest.approx([0.0, 4.6])


def _cues(vtt: str) -> list[tuple[str, str]]:
    blocks = vtt.split("\n\n")
    assert blocks[0] == "WEBVTT"
    return [(lines[1], lines[2]) for lines in (block.split("\n") for block in blocks[1:])]


def test_subtitles_move_each_clips_captions_to_where_it_lands():
    clips = [
        Clip(Path("a.webm"), 1.0, (Cue(1.5, 4.0, "Start with a search"),)),
        Clip(Path("b.webm"), 0.5, (Cue(0.5, 2.5, "Open a dataset"),)),
    ]

    vtt = video.subtitles(clips, [11.0, 6.5], Transition("crossfade", 0.6))

    # a: 10 s after its 1 s lead-in; b starts 0.6 s before that ends.
    assert _cues(vtt) == [
        ("00:00:00.500 --> 00:00:03.000", "Start with a search"),
        ("00:00:09.400 --> 00:00:11.400", "Open a dataset"),
    ]


def test_subtitles_trim_lead_ins_and_clip_ends_and_never_overlap():
    clips = [
        Clip(
            Path("a.webm"), 2.0, (Cue(0.5, 1.0, "During loading"), Cue(1.0, 3.0, "Straddles"), Cue(9.0, 20.0, "Long"))
        ),
        Clip(Path("b.webm"), 0.0, (Cue(0.0, 1.0, "Next"),)),
    ]

    vtt = video.subtitles(clips, [10.0, 5.0], Transition("crossfade", 1.0))

    # a is 8 s after its lead-in; b starts at 7 s. "Long" would run 7-8 s,
    # under b's first caption, which takes over.
    assert _cues(vtt) == [
        ("00:00:00.000 --> 00:00:01.000", "Straddles"),
        ("00:00:07.000 --> 00:00:08.000", "Next"),
    ]


def test_subtitle_text_is_escaped_and_hours_are_counted():
    clip = Clip(Path("a.webm"), 0.0, (Cue(3725.25, 3726.0, "Tom & Jerry <script>"),))

    assert _cues(video.subtitles([clip], [4000.0], Transition("cut", 0.0))) == [
        ("01:02:05.250 --> 01:02:06.000", "Tom &amp; Jerry &lt;script&gt;")
    ]


def test_write_subtitles_only_with_captions(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "duration", lambda path: 5.0)
    target = tmp_path / "demo.vtt"
    captioned = [Clip(tmp_path / "a.webm", 0.0, (Cue(1.0, 2.0, "Hi"),))]

    assert video.write_subtitles(captioned, target) == target
    assert "Hi" in target.read_text()

    assert video.write_subtitles([Clip(tmp_path / "a.webm", 0.0)], target) is None
    assert not target.exists()  # an old file would describe another recording


def test_chapters_start_where_each_clip_lands():
    clips = [Clip(Path("a.webm"), 1.0), Clip(Path("b.webm"), 2.0), Clip(Path("c.webm"), 0.0)]
    durations = [11.0, 22.0, 5.0]  # 10, 20 and 5 s once trimmed

    cut = video.chapters(["A", "B", "C"], clips, durations, Transition("cut", 0))
    assert [(c.title, c.start, c.end) for c in cut] == [("A", 0, 10), ("B", 10, 30), ("C", 30, 35)]

    # A crossfade's chapter starts as the blend does, 0.6 s before the cut would.
    blended = video.chapters(["A", "B", "C"], clips, durations, Transition("crossfade", 0.6))
    assert [round(c.start, 2) for c in blended] == [0, 9.4, 28.8]
    assert round(blended[-1].end, 2) == 33.8


def test_timestamps_read_like_a_youtube_description():
    chapters = [
        video.Chapter("Open a ticket", 0, 42.9),
        video.Chapter("Staff triage", 42.9, 3725),
        video.Chapter("Close", 3725, 3800),
    ]

    assert video.timestamps(chapters) == "0:00 Open a ticket\n0:42 Staff triage\n1:02:05 Close"


def test_youtube_problems_name_short_chapters_and_too_few():
    assert video.youtube_problems([video.Chapter(t, i * 10, i * 10 + 10) for i, t in enumerate("ABC")]) == []
    problems = video.youtube_problems([video.Chapter("Long", 0, 30), video.Chapter("Quick", 30, 34)])
    assert problems == ["YouTube needs at least 3 chapters", "YouTube needs chapters of 10 s or more (Quick)"]


def test_ffmetadata_escapes_titles():
    text = video.ffmetadata([video.Chapter("Q&A; a=b #1", 0, 1.2345)])

    assert text == ";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1234\ntitle=Q&A\\; a\\=b \\#1\n"


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


def _clip_with_marker(path: Path, at: float | None) -> Path:
    """A 4 s white WebM like a recorded page, with the sync marker (a magenta
    corner) from ``at`` for 0.3 s."""
    marker = f",drawbox=x=0:y=0:w=32:h=32:color=0xff00ff:t=fill:enable='between(t,{at},{at + 0.3})'" if at else ""
    video.subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=white:s=320x240:r=25:d=4",
                          "-vf", f"format=yuv420p{marker}", str(path)], check=True)  # fmt: skip
    return path


def test_line_up_moves_the_cut_and_captions_to_the_videos_timeline(tmp_path):
    _ffmpeg_or_skip()
    # The Director saw the marker at 0.5 s, the video shows it at 1.5 s: the
    # recording started a second late, so everything is a second later in it.
    clip = Clip(_clip_with_marker(tmp_path / "a.webm", 1.5), 0.8, (Cue(1.0, 2.0, "Hi"),))

    lined_up = video.line_up(clip, sync_at=0.5)

    assert lined_up.lead_in == pytest.approx(1.8, abs=0.05)
    assert lined_up.cues[0].start == pytest.approx(2.0, abs=0.05)
    assert lined_up.cues[0].end - lined_up.cues[0].start == pytest.approx(1.0)


def test_line_up_without_a_marker_leaves_the_clip(tmp_path):
    _ffmpeg_or_skip()
    clip = Clip(_clip_with_marker(tmp_path / "a.webm", None), 0.8, (Cue(1.0, 2.0, "Hi"),))

    assert video.line_up(clip, sync_at=0.5) == clip


def test_line_up_without_ffmpeg_leaves_the_clip(monkeypatch):
    monkeypatch.setattr(video.shutil, "which", lambda name: None)
    clip = Clip(Path("a.webm"), 0.8)

    assert video.line_up(clip, sync_at=0.5) == clip


def test_add_music_failure_keeps_the_silent_video(tmp_path):
    _ffmpeg_or_skip()
    clip = tmp_path / "demo.mp4"
    video.subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=64x64:d=1",
                          "-pix_fmt", "yuv420p", str(clip)], check=True)  # fmt: skip
    before = clip.read_bytes()
    not_audio = tmp_path / "song.mp3"
    not_audio.write_text("not audio")

    with pytest.raises(video.subprocess.CalledProcessError) as raised:
        video.add_music(clip, not_audio)

    assert "Invalid data" in raised.value.stderr  # captured for the error message, not printed

    assert clip.read_bytes() == before
    assert not (tmp_path / "demo.music.mp4").exists()


def test_add_chapters_embeds_them_without_re_encoding(tmp_path):
    _ffmpeg_or_skip()
    clip = tmp_path / "demo.mp4"
    video.subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=64x64:d=4",
                          "-pix_fmt", "yuv420p", str(clip)], check=True)  # fmt: skip

    video.add_chapters(clip, [video.Chapter("Open; a ticket", 0, 1.5), video.Chapter("Staff triage", 1.5, 4)])

    result = video.subprocess.run(
        ["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(clip)],
        check=True,
        capture_output=True,
        text=True,
    )
    found = [(c["tags"]["title"], float(c["start_time"])) for c in json.loads(result.stdout)["chapters"]]
    assert found == [("Open; a ticket", 0.0), ("Staff triage", 1.5)]
    assert video.duration(clip) == pytest.approx(4.0, abs=0.1)
    assert sorted(tmp_path.iterdir()) == [clip]  # no leftover metadata or partial file
