"""The ``ckan-demo`` command."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, TypeVar

import click
import requests

from ckan_demo import __version__, seeding, video
from ckan_demo.config import Config, ConfigError, load_config
from ckan_demo.director import Options
from ckan_demo.portal import ACTION_ERRORS, Portal, PortalError
from ckan_demo.recorder import RecordingError, record
from ckan_demo.scenario import Scenario, ScenarioError, load_scenario

TOKEN_ENV = "CKAN_DEMO_API_TOKEN"
CKAN_INI_ENV = "CKAN_INI"  # same as CKAN's CLI
DEFAULT_PORTAL = "http://127.0.0.1:5000"

F = TypeVar("F", bound=Callable[..., Any])


class SizeType(click.ParamType):
    """Video size, e.g. ``1920x1080``."""

    name = "WIDTHxHEIGHT"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> tuple[int, int]:
        if isinstance(value, tuple):
            return value
        match = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", str(value))
        if not match or not int(match[1]) or not int(match[2]):
            self.fail(f"{value!r} is not a size like 1920x1080", param, ctx)
        return int(match[1]), int(match[2])


class TransitionType(click.ParamType):
    """``cut``, ``fade[:seconds]`` or ``crossfade[:seconds]``."""

    name = "transition"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> video.Transition:
        if isinstance(value, video.Transition):
            return value
        try:
            return video.Transition.parse(str(value))
        except ValueError as error:
            self.fail(str(error), param, ctx)


def resolve_transition(flag: video.Transition | None, scenario: Scenario, config: Config) -> video.Transition:
    """Flag, then scenario, then config, then default."""
    if flag is not None:
        return flag
    for source, value in (("the scenario", scenario.transition), (f"{config.source}", config.transition)):
        if value:
            try:
                return video.Transition.parse(value)
            except ValueError as error:
                raise ConfigError(f"{source}: {error}") from error
    return video.DEFAULT_TRANSITION


@contextlib.contextmanager
def _clean_errors() -> Iterator[None]:
    """Turn known errors into one-line messages."""
    try:
        yield
    except (ScenarioError, PortalError, ConfigError) as error:
        raise click.ClickException(str(error)) from error
    except ACTION_ERRORS as error:
        raise click.ClickException(f"CKAN: {type(error).__name__}: {error}") from error
    except requests.RequestException as error:
        raise click.ClickException(f"cannot reach the portal: {error}") from error


def _scenario_argument(func: F) -> F:
    return click.argument("scenario", type=click.Path(exists=True, dir_okay=False, path_type=Path))(func)


def _portal_options(func: F) -> F:
    """Options shared by commands that talk to a portal."""
    options = [
        _scenario_argument,
        click.option("--portal", metavar="URL", help=f"CKAN site URL. [default: config portal, or {DEFAULT_PORTAL}]"),
        click.option(
            "--api-token",
            metavar="TOKEN",
            envvar=TOKEN_ENV,
            show_envvar=True,
            help="A sysadmin's API token, for scenarios that seed through the API.",
        ),
        click.option(
            "--ckan-ini",
            type=click.Path(dir_okay=False, path_type=Path),
            envvar=CKAN_INI_ENV,
            show_envvar=True,
            help="The portal's ckan.ini, for local seeding. [default: config ckan-ini]",
        ),
        click.option("--reset", is_flag=True, help="Ask the scenario to reset its data to a clean slate."),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def resolve_settings(
    scenario: Scenario,
    config: Config,
    *,
    portal: str | None,
    api_token: str | None,
    ckan_ini: Path | None,
    output: Path | None = None,
) -> tuple[Portal, Path]:
    """Portal and output directory: command line first, then config, then
    defaults."""
    site = Portal(
        portal or config.portal or DEFAULT_PORTAL,
        api_token=api_token,
        ckan_ini=ckan_ini or config.ckan_ini,
    )
    return site, output or config.output or Path("demo-output") / scenario.slug


def _describe_config(config: Config) -> None:
    if config.keys:
        click.echo(f"Config: [tool.ckan-demo] in {config.source} ({', '.join(sorted(config.keys))})")


@click.group(context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100})
@click.version_option(__version__, prog_name="ckan-demo")
def cli() -> None:
    """Record demo videos of a CKAN portal from scenario files."""


@cli.command("list")
@_scenario_argument
def list_command(scenario: Path) -> None:
    """Show a scenario's users, scenes and seeding."""
    with _clean_errors():
        loaded = load_scenario(scenario)
        config = load_config(scenario)

    click.echo(loaded.title)
    if config.keys:
        click.echo()
        _describe_config(config)
    if loaded.setup_hook:
        how = "local" if loaded.setup_local else "through the API or local"
        optional = ", optional" if loaded.setup_optional else ""
        click.echo(f"\nSeeding: {how}{optional} (needs {seeding.requirements(loaded)})")
    click.echo("\nUsers:")
    for key, user in loaded.users.items():
        click.echo(f"  {key:12} {user.name}{' (sysadmin)' if user.sysadmin else ''}")
    click.echo("\nScenes:")
    for scene in loaded.scenes:
        click.echo(f"  {scene.name:24} {scene.user or 'anonymous':12} {scene.description}")


