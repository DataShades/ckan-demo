"""Scenario files: users, an optional setup hook and scenes.

from ckan_demo import Director, Scenario, User

scenario = Scenario(
    "Dataset search",
    users={"visitor": User("demo-visitor", fullname="Dana Visitor")},
)

@scenario.scene("search", user="visitor")
def search(d: Director) -> None:
    d.goto("/dataset/")
    d.type(d.page.get_by_placeholder("Search datasets"), "population")
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from ckan_demo.director import Director
    from ckan_demo.seeding import Setup

DEFAULT_PASSWORD = "correct horse battery staple"


class ScenarioError(Exception):
    """Bad or missing scenario file."""


@dataclass(frozen=True)
class User:
    """A demo user, created or updated before recording."""

    name: str
    fullname: str = ""
    password: str = DEFAULT_PASSWORD
    sysadmin: bool = False
    email: str | None = None

    @property
    def email_address(self) -> str:
        return self.email or f"{self.name}@example.com"


@dataclass(frozen=True)
class Scene:
    """One clip, played by one user (``None``: anonymous)."""

    name: str
    play: Callable[[Director], None]
    user: str | None = None
    description: str = ""


SetupHook = Callable[["Setup"], None]


@dataclass
class Scenario:
    """Users, setup and scenes. Scenes are recorded in order, then joined."""

    title: str
    users: dict[str, User] = field(default_factory=dict)
    size: tuple[int, int] = (1920, 1080)  # Full HD
    transition: str | None = None  # "cut", "fade[:s]" or "crossfade[:s]"
    scenes: list[Scene] = field(default_factory=list)
    setup_hook: SetupHook | None = None
    setup_local: bool = False
    setup_optional: bool = False

    def scene(
        self, name: str, *, user: str | None = None
    ) -> Callable[[Callable[[Director], None]], Callable[[Director], None]]:
        """Add the decorated function as the next scene."""

        def register(play: Callable[[Director], None]) -> Callable[[Director], None]:
            if any(scene.name == name for scene in self.scenes):
                raise ScenarioError(f"scene {name!r} is defined twice")
            if user is not None and user not in self.users:
                known = ", ".join(sorted(self.users)) or "none"
                raise ScenarioError(f"scene {name!r} uses unknown user {user!r} (known: {known})")
            description = (play.__doc__ or "").strip().splitlines()[0] if play.__doc__ else ""
            self.scenes.append(Scene(name, play, user, description))
            return play

        return register

    @property
    def slug(self) -> str:
        """Title as a file name, e.g. "dataset-search"."""
        slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
        return slug or "demo"

    @overload
    def setup(self, hook: SetupHook, /) -> SetupHook: ...

    @overload
    def setup(self, *, local: bool = False, optional: bool = False) -> Callable[[SetupHook], SetupHook]: ...

    def setup(
        self, hook: SetupHook | None = None, /, *, local: bool = False, optional: bool = False
    ) -> SetupHook | Callable[[SetupHook], SetupHook]:
        """Add a hook that seeds data before recording.

        The hook gets a :class:`~ckan_demo.seeding.Setup`. By default it runs
        through the API (token) or locally (ckan.ini), whichever the run has.
        ``local=True``: always locally, inside CKAN, for factories and models.
        ``optional=True``: if seeding can't run or fails, ``record`` warns and
        carries on.
        """

        def register(hook: SetupHook) -> SetupHook:
            if self.setup_hook is not None:
                raise ScenarioError("the scenario already has a setup hook")
            self.setup_hook = hook
            self.setup_local = local
            self.setup_optional = optional
            return hook

        return register(hook) if hook is not None else register

    def select(self, names: list[str] | None) -> list[Scene]:
        """Scenes to record, in scenario order; ``None`` means all."""
        if not names:
            return list(self.scenes)

        known = {scene.name for scene in self.scenes}
        unknown = [name for name in names if name not in known]
        if unknown:
            raise ScenarioError(f"unknown scene(s): {', '.join(unknown)} (known: {', '.join(sorted(known))})")
        return [scene for scene in self.scenes if scene.name in names]


def load_scenario(path: str | Path) -> Scenario:
    """Import a scenario file. It must define exactly one Scenario."""
    path = Path(path).resolve()
    if not path.is_file():
        raise ScenarioError(f"scenario file not found: {path}")

    module_name = f"ckan_demo_scenario_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ScenarioError(f"cannot import {path}")

    module = importlib.util.module_from_spec(spec)
    # Scenarios may import modules next to them.
    sys.path.insert(0, str(path.parent))
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))

    found = [value for value in vars(module).values() if isinstance(value, Scenario)]
    if len(found) != 1:
        raise ScenarioError(f"{path} must define exactly one Scenario, found {len(found)}")
    if not found[0].scenes:
        raise ScenarioError(f"{path}: the scenario has no scenes")
    return found[0]
