"""Portal against the fake CKAN in conftest.py."""

from __future__ import annotations

import pytest
import requests
from ckanapi import ValidationError

from ckan_demo import Portal, PortalError, User, exists
from ckan_demo.portal import ensure_user


def test_remote_sends_the_token_and_returns_the_result(ckan):
    remote = Portal(ckan.url + "/", api_token="secret").remote()

    assert remote.action.echo(answer=42) == {"answer": 42}
    assert ckan.calls == [("echo", {"answer": 42}, "secret")]


def test_action_errors_are_ckanapi_errors(ckan):
    with pytest.raises(ValidationError):
        Portal(ckan.url).remote().action.boom()


def test_name_fields_pass_through(ckan):
    # "name" is a common CKAN field.
    assert Portal(ckan.url).remote().action.echo(name="my-dataset") == {"name": "my-dataset"}


def test_exists_returns_none_for_not_found(ckan):
    remote = Portal(ckan.url).remote()

    assert exists(remote, "user_show", id="ghost") is None
    assert exists(remote, "echo", id="x") == {"id": "x"}


def test_ensure_user_creates_then_updates(ckan):
    remote = Portal(ckan.url, api_token="secret").remote()

    ensure_user(remote, User("anna", fullname="Anna", sysadmin=True, password="pw-1"))
    assert ckan.users["anna"]["sysadmin"] is True
    assert ckan.users["anna"]["email"] == "anna@example.com"

    ensure_user(remote, User("anna", fullname="Anna L.", password="pw-2"))
    assert [call[0] for call in ckan.calls] == ["user_show", "user_create", "user_show", "user_patch"]
    assert ckan.users["anna"]["password"] == "pw-2"
    assert ckan.users["anna"]["sysadmin"] is False


def test_get_json_sends_the_token(ckan):
    portal = Portal(ckan.url, api_token="secret")

    assert portal.get_json("/table", page=1) == {"data": [{"id": 1}], "last_page": 1}
    assert ckan.calls[-1] == ("GET /table?page=1", {}, "secret")


def test_get_json_errors_are_portal_errors(ckan):
    with pytest.raises(PortalError, match="404"):
        Portal(ckan.url).get_json("/missing")


def test_unreachable_portal():
    with pytest.raises(requests.ConnectionError):
        Portal("http://127.0.0.1:9", timeout=2).remote().action.status_show()


def test_local_ckan_needs_a_config():
    with pytest.raises(PortalError, match="--ckan-ini"), Portal("http://x").local_ckan():
        pass
