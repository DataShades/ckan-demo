"""Run settings from ``[tool.ckan-demo]`` in the project's ``pyproject.toml``.

So a project doesn't need long commands::

    [tool.ckan-demo]
    portal = "http://127.0.0.1:5000"
    output = "demo/output"

The nearest ``pyproject.toml`` from the scenario file upward is used; relative
paths in it are relative to that file. Command-line flags and environment
variables win over it. API tokens are never read from it: it is usually
committed.
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
_PATH_KEYS = {"ckan-ini", "output"}
_STRING_KEYS = {"portal", "transition"}


class ConfigError(Exception):
    """``[tool.ckan-demo]`` is malformed."""


@dataclass(frozen=True)
class Config:
    """Settings found in a ``pyproject.toml`` (all optional)."""

    source: Path | None = None
    portal: str | None = None
    ckan_ini: Path | None = None
    output: Path | None = None
    transition: str | None = None
    keys: frozenset[str] = field(default_factory=frozenset)


def find_pyproject(start: Path) -> Path | None:
    """The nearest ``pyproject.toml`` in ``start`` or its parents."""
    directory = start if start.is_dir() else start.parent
    for candidate in (directory, *directory.parents):
        path = candidate / "pyproject.toml"
        if path.is_file():
            return path
    return None


def load_config(scenario_path: Path) -> Config:
    """``[tool.ckan-demo]`` of the project the scenario belongs to."""
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

    known = _PATH_KEYS | _STRING_KEYS
    unknown = sorted(set(table) - known)
    if unknown:
        raise ConfigError(
            f"{pyproject}: unknown key(s) in [tool.{TABLE}]: {', '.join(unknown)} (known: {', '.join(sorted(known))})"
        )
    for key, value in table.items():
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{pyproject}: [tool.{TABLE}] {key} must be a non-empty string")

    def path(key: str) -> Path | None:
        return (pyproject.parent / table[key]).resolve() if key in table else None

    return Config(
        source=pyproject,
        portal=table.get("portal"),
        ckan_ini=path("ckan-ini"),
        output=path("output"),
        transition=table.get("transition"),
        keys=frozenset(table),
    )
