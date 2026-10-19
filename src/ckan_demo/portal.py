"""Access to the portal through ckanapi: ``RemoteCKAN`` with a token, or
``LocalCKAN`` locally with the portal's ckan.ini.
"""

from __future__ import annotations

import contextlib
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, Union

import requests
from ckanapi import LocalCKAN, NotFound, RemoteCKAN
from ckanapi import errors as ckanapi_errors

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ckan_demo.scenario import User

CKAN = Union[RemoteCKAN, LocalCKAN]  # noqa: UP007 - runtime alias, Python 3.10

ACTION_ERRORS: tuple[type[Exception], ...] = (
    ckanapi_errors.CKANAPIError,
    ckanapi_errors.NotAuthorized,
    ckanapi_errors.NotFound,
    ckanapi_errors.ValidationError,
    ckanapi_errors.SearchQueryError,
    ckanapi_errors.SearchError,
    ckanapi_errors.SearchIndexError,
)


class PortalError(Exception):
    """Portal unreachable, or missing setup for this run."""


def _user_agent() -> str:
    try:
        return f"ckan-demo/{version('ckan-demo')}"
    except PackageNotFoundError:  # pragma: no cover - running from a source tree
        return "ckan-demo"


class Portal:
    """Portal URL, sysadmin API token and ckan.ini."""

    def __init__(
        self, url: str, api_token: str | None = None, ckan_ini: Path | None = None, timeout: float = 30
    ) -> None:
        self.url = url.rstrip("/")
        self.api_token = api_token
        self.ckan_ini = ckan_ini
        self.timeout = timeout

    def remote(self) -> RemoteCKAN:
        """ckanapi client for the action API."""
        return RemoteCKAN(self.url, apikey=self.api_token, user_agent=_user_agent())

    def get_json(self, path: str, **params: Any) -> Any:
        """GET a non-action JSON page, e.g. a table's data endpoint."""
        headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        if self.api_token:
            headers["Authorization"] = self.api_token
        try:
            response = requests.get(self.url + path, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            raise PortalError(f"GET {self.url}{path}: {error}") from error

    @contextlib.contextmanager
    def local_ckan(self) -> Iterator[LocalCKAN]:
        """Load CKAN locally and yield a ``LocalCKAN`` (as the site user).

        Models, toolkit and factories work inside the block.
        """
        if not self.ckan_ini:
            raise PortalError("this needs the portal's ckan.ini: pass --ckan-ini or set $CKAN_INI")

        # CKAN is only needed for local seeding.
        from ckan.cli import load_config  # noqa: PLC0415
        from ckan.config.middleware import make_app  # noqa: PLC0415

        app = make_app(load_config(str(self.ckan_ini)))
        with app._wsgi_app.test_request_context():
            yield LocalCKAN()


def exists(ckan: CKAN, action: str, /, **data: Any) -> dict[str, Any] | None:
    """The action's result, or None if CKAN says Not Found."""
    try:
        return ckan.call_action(action, data)
    except NotFound:
        return None


def ensure_user(ckan: CKAN, user: User) -> dict[str, Any]:
    """Create ``user`` or update it, resetting password and sysadmin flag."""
    wanted = {
        "fullname": user.fullname or user.name,
        "email": user.email_address,
        "password": user.password,
        "sysadmin": user.sysadmin,
    }
    if exists(ckan, "user_show", id=user.name) is None:
        return ckan.call_action("user_create", {"name": user.name, **wanted})
    return ckan.call_action("user_patch", {"id": user.name, **wanted})
