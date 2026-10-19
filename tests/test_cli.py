from __future__ import annotations

import textwrap

import pytest
from click.testing import CliRunner

from ckan_demo import seeding
from ckan_demo.cli import SizeType, cli

SCENARIO = textwrap.dedent(
    """
    from ckan_demo import Scenario, User

    scenario = Scenario("Issues demo", users={"staff": User("anna-support", sysadmin=True)})

    @scenario.scene("triage", user="staff")
    def triage(d):
        '''Assign and answer a new ticket.'''

    @scenario.scene("browse")
    def browse(d): ...

    @scenario.setup(in_process=True)
    def prepare(setup): ...
    """
)


@pytest.fixture
def scenario_file(tmp_path):
    path = tmp_path / "issues.py"
    path.write_text(SCENARIO)
    return path


@pytest.fixture
def runner(monkeypatch):
    # CKAN's pytest plugin sets CKAN_INI; start every test from a clean slate.
    monkeypatch.delenv("CKAN_INI", raising=False)
    monkeypatch.delenv("CKAN_DEMO_API_TOKEN", raising=False)
    return CliRunner()


def test_list_shows_users_scenes_and_seeding(runner, scenario_file):
    result = runner.invoke(cli, ["list", str(scenario_file)])

    assert result.exit_code == 0, result.output
    assert "Issues demo" in result.output
    assert "anna-support (sysadmin)" in result.output
    assert "Assign and answer a new ticket." in result.output
    assert "anonymous" in result.output
    assert "Seeding: in-process (needs the portal's ckan.ini (--ckan-ini or $CKAN_INI))" in result.output


def test_setup_without_requirements_explains_what_is_needed(runner, scenario_file):
    result = runner.invoke(cli, ["setup", str(scenario_file)])

    assert result.exit_code == 1
    assert "Error: seeding this scenario needs" in result.output
    assert "--ckan-ini" in result.output


def test_missing_scenario_file_is_a_usage_error(runner, tmp_path):
    result = runner.invoke(cli, ["list", str(tmp_path / "missing.py")])

    assert result.exit_code == 2
    assert "does not exist" in result.output


def test_environment_variables_reach_the_portal(runner, scenario_file, monkeypatch):
    seen = {}
    monkeypatch.setattr(seeding, "run_setup", lambda scenario, portal, **kw: seen.update(portal=portal))
    monkeypatch.setenv("CKAN_INI", "/env/ckan.ini")
    monkeypatch.setenv("CKAN_DEMO_API_TOKEN", "env-token")

    result = runner.invoke(cli, ["setup", str(scenario_file), "--portal", "http://flag.test"])

    assert result.exit_code == 0, result.output
    assert str(seen["portal"].ckan_ini) == "/env/ckan.ini"
    assert seen["portal"].api_token == "env-token"
    assert seen["portal"].url == "http://flag.test"


def test_flags_beat_environment_variables(runner, scenario_file, monkeypatch):
    seen = {}
    monkeypatch.setattr(seeding, "run_setup", lambda scenario, portal, **kw: seen.update(portal=portal))
    monkeypatch.setenv("CKAN_INI", "/env/ckan.ini")

    result = runner.invoke(cli, ["setup", str(scenario_file), "--ckan-ini", "/flag/ckan.ini"])

    assert result.exit_code == 0, result.output
    assert str(seen["portal"].ckan_ini) == "/flag/ckan.ini"


@pytest.mark.parametrize(("value", "size"), [("1920x1080", (1920, 1080)), (" 1280 X 720 ", (1280, 720))])
def test_size_type_accepts(value, size):
    assert SizeType().convert(value, None, None) == size


@pytest.mark.parametrize("value", ["1920by1080", "0x1080", "1920x", "big"])
def test_size_type_rejects(runner, scenario_file, value):
    result = runner.invoke(cli, ["record", str(scenario_file), "--size", value])

    assert result.exit_code == 2
    assert "is not a size like 1920x1080" in result.output


def test_speed_must_be_positive(runner, scenario_file):
    result = runner.invoke(cli, ["record", str(scenario_file), "--speed", "0"])

    assert result.exit_code == 2
    assert "--speed" in result.output


def test_help_mentions_the_environment_variables(runner):
    result = runner.invoke(cli, ["record", "--help"])

    assert result.exit_code == 0
    assert "CKAN_DEMO_API_TOKEN" in result.output
    assert "CKAN_INI" in result.output
