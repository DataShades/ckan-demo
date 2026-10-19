"""Joining clips into one video, with ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ckan_demo.recorder import Clip


class FfmpegMissing(Exception):
    """ffmpeg is not on PATH."""


def _ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FfmpegMissing("ffmpeg is not installed")
    return ffmpeg


def join_command(clips: Sequence[Clip], output: Path, *, fps: int = 30) -> list[str]:
    """The ffmpeg command that trims each clip's lead-in and joins them."""
    inputs: list[str] = []
    filters: list[str] = []
    for index, clip in enumerate(clips):
        inputs += ["-i", str(clip.path)]
        filters.append(f"[{index}:v]trim=start={clip.lead_in:.2f},setpts=PTS-STARTPTS,fps={fps}[v{index}]")
    joined = "".join(f"[v{index}]" for index in range(len(clips)))
    filters.append(f"{joined}concat=n={len(clips)}:v=1:a=0[out]")

    return [
        "ffmpeg", "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(output),
    ]  # fmt: skip


def gif_command(video: Path, output: Path, *, width: int = 960, fps: int = 12) -> list[str]:
    """The ffmpeg command for a GIF with a palette made for this video."""
    scale = f"fps={fps},scale={width}:-1:flags=lanczos"
    return [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
        "-filter_complex", f"[0:v]{scale},split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer",
        str(output),
    ]  # fmt: skip


def join(clips: Sequence[Clip], output: Path) -> Path:
    command = join_command(clips, output)
    command[0] = _ffmpeg()
    subprocess.run(command, check=True)
    return output


def to_gif(video: Path, output: Path, *, width: int = 960) -> Path:
    command = gif_command(video, output, width=width)
    command[0] = _ffmpeg()
    subprocess.run(command, check=True)
    return output
