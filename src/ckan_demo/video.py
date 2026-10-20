"""Joins clips into one video with ffmpeg, adds background music and
chapters, and writes the captions as subtitles."""

from __future__ import annotations

import dataclasses
import html
import itertools
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ckan_demo.recorder import Clip


class FfmpegMissing(Exception):
    """ffmpeg is not on PATH."""


# ── Transitions ──────────────────────────────────────────────────────────────

TransitionKind = Literal["cut", "fade", "crossfade"]
_DEFAULT_SECONDS: dict[str, float] = {"cut": 0.0, "fade": 0.4, "crossfade": 0.6}


@dataclass(frozen=True)
class Transition:
    """Between scenes: ``cut``, ``fade`` (through black) or ``crossfade``
    (overlapping, so slightly shorter)."""

    kind: TransitionKind = "fade"
    seconds: float = _DEFAULT_SECONDS["fade"]

    @classmethod
    def parse(cls, value: str) -> Transition:
        """``cut``, ``fade``, ``fade:0.4``, ``crossfade``, ``crossfade:0.6``."""
        match = re.fullmatch(r"\s*(cut|fade|crossfade)\s*(?::\s*(\d+(?:\.\d+)?)\s*)?", value or "")
        if not match:
            raise ValueError(f"{value!r} is not a transition: use cut, fade[:seconds] or crossfade[:seconds]")
        kind: TransitionKind = match[1]  # type: ignore[assignment]
        if kind == "cut":
            if match[2] is not None:
                raise ValueError("a cut takes no duration")
            return cls("cut", 0.0)
        seconds = float(match[2]) if match[2] is not None else _DEFAULT_SECONDS[kind]
        if seconds <= 0:
            raise ValueError(f"{kind} needs a duration above 0 (or use cut)")
        return cls(kind, seconds)

    def __str__(self) -> str:
        return self.kind if self.kind == "cut" else f"{self.kind}:{self.seconds:g}"


DEFAULT_TRANSITION = Transition()


# ── ffmpeg ───────────────────────────────────────────────────────────────────


def _ffmpeg(tool: str = "ffmpeg") -> str:
    path = shutil.which(tool)
    if not path:
        raise FfmpegMissing(f"{tool} is not installed")
    return path


