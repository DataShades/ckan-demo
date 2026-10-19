"""Joins clips into one video with ffmpeg."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

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
        # Each blend starts `overlap` seconds before the end so far; short
        # clips blend for less.
        joined, total = "[v0]", lengths[0]
        for index in range(1, len(clips)):
            overlap = min(seconds, lengths[index - 1] / 2, lengths[index] / 2)
            label = "[out]" if index == len(clips) - 1 else f"[x{index}]"
            filters.append(
                f"{joined}[v{index}]xfade=transition=fade:duration={overlap:.2f}:offset={total - overlap:.2f}{label}"
            )
            joined, total = label, total + lengths[index] - overlap
    else:
        joined = "".join(f"[v{index}]" for index in range(len(clips)))
        filters.append(f"{joined}concat=n={len(clips)}:v=1:a=0[out]")

    return [
        "ffmpeg", "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
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


def join(clips: Sequence[Clip], output: Path, *, transition: Transition = DEFAULT_TRANSITION) -> Path:
    durations = [duration(clip.path) for clip in clips] if transition.kind != "cut" else None
    command = join_command(clips, output, durations=durations, transition=transition)
    command[0] = _ffmpeg()
    subprocess.run(command, check=True)
    return output


def to_gif(video: Path, output: Path, *, width: int = 960) -> Path:
    command = gif_command(video, output, width=width)
    command[0] = _ffmpeg()
    subprocess.run(command, check=True)
    return output
