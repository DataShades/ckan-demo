"""Talking to the CKAN portal being demoed, through ckanapi.

The same ckanapi interface works both ways a scenario can seed:

- :meth:`Portal.remote` returns a ``RemoteCKAN`` that calls the action API
  with a sysadmin's token, so ckan-demo works against any portal it can reach;
- :meth:`Portal.local_ckan` runs CKAN in-process (given the portal's
  ``ckan.ini``) and yields a ``LocalCKAN``, acting as the site user.

Either way: ``ckan.action.package_create(name=..., ...)``.
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

CKAN = Union[RemoteCKAN, LocalCKAN]  # noqa: UP007 - a runtime alias, valid on Python 3.10

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
    """The portal could not be reached, or is set up wrong for this run."""


def _user_agent() -> str:
    try:
        return f"ckan-demo/{version('ckan-demo')}"
    except PackageNotFoundError:  # pragma: no cover - running from a source tree
        return "ckan-demo"


class Portal:
    """A CKAN portal: its URL, a sysadmin API token, and its ckan.ini."""

    def __init__(
        self, url: str, api_token: str | None = None, ckan_ini: Path | None = None, timeout: float = 30
    ) -> None:
        self.url = url.rstrip("/")
        self.api_token = api_token
        self.ckan_ini = ckan_ini
        self.timeout = timeout

    def remote(self) -> RemoteCKAN:
        """A ckanapi client for the action API, authenticated with the token."""
        return RemoteCKAN(self.url, apikey=self.api_token, user_agent=_user_agent())

    def get_json(self, path: str, **params: Any) -> Any:
        """GET a JSON page that isn't an action (e.g. a table's data endpoint)."""
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
        """Run CKAN in-process against the portal's database.

        Yields a ``LocalCKAN`` acting as the site user; inside the block,
        CKAN's models, toolkit and test factories work too. Needs CKAN
        importable and the portal's ``ckan.ini``.
        """
        if not self.ckan_ini:
            raise PortalError("this needs the portal's ckan.ini: pass --ckan-ini or set $CKAN_INI")

        # Imported here: CKAN is only needed by scenarios that seed in-process.
        from ckan.cli import load_config  # noqa: PLC0415
        from ckan.config.middleware import make_app  # noqa: PLC0415

        app = make_app(load_config(str(self.ckan_ini)))
        with app._wsgi_app.test_request_context():
            yield LocalCKAN()


def exists(ckan: CKAN, action: str, /, **data: Any) -> dict[str, Any] | None:
    """``ckan.call_action(action, data)``, or None when CKAN says Not Found."""
    try:
        return ckan.call_action(action, data)
    except NotFound:
        return None


def ensure_user(ckan: CKAN, user: User) -> dict[str, Any]:
    """Create ``user``, or bring an existing account in line with it.

    The password and sysadmin flag are always reset, so the browser can
    log in as the user however the account was left.
    """
    wanted = {
        "fullname": user.fullname or user.name,
        "email": user.email_address,
        "password": user.password,
        "sysadmin": user.sysadmin,
    }
    if exists(ckan, "user_show", id=user.name) is None:
        return ckan.call_action("user_create", {"name": user.name, **wanted})
    return ckan.call_action("user_patch", {"id": user.name, **wanted})
