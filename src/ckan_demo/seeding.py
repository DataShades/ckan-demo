"""Seeding: getting the portal into the state a demo needs.

Two ways, chosen by the scenario, with the same ckanapi client in the hook
(``setup.ckan.action.package_create(...)``):

- **Through the API** (``@scenario.setup``): works against any portal ckan-demo
  can reach, given a sysadmin's API token. ``setup.ckan`` is a ``RemoteCKAN``.
- **In-process** (``@scenario.setup(in_process=True)``): needs the portal's
  ``ckan.ini`` and CKAN installed where ckan-demo runs. The hook runs inside
  CKAN's app context and ``setup.ckan`` is a ``LocalCKAN``; the models,
  toolkit and the test factories CKAN and most extensions have work too.

Either way, the scenario's users are created (or brought in line) first, and
the hook receives them with their CKAN ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import requests
from ckanapi.errors import NotAuthorized

from ckan_demo.portal import ACTION_ERRORS, CKAN, Portal, PortalError, ensure_user

if TYPE_CHECKING:
    from ckan_demo.scenario import Scenario

TOKEN_HINT = "an API token (--api-token or $CKAN_DEMO_API_TOKEN)"
SEEDING_ERRORS = (PortalError, *ACTION_ERRORS, requests.RequestException)


@dataclass(frozen=True)
class Setup:
    """What a setup hook gets."""

    ckan: CKAN  # ckanapi: RemoteCKAN through the API, LocalCKAN in-process
    portal: Portal
    reset: bool  # the run asked for a clean slate (--reset)
    in_process: bool  # the hook runs inside CKAN
    users: dict[str, dict[str, Any]] = field(default_factory=dict)  # role -> CKAN user dict


def requirements(scenario: Scenario) -> str:
    """What a run needs to seed this scenario, for messages."""
    if scenario.setup_in_process:
        return "the portal's ckan.ini (--ckan-ini or $CKAN_INI)"
    return TOKEN_HINT


def can_seed(scenario: Scenario, portal: Portal) -> bool:
    if scenario.setup_in_process:
        return portal.ckan_ini is not None
    return portal.api_token is not None


def run_setup(scenario: Scenario, portal: Portal, *, reset: bool, log: Any = print) -> Setup:
    """Create the scenario's users, then run its setup hook (if any)."""
    if not can_seed(scenario, portal):
        raise PortalError(f"seeding this scenario needs {requirements(scenario)}")

    if scenario.setup_in_process:
        with portal.local_ckan() as ckan:
            return _seed(scenario, portal, ckan, reset=reset, in_process=True, log=log)
    return _seed(scenario, portal, portal.remote(), reset=reset, in_process=False, log=log)


def _seed(scenario: Scenario, portal: Portal, ckan: CKAN, *, reset: bool, in_process: bool, log: Any) -> Setup:
    users = {role: ensure_user(ckan, user) for role, user in scenario.users.items()}
    for user in scenario.users.values():
        log(f"  user {user.name}{' (sysadmin)' if user.sysadmin else ''}")

    setup = Setup(ckan, portal, reset, in_process=in_process, users=users)
    if scenario.setup_hook:
        scenario.setup_hook(setup)
    return setup


def seed_before_recording(
    scenario: Scenario, portal: Portal, *, reset: bool, log: Any = print, warn: Any = print
) -> bool:
    """Seed before ``record``; returns whether it did.

    A scenario whose setup is ``optional`` records the portal as it is when
    seeding can't run or fails, with one warning; otherwise a failure stops
    the run (the scenes need the data).
    """
    if not can_seed(scenario, portal):
        if scenario.setup_hook or scenario.users or reset:
            if scenario.setup_optional:
                log(f"Seeding skipped (it needs {requirements(scenario)}); recording the portal as it is")
            else:
                warn(f"warning: skipping data setup, it needs {requirements(scenario)}")
        return False

    log("Preparing data…")
    try:
        run_setup(scenario, portal, reset=reset, log=log)
    except SEEDING_ERRORS as error:
        if not scenario.setup_optional:
            raise
        warn(f"warning: seeding stopped, {_why(error)}; recording the portal as it is")
        return False
    return True


def _message(error: BaseException) -> str:
    """CKAN's own message: remote errors carry the API's error dict."""
    detail = error.args[0] if error.args else ""
    if isinstance(detail, dict):
        detail = detail.get("message") or {k: v for k, v in detail.items() if k != "__type"}
    return str(detail or type(error).__name__)


def _why(error: BaseException) -> str:
    if isinstance(error, NotAuthorized):
        return f"not allowed on this portal ({_message(error)})"
    return f"{type(error).__name__}: {_message(error)}"
