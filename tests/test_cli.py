from __future__ import annotations

import textwrap

import pytest
from click.testing import CliRunner

from ckan_demo import Scenario, seeding
from ckan_demo.cli import SizeType, cli, resolve_transition
from ckan_demo.config import Config, ConfigError
from ckan_demo.video import Transition

SCENARIO = textwrap.dedent(
    """
    from ckan_demo import Scenario, User

    scenario = Scenario("Issues demo", users={"staff": User("anna-support", sysadmin=True)})

    @scenario.scene("triage", user="staff")
    def triage(d):
        '''Assign and answer a new ticket.'''

    @scenario.scene("browse")
    def browse(d): ...

    @scenario.setup(local=True)
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
    # CKAN's pytest plugin sets CKAN_INI.
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
    assert "Seeding: local (needs the portal's ckan.ini (--ckan-ini or $CKAN_INI))" in result.output


def test_missing_scenario_file_is_a_usage_error(runner, tmp_path):
    result = runner.invoke(cli, ["list", str(tmp_path / "missing.py")])

    assert result.exit_code == 2
    assert "does not exist" in result.output


def _capture_portal(monkeypatch):
    """Fake seeding, recording and joining; keep the portal record was given."""
    seen = {}
    monkeypatch.setattr(seeding, "seed_before_recording", lambda scenario, portal, **kw: seen.update(portal=portal))
    monkeypatch.setattr("ckan_demo.cli.record", lambda *a, **kw: [])
    monkeypatch.setattr("ckan_demo.cli.video.join", lambda clips, target, **kw: target)
    return seen


def test_environment_variables_reach_the_portal(runner, scenario_file, monkeypatch):
    seen = _capture_portal(monkeypatch)
    monkeypatch.setenv("CKAN_INI", "/env/ckan.ini")
    monkeypatch.setenv("CKAN_DEMO_API_TOKEN", "env-token")

    result = runner.invoke(cli, ["record", str(scenario_file), "--portal", "http://flag.test"])

    assert result.exit_code == 0, result.output
    assert str(seen["portal"].ckan_ini) == "/env/ckan.ini"
    assert seen["portal"].api_token == "env-token"
    assert seen["portal"].url == "http://flag.test"


def test_flags_beat_environment_variables(runner, scenario_file, monkeypatch):
    seen = _capture_portal(monkeypatch)
    monkeypatch.setenv("CKAN_INI", "/env/ckan.ini")

    result = runner.invoke(cli, ["record", str(scenario_file), "--ckan-ini", "/flag/ckan.ini"])

    assert result.exit_code == 0, result.output
    assert str(seen["portal"].ckan_ini) == "/flag/ckan.ini"


def test_there_is_no_setup_command(runner):
    result = runner.invoke(cli, ["setup", "x.py"])

    assert result.exit_code == 2
    assert "No such command 'setup'" in result.output


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


@pytest.mark.parametrize(
    ("flag", "scenario_value", "config_value", "expected"),
    [
        (None, None, None, "fade:0.4"),
        (None, None, "cut", "cut"),
        (None, "crossfade:0.8", "cut", "crossfade:0.8"),
        ("fade:0.2", "crossfade:0.8", "cut", "fade:0.2"),
    ],
)
def test_transition_precedence(flag, scenario_value, config_value, expected):

    resolved = resolve_transition(
        Transition.parse(flag) if flag else None,
        Scenario("Demo", transition=scenario_value),
        Config(transition=config_value),
    )

    assert str(resolved) == expected


def test_bad_scenario_transition_is_a_clean_error():

    with pytest.raises(ConfigError, match="the scenario: 'wipe' is not a transition"):
        resolve_transition(None, Scenario("Demo", transition="wipe"), Config())


def test_transition_flag_is_validated(runner, scenario_file):
    result = runner.invoke(cli, ["record", str(scenario_file), "--transition", "wipe"])

    assert result.exit_code == 2
    assert "is not a transition" in result.output


def test_jobs_fall_back_to_one_without_independent_scenes(runner, scenario_file, monkeypatch):
    seen = {}

    def fake_record(scenario, options, scenes, **kwargs):
        seen["jobs"] = kwargs["jobs"]
        return []

    monkeypatch.setattr("ckan_demo.cli.record", fake_record)
    monkeypatch.setattr("ckan_demo.cli.video.join", lambda clips, target, **kw: target)

    result = runner.invoke(cli, ["record", str(scenario_file), "--no-setup", "--jobs", "3"])

    assert result.exit_code == 0, result.output
    assert seen["jobs"] == 1
    assert "recording one at a time" in result.output