@cli.command()
@_portal_options
def setup(scenario: Path, portal: str | None, api_token: str | None, ckan_ini: Path | None, reset: bool) -> None:
    """Seed the portal without recording."""
    with _clean_errors():
        loaded = load_scenario(scenario)
        config = load_config(scenario)
        site, _ = resolve_settings(loaded, config, portal=portal, api_token=api_token, ckan_ini=ckan_ini)
        _describe_config(config)
        click.echo("Preparing data…")
        seeding.run_setup(loaded, site, reset=reset, log=click.echo)


@cli.command("record", short_help="Seed, record every scene and join them into one video.")
@_portal_options
@click.option("--no-setup", is_flag=True, help="Record without seeding.")
@click.option("--size", type=SizeType(), metavar="WxH", help="Video size. [default: the scenario's, usually 1920x1080]")
@click.option(
    "--speed",
    type=click.FloatRange(min=0, min_open=True),
    default=1.0,
    show_default=True,
    help="Pace multiplier; 1.3 is 30% faster.",
)
@click.option("--captions/--no-captions", default=True, help="Show captions; turn off for a voice-over.")
@click.option("--scenes", metavar="NAME,…", help="Record only these scenes, in scenario order. [default: all]")
@click.option("--headed", is_flag=True, help="Show the browser while recording.")
@click.option(
    "--transition",
    type=TransitionType(),
    metavar="cut|fade[:S]|crossfade[:S]",
    help="Between scenes. [default: the scenario's, config transition, or fade:0.4]",
)
@click.option("--gif", is_flag=True, help="Also write a GIF next to the MP4.")
@click.option(
    "--output",
    type=click.Path(file_okay=False, path_type=Path),
    help="Where clips, video and stills go. [default: config output, or ./demo-output/<scenario title>]",
)
def record_command(
    scenario: Path,
    portal: str | None,
    api_token: str | None,
    ckan_ini: Path | None,
    reset: bool,
    no_setup: bool,
    size: tuple[int, int] | None,
    speed: float,
    captions: bool,
    scenes: str | None,
    headed: bool,
    transition: video.Transition | None,
    gif: bool,
    output: Path | None,
) -> None:
    """Seed, record every scene and join them."""
    with _clean_errors():
        loaded = load_scenario(scenario)
        config = load_config(scenario)
        site, output_dir = resolve_settings(
            loaded, config, portal=portal, api_token=api_token, ckan_ini=ckan_ini, output=output
        )
        selected = loaded.select(scenes.split(",") if scenes else None)
        effect = resolve_transition(transition, loaded, config)
        _describe_config(config)

        if not no_setup:
            seeding.seed_before_recording(
                loaded, site, reset=reset, log=click.echo, warn=lambda line: click.echo(line, err=True)
            )

    width, height = size or loaded.size
    options = Options(base_url=site.url, width=width, height=height, captions=captions, speed=speed, output=output_dir)
    try:
        clips = record(loaded, options, selected, headed=headed, on_scene=click.echo)
    except RecordingError as error:
        message = str(error)
        if error.clips:
            message += f"\nRecorded before it: {', '.join(clip.path.name for clip in error.clips)}"
        raise click.ClickException(message) from error

    target = output_dir / f"{loaded.slug}.mp4"
    try:
        video.join(clips, target, transition=effect)
    except video.FfmpegMissing as error:
        click.echo(f"{error}. The scenes are in {output_dir}/ as .webm files.")
        return
    click.echo(f"Video: {target}")

    if gif:
        click.echo(f"GIF:   {video.to_gif(target, target.with_suffix('.gif'))}")


if __name__ == "__main__":  # pragma: no cover
    cli()
