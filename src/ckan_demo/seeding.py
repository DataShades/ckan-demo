"""Seeding: create the scenario's users, then run its setup hook.

The hook gets ``setup.ckan``: a ``RemoteCKAN`` if the run has a token, else a
``LocalCKAN`` from ckan.ini. ``local=True`` hooks always get a ``LocalCKAN``.
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
CKAN_INI_HINT = "the portal's ckan.ini (--ckan-ini or $CKAN_INI)"
SEEDING_ERRORS = (PortalError, *ACTION_ERRORS, requests.RequestException)


@dataclass(frozen=True)
class Setup:
    """Passed to the setup hook."""

    ckan: CKAN
    portal: Portal
    reset: bool  # --reset
    local: bool
    users: dict[str, dict[str, Any]] = field(default_factory=dict)  # role -> CKAN user


def requirements(scenario: Scenario) -> str:
    """What seeding needs, for messages."""
    if scenario.setup_local:
        return CKAN_INI_HINT
    return f"{TOKEN_HINT} or {CKAN_INI_HINT}"


def _seeds_locally(scenario: Scenario, portal: Portal) -> bool:
    """Local if the hook requires it or there's no token."""
    return scenario.setup_local or portal.api_token is None


def can_seed(scenario: Scenario, portal: Portal) -> bool:
    if _seeds_locally(scenario, portal):
        return portal.ckan_ini is not None
    return True


def run_setup(scenario: Scenario, portal: Portal, *, reset: bool, log: Any = print) -> Setup:
    """Create the users, then run the hook."""
    if not can_seed(scenario, portal):
        raise PortalError(f"seeding this scenario needs {requirements(scenario)}")

    if _seeds_locally(scenario, portal):
        with portal.local_ckan() as ckan:
            return _seed(scenario, portal, ckan, reset=reset, local=True, log=log)
    return _seed(scenario, portal, portal.remote(), reset=reset, local=False, log=log)


def _seed(scenario: Scenario, portal: Portal, ckan: CKAN, *, reset: bool, local: bool, log: Any) -> Setup:
    users = {role: ensure_user(ckan, user) for role, user in scenario.users.items()}
    for user in scenario.users.values():
        log(f"  user {user.name}{' (sysadmin)' if user.sysadmin else ''}")

    setup = Setup(ckan, portal, reset, local=local, users=users)
    if scenario.setup_hook:
        scenario.setup_hook(setup)
    return setup


def seed_before_recording(
    scenario: Scenario, portal: Portal, *, reset: bool, log: Any = print, warn: Any = print
) -> bool:
    """Seed for ``record``; return whether it did.

    Optional setups only warn on failure; others raise.
    """
    if not can_seed(scenario, portal):
        if scenario.setup_hook or scenario.users or reset:
            if scenario.setup_optional:
                log(f"Seeding skipped (it needs {requirements(scenario)}); recording the portal as it is")
            else:
                warn(f"warning: skipping data setup, it needs {requirements(scenario)}")
        return False

    log(f"Preparing data… ({'local' if _seeds_locally(scenario, portal) else 'through the API'})")
    try:
        run_setup(scenario, portal, reset=reset, log=log)
    except SEEDING_ERRORS as error:
        if not scenario.setup_optional:
            raise
        warn(f"warning: seeding stopped, {_why(error)}; recording the portal as it is")
        return False
    return True


def _message(error: BaseException) -> str:
    """CKAN's message, also from a remote error dict."""
    detail = error.args[0] if error.args else ""
    if isinstance(detail, dict):
        detail = detail.get("message") or {k: v for k, v in detail.items() if k != "__type"}
    return str(detail or type(error).__name__)


def _why(error: BaseException) -> str:
    if isinstance(error, NotAuthorized):
        return f"not allowed on this portal ({_message(error)})"
    return f"{type(error).__name__}: {_message(error)}"
