"""Defaults from ``[tool.ckan-demo]`` in the nearest ``pyproject.toml``.

Paths are relative to that file. Flags and environment variables win. API
tokens are never read from it.
"""

from __future__ import annotations

import base64
import re
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
_TABLE_KEYS = {"brand"}
_BRAND_KEYS = {"logo", "background", "text", "accent"}

# Hex, a name, or a colour function such as rgb() or oklch(); enough to catch
# typos without parsing CSS.
_COLOUR = re.compile(r"#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})|[a-z]+|[a-z]+\([^;{}()]*\)", re.IGNORECASE)
_LOGO_TYPES = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class ConfigError(Exception):
    """Malformed ``[tool.ckan-demo]``."""


@dataclass(frozen=True)
class Brand:
    """Title card logo and colours, from ``[tool.ckan-demo.brand]``."""

    logo: Path | None = None
    background: tuple[str, ...] = ()  # one colour, or gradient stops
    text: str | None = None
    accent: str | None = None  # the kicker

    def overlay(self) -> dict[str, str]:
        """The overlay's card settings: CSS values and the logo as a data URI.

        Reads the logo, so a missing or unsupported one fails before recording.
        """
        settings: dict[str, str] = {}
        if self.logo is not None:
            mime = _LOGO_TYPES.get(self.logo.suffix.lower())
            if mime is None:
                raise ConfigError(f"brand logo {self.logo}: use one of {', '.join(sorted(_LOGO_TYPES))}")
            if not self.logo.is_file():
                raise ConfigError(f"brand logo {self.logo} is not a file")
            settings["logo"] = f"data:{mime};base64,{base64.b64encode(self.logo.read_bytes()).decode()}"
        if len(self.background) == 1:
            settings["background"] = self.background[0]
        elif self.background:
            settings["background"] = f"linear-gradient(135deg, {', '.join(self.background)})"
        if self.text:
            settings["text"] = self.text
            settings["muted"] = f"color-mix(in srgb, {self.text} 80%, transparent)"
        if self.accent:
            settings["accent"] = self.accent
        return settings


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
    brand: Brand = field(default_factory=Brand)
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

    known = _PATH_KEYS | _STRING_KEYS | _NUMBER_KEYS | _TABLE_KEYS
    unknown = sorted(set(table) - known)
    if unknown:
        raise ConfigError(
            f"{pyproject}: unknown key(s) in [tool.{TABLE}]: {', '.join(unknown)} (known: {', '.join(sorted(known))})"
        )
    for key, value in table.items():
        if key in _NUMBER_KEYS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{pyproject}: [tool.{TABLE}] {key} must be a number")
        elif key in _TABLE_KEYS:
            if not isinstance(value, dict):
                raise ConfigError(f"{pyproject}: [tool.{TABLE}] {key} must be a table ([tool.{TABLE}.{key}])")
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
        brand=_load_brand(pyproject, table.get("brand", {})),
        keys=frozenset(table),
    )


def _load_brand(pyproject: Path, table: dict[str, Any]) -> Brand:
    where = f"{pyproject}: [tool.{TABLE}.brand]"
    unknown = sorted(set(table) - _BRAND_KEYS)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)} (known: {', '.join(sorted(_BRAND_KEYS))})")

    def colour(key: str, value: Any) -> str:
        if not isinstance(value, str) or not _COLOUR.fullmatch(value.strip()):
            raise ConfigError(f'{where} {key} must be a CSS colour like "#1e3a8a", not {value!r}')
        return value.strip()

    logo = table.get("logo")
    if logo is not None and (not isinstance(logo, str) or not logo):
        raise ConfigError(f"{where} logo must be a non-empty string")

    background = table.get("background", [])
    if isinstance(background, str):
        background = [background]
    if not isinstance(background, list) or ("background" in table and not background):
        raise ConfigError(f"{where} background must be a colour or a list of colours")

    return Brand(
        logo=(pyproject.parent / logo).resolve() if logo else None,
        background=tuple(colour("background", value) for value in background),
        text=colour("text", table["text"]) if "text" in table else None,
        accent=colour("accent", table["accent"]) if "accent" in table else None,
    )
