"""Defaults from ``[tool.ckan-demo]`` in the nearest ``pyproject.toml``.

Paths are relative to that file. Flags and environment variables win. API
tokens are never read from it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

TABLE = "ckan-demo"
_PATH_KEYS = {"ckan-ini", "music", "output"}
_STRING_KEYS = {"portal", "transition"}
_NUMBER_KEYS = {"music-volume"}


class ConfigError(Exception):
    """Malformed ``[tool.ckan-demo]``."""


@dataclass(frozen=True)
class Config:
    """Settings from ``pyproject.toml``; all optional."""

    source: Path | None = None
    portal: str | None = None
    ckan_ini: Path | None = None
    output: Path | None = None
    transition: str | None = None
    music: Path | None = None
    music_volume: float | None = None
    keys: frozenset[str] = field(default_factory=frozenset)


def find_pyproject(start: Path) -> Path | None:
    """Nearest ``pyproject.toml`` at or above ``start``."""
    directory = start if start.is_dir() else start.parent
    for candidate in (directory, *directory.parents):
        path = candidate / "pyproject.toml"
        if path.is_file():
            return path
    return None


def load_config(scenario_path: Path) -> Config:
    """``[tool.ckan-demo]`` for the scenario's project."""
    pyproject = find_pyproject(scenario_path.resolve())
    if pyproject is None:
        return Config()

    try:
        data = tomllib.loads(pyproject.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{pyproject}: {error}") from error

    table: dict[str, Any] = data.get("tool", {}).get(TABLE, {})
    if not isinstance(table, dict):
        raise ConfigError(f"{pyproject}: [tool.{TABLE}] must be a table")

    known = _PATH_KEYS | _STRING_KEYS | _NUMBER_KEYS
    unknown = sorted(set(table) - known)
    if unknown:
        raise ConfigError(
            f"{pyproject}: unknown key(s) in [tool.{TABLE}]: {', '.join(unknown)} (known: {', '.join(sorted(known))})"
        )
    for key, value in table.items():
        if key in _NUMBER_KEYS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{pyproject}: [tool.{TABLE}] {key} must be a number")
        elif not isinstance(value, str) or not value:
            raise ConfigError(f"{pyproject}: [tool.{TABLE}] {key} must be a non-empty string")

    def path(key: str) -> Path | None:
        return (pyproject.parent / table[key]).resolve() if key in table else None

    return Config(
        source=pyproject,
        portal=table.get("portal"),
        ckan_ini=path("ckan-ini"),
        output=path("output"),
        transition=table.get("transition"),
        music=path("music"),
        music_volume=float(table["music-volume"]) if "music-volume" in table else None,
        keys=frozenset(table),
    )