def duration(video: Path) -> float:
    """Video length in seconds, via ffprobe."""
    result = subprocess.run(
        [_ffmpeg("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _overlap(before: float, after: float, seconds: float) -> float:
    """A crossfade's length: short clips blend for less."""
    return min(seconds, before / 2, after / 2)


def clip_starts(lengths: Sequence[float], transition: Transition) -> list[float]:
    """Where each trimmed clip starts in the joined video. A crossfade
    overlaps a clip with the end of the one before."""
    starts, total = [], 0.0
    for index, length in enumerate(lengths):
        if index and transition.kind == "crossfade":
            total -= _overlap(lengths[index - 1], length, transition.seconds)
        starts.append(total)
        total += length
    return starts


def join_command(
    clips: Sequence[Clip],
    output: Path,
    *,
    durations: Sequence[float] | None = None,
    transition: Transition = DEFAULT_TRANSITION,
    fps: int = 30,
) -> list[str]:
    """ffmpeg command that trims lead-ins and joins the clips.

    Fades need ``durations``; without them scenes are cut.
    """
    inputs: list[str] = []
    filters: list[str] = []
    lengths = [durations[i] - clip.lead_in for i, clip in enumerate(clips)] if durations else []
    kind = transition.kind if lengths else "cut"
    seconds = transition.seconds

    for index, clip in enumerate(clips):
        inputs += ["-i", str(clip.path)]
        # Same fps, time base and pixel format, as concat and xfade need.
        chain = f"[{index}:v]trim=start={clip.lead_in:.2f},setpts=PTS-STARTPTS,fps={fps},settb=AVTB,format=yuv420p"
        if kind == "fade":
            chain += f",fade=t=in:st=0:d={seconds:g}"
            if lengths[index] > 2 * seconds:
                chain += f",fade=t=out:st={lengths[index] - seconds:.2f}:d={seconds:g}"
        filters.append(f"{chain}[v{index}]")

    if kind == "crossfade" and len(clips) > 1:
        # Each blend starts where the next clip does.
        joined, starts = "[v0]", clip_starts(lengths, transition)
        for index in range(1, len(clips)):
            overlap = _overlap(lengths[index - 1], lengths[index], seconds)
            label = "[out]" if index == len(clips) - 1 else f"[x{index}]"
            filters.append(
                f"{joined}[v{index}]xfade=transition=fade:duration={overlap:.2f}:offset={starts[index]:.2f}{label}"
            )
            joined = label
    else:
        joined = "".join(f"[v{index}]" for index in range(len(clips)))
        filters.append(f"{joined}concat=n={len(clips)}:v=1:a=0[out]")

    return [
        "ffmpeg", "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(output),
    ]  # fmt: skip


DEFAULT_MUSIC_VOLUME = -12.0  # dB; a bed under the visuals, not the main sound


def music_command(
    video: Path,
    music: Path,
    output: Path,
    *,
    length: float,
    volume: float = DEFAULT_MUSIC_VOLUME,
    fade_in: float = 1.0,
    fade_out: float = 3.0,
) -> list[str]:
    """ffmpeg command that lays ``music`` under the finished ``video``.

    The music loops if it's shorter than the video, is cut where the video
    ends and fades in and out. The video stream is copied, not re-encoded.
    """
    fade_in = min(fade_in, length / 4)
    fade_out = min(fade_out, length / 3)
    chain = (
        f"[1:a]atrim=duration={length:.3f},asetpts=PTS-STARTPTS,volume={volume:g}dB,"
        f"afade=t=in:st=0:d={fade_in:.2f},afade=t=out:st={length - fade_out:.3f}:d={fade_out:.2f}[music]"
    )
    return [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-stream_loop", "-1", "-i", str(music),
        "-filter_complex", chain, "-map", "0:v", "-map", "[music]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{length:.3f}",
        "-movflags", "+faststart", str(output),
    ]  # fmt: skip


def gif_command(video: Path, output: Path, *, width: int = 960, fps: int = 12) -> list[str]:
    """ffmpeg command for a GIF with its own palette."""
    scale = f"fps={fps},scale={width}:-1:flags=lanczos"
    return [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
        "-filter_complex", f"[0:v]{scale},split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer",
        str(output),
    ]  # fmt: skip


# ── Sync ─────────────────────────────────────────────────────────────────────

_SYNC_CHROMA = 170


def sync_command(clip: Path, *, within: float) -> list[str]:
    """ffmpeg command printing the chroma of the sync marker's corner for
    each frame in the first ``within`` seconds."""
    return [
        "ffmpeg", "-v", "error", "-t", f"{within:.2f}", "-i", str(clip),
        "-vf", "crop=16:16:8:8,signalstats,metadata=print:file=-", "-an", "-f", "null", "-",
    ]  # fmt: skip


def find_sync(clip: Path, *, within: float) -> float | None:
    """When the sync marker first shows in ``clip``, in video seconds."""
    command = sync_command(clip, within=within)
    command[0] = _ffmpeg()
    output = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    for frame in re.split(r"(?=frame:)", output):
        time = re.search(r"pts_time:([\d.]+)", frame)
        u = re.search(r"signalstats\.UAVG=([\d.]+)", frame)
        v = re.search(r"signalstats\.VAVG=([\d.]+)", frame)
        if time and u and v and float(u[1]) > _SYNC_CHROMA and float(v[1]) > _SYNC_CHROMA:
            return float(time[1])
    return None


def line_up(clip: Clip, sync_at: float) -> Clip:
    """``clip`` with its lead-in and captions on the video's timeline instead
    of the Director's. They differ by how late the recording started, which
    is usually a few hundredths of a second but can be a second or more on a
    busy machine (``--jobs``). Unchanged if the marker isn't found."""
    try:
        found = find_sync(clip.path, within=clip.lead_in + 10)
    except (FfmpegMissing, subprocess.CalledProcessError):
        return clip
    if found is None:
        return clip
    offset = found - sync_at
    cues = tuple(dataclasses.replace(cue, start=cue.start + offset, end=cue.end + offset) for cue in clip.cues)
    return dataclasses.replace(clip, lead_in=max(0.0, clip.lead_in + offset), cues=cues)


# ── Subtitles ────────────────────────────────────────────────────────────────


MIN_CUE = 0.05  # seconds; anything shorter was never readable


def _timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    return f"{hours:02}:{minutes:02}:{millis // 1000:02}.{millis % 1000:03}"


def subtitles(clips: Sequence[Clip], durations: Sequence[float], transition: Transition = DEFAULT_TRANSITION) -> str:
    """WebVTT for the joined video: each clip's captions, moved to where the
    clip lands. Captions in a cut lead-in or past a clip's end are trimmed."""
    lengths = [durations[i] - clip.lead_in for i, clip in enumerate(clips)]
    cues: list[list[Any]] = []
    for clip, start, length in zip(clips, clip_starts(lengths, transition), lengths, strict=True):
        for cue in clip.cues:
            begin = start + max(0.0, cue.start - clip.lead_in)
            end = start + min(length, cue.end - clip.lead_in)
            cues.append([begin, end, cue.text])
    # Crossfades overlap scenes; the next scene's caption takes over.
    cues.sort(key=lambda cue: cue[0])
    for cue, following in itertools.pairwise(cues):
        cue[1] = min(cue[1], following[0])
    cues = [cue for cue in cues if cue[1] - cue[0] >= MIN_CUE]

    blocks = ["WEBVTT"]
    for number, (begin, end, text) in enumerate(cues, start=1):
        blocks.append(f"{number}\n{_timestamp(begin)} --> {_timestamp(end)}\n{html.escape(text, quote=False)}")
    return "\n\n".join(blocks) + "\n"


def write_subtitles(
    clips: Sequence[Clip],
    output: Path,
    *,
    transition: Transition = DEFAULT_TRANSITION,
    durations: Sequence[float] | None = None,
) -> Path | None:
    """Write ``output`` (.vtt) if any clip has captions; otherwise remove an
    old one, so it never describes a different recording. ``durations`` are
    the clips' lengths, measured if not given."""
    if not any(clip.cues for clip in clips):
        output.unlink(missing_ok=True)
        return None
    if durations is None:
        durations = [duration(clip.path) for clip in clips]
    output.write_text(subtitles(clips, durations, transition), encoding="utf-8")
    return output


# ── Chapters ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Chapter:
    title: str
    start: float  # seconds in the joined video
    end: float


def chapters(
    titles: Sequence[str],
    clips: Sequence[Clip],
    durations: Sequence[float],
    transition: Transition = DEFAULT_TRANSITION,
) -> list[Chapter]:
    """One chapter per clip, from where it lands in the joined video to where
    the next one does. A crossfade's chapter starts as the blend begins."""
    lengths = [durations[i] - clip.lead_in for i, clip in enumerate(clips)]
    starts = clip_starts(lengths, transition)
    ends = [*starts[1:], starts[-1] + lengths[-1]] if starts else []
    return [Chapter(title, start, end) for title, start, end in zip(titles, starts, ends, strict=True)]


def youtube_timestamp(seconds: float) -> str:
    """``0:42``, ``12:05``, ``1:02:03``: whole seconds, rounded down."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def timestamps(chapters: Sequence[Chapter]) -> str:
    """Chapters as a YouTube description lists them, one per line."""
    return "\n".join(f"{youtube_timestamp(chapter.start)} {chapter.title}" for chapter in chapters)


YOUTUBE_MIN_CHAPTERS = 3
YOUTUBE_MIN_CHAPTER = 10.0  # seconds


def youtube_problems(chapters: Sequence[Chapter]) -> list[str]:
    """Why YouTube would ignore these timestamps, if it would."""
    problems = []
    if len(chapters) < YOUTUBE_MIN_CHAPTERS:
        problems.append(f"YouTube needs at least {YOUTUBE_MIN_CHAPTERS} chapters")
    short = [chapter.title for chapter in chapters if chapter.end - chapter.start < YOUTUBE_MIN_CHAPTER]
    if short:
        problems.append(f"YouTube needs chapters of {YOUTUBE_MIN_CHAPTER:g} s or more ({', '.join(short)})")
    return problems


def _ffmetadata_escape(text: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", text)


def ffmetadata(chapters: Sequence[Chapter]) -> str:
    """Chapters in ffmpeg's metadata format, in milliseconds."""
    lines = [";FFMETADATA1"]
    for chapter in chapters:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={round(chapter.start * 1000)}",
            f"END={round(chapter.end * 1000)}",
            f"title={_ffmetadata_escape(chapter.title)}",
        ]
    return "\n".join(lines) + "\n"


def chapters_command(video: Path, metadata: Path, output: Path) -> list[str]:
    """ffmpeg command that copies ``video`` with the chapters in ``metadata``."""
    return [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-f", "ffmetadata", "-i", str(metadata),
        "-map", "0", "-map_chapters", "1", "-c", "copy", "-movflags", "+faststart", str(output),
    ]  # fmt: skip


def add_chapters(video: Path, chapters: Sequence[Chapter]) -> Path:
    """Embed ``chapters`` in ``video`` in place. The streams are copied, not
    re-encoded. On failure the video is left as it was."""
    metadata = video.with_name(f"{video.stem}.chapters.txt")
    partial = video.with_name(f"{video.stem}.chapters{video.suffix}")
    metadata.write_text(ffmetadata(chapters), encoding="utf-8")
    command = chapters_command(video, metadata, partial)
    command[0] = _ffmpeg()
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        partial.unlink(missing_ok=True)
        raise
    finally:
        metadata.unlink(missing_ok=True)
    partial.replace(video)
    return video


def join(clips: Sequence[Clip], output: Path, *, transition: Transition = DEFAULT_TRANSITION) -> Path:
    durations = [duration(clip.path) for clip in clips] if transition.kind != "cut" else None
    command = join_command(clips, output, durations=durations, transition=transition)
    command[0] = _ffmpeg()
    subprocess.run(command, check=True)
    return output


def add_music(video: Path, music: Path, *, volume: float = DEFAULT_MUSIC_VOLUME) -> Path:
    """Lay ``music`` under ``video`` in place. On failure the silent video
    is left as it was."""
    partial = video.with_name(f"{video.stem}.music{video.suffix}")
    command = music_command(video, music, partial, length=duration(video), volume=volume)
    command[0] = _ffmpeg()
    try:
        # ffmpeg's error goes into the exception (error.stderr), not the terminal.
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(video)
    return video


def to_gif(video: Path, output: Path, *, width: int = 960) -> Path:
    command = gif_command(video, output, width=width)
    command[0] = _ffmpeg()
    subprocess.run(command, check=True)
    return output
