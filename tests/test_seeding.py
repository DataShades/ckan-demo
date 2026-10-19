from __future__ import annotations

import contextlib

import pytest

from ckan_demo import Portal, PortalError, Scenario, Setup, User, seeding
from ckan_demo.scenario import ScenarioError


def _scenario() -> Scenario:
    return Scenario("Demo", users={"staff": User("anna", sysadmin=True), "author": User("maria")})


def test_setup_decorator_defaults_to_the_api():
    scenario = _scenario()

    @scenario.setup
    def prepare(setup): ...

    assert scenario.setup_hook is prepare
    assert scenario.setup_in_process is False


def test_setup_decorator_in_process():
    scenario = _scenario()

    @scenario.setup(in_process=True)
    def prepare(setup): ...

    assert scenario.setup_hook is prepare
    assert scenario.setup_in_process is True


def test_only_one_setup_hook():
    scenario = _scenario()
    scenario.setup(lambda setup: None)

    with pytest.raises(ScenarioError, match="already has a setup hook"):
        scenario.setup(in_process=True)(lambda setup: None)


def test_api_seeding_creates_users_and_passes_them_to_the_hook(ckan):
    scenario = _scenario()
    received: list[Setup] = []
    scenario.setup(received.append)

    seeding.run_setup(scenario, Portal(ckan.url, api_token="secret"), reset=True, log=lambda line: None)

    (setup,) = received
    assert setup.reset is True
    assert setup.in_process is False
    assert setup.ckan.action.echo(ok=1) == {"ok": 1}  # the RemoteCKAN client
    assert setup.users["staff"]["name"] == "anna"
    assert setup.users["staff"]["sysadmin"] is True
    assert set(setup.users) == {"staff", "author"}


def test_users_are_created_even_without_a_hook(ckan):
    seeding.run_setup(_scenario(), Portal(ckan.url, api_token="secret"), reset=False, log=lambda line: None)

    assert set(ckan.users) == {"anna", "maria"}


def test_in_process_seeding_runs_inside_ckan(monkeypatch):
    entered: list[str] = []
    local = object()  # stands in for the LocalCKAN that local_ckan() yields

    @contextlib.contextmanager
    def fake_local_ckan(self):
        entered.append("in")
        yield local
        entered.append("out")

    def fake_ensure(ckan, user):
        assert ckan is local, "users must be created through the in-process client"
        assert entered == ["in"], "users must be created inside the CKAN app context"
        return {"name": user.name, "id": f"id-{user.name}"}

    monkeypatch.setattr(Portal, "local_ckan", fake_local_ckan)
    monkeypatch.setattr(seeding, "ensure_user", fake_ensure)

    scenario = _scenario()
    received: list[Setup] = []

    @scenario.setup(in_process=True)
    def prepare(setup):
        assert entered == ["in"], "the hook must run inside the CKAN app context"
        received.append(setup)

    seeding.run_setup(scenario, Portal("http://x", ckan_ini="ckan.ini"), reset=False, log=lambda line: None)

    assert entered == ["in", "out"]
    assert received[0].in_process is True
    assert received[0].ckan is local
    assert received[0].users["author"]["id"] == "id-maria"


@pytest.mark.parametrize(
    ("in_process", "portal", "message"),
    [
        (True, Portal("http://x", api_token="secret"), "--ckan-ini"),
        (False, Portal("http://x", ckan_ini="ckan.ini"), "API token"),
    ],
)
def test_missing_requirements_are_explained(in_process, portal, message):
    scenario = _scenario()
    scenario.setup(in_process=in_process)(lambda setup: None)

    assert seeding.can_seed(scenario, portal) is False
    with pytest.raises(PortalError, match=message):
        seeding.run_setup(scenario, portal, reset=False)
