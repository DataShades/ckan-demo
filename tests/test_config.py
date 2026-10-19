from __future__ import annotations

from pathlib import Path

import pytest

from ckan_demo import Scenario
from ckan_demo.cli import DEFAULT_PORTAL, resolve_settings
from ckan_demo.config import Config, ConfigError, load_config


def _project(tmp_path: Path, table: str) -> Path:
    """pyproject.toml at the root, scenario in demo/."""
    (tmp_path / "pyproject.toml").write_text(f"[project]\nname = 'ckanext-foo'\n\n{table}")
    scenario = tmp_path / "demo" / "scenario.py"
    scenario.parent.mkdir()
    scenario.write_text("")
    return scenario


def test_nearest_pyproject_is_used_and_paths_are_relative_to_it(tmp_path):
    scenario = _project(
        tmp_path,
        '[tool.ckan-demo]\nportal = "http://portal.test"\nckan-ini = "../config/ckan.ini"\noutput = "demo/output"\n'
        'transition = "cut"\n',
    )

    config = load_config(scenario)

    assert config.source == tmp_path / "pyproject.toml"
    assert config.portal == "http://portal.test"
    assert config.ckan_ini == (tmp_path.parent / "config" / "ckan.ini").resolve()
    assert config.output == (tmp_path / "demo" / "output").resolve()
    assert config.transition == "cut"
    assert config.keys == {"portal", "ckan-ini", "output", "transition"}


def test_pyproject_without_the_table_means_no_settings(tmp_path):
    config = load_config(_project(tmp_path, ""))

    assert config.keys == frozenset()
    assert config.portal is None


def test_no_pyproject_at_all(tmp_path, monkeypatch):
    lonely = tmp_path / "scenario.py"
    lonely.write_text("")
    monkeypatch.setattr("ckan_demo.config.find_pyproject", lambda start: None)

    assert load_config(lonely) == Config()


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ('[tool.ckan-demo]\nportl = "x"\n', "unknown key"),
        ("[tool.ckan-demo]\nportal = 5000\n", "must be a non-empty string"),
        ('[tool.ckan-demo]\nportal = ""\n', "must be a non-empty string"),
        ("[tool.ckan-demo\n", "pyproject.toml"),
    ],
)
def test_malformed_config_is_an_error(tmp_path, table, message):
    with pytest.raises(ConfigError, match=message):
        load_config(_project(tmp_path, table))


def test_command_line_beats_config_beats_defaults():
    scenario = Scenario("My demo")
    config = Config(portal="http://config.test", ckan_ini=Path("/config.ini"), output=Path("/config-out"))
    nothing = {"portal": None, "api_token": None, "ckan_ini": None}

    # Defaults only.
    portal, output = resolve_settings(scenario, Config(), **nothing)
    assert (portal.url, portal.ckan_ini, output) == (DEFAULT_PORTAL, None, Path("demo-output/my-demo"))

    # Config fills the gaps.
    portal, output = resolve_settings(scenario, config, **nothing)
    assert (portal.url, portal.ckan_ini, output) == ("http://config.test", Path("/config.ini"), Path("/config-out"))

    # Command line (flags or env vars) wins.
    portal, output = resolve_settings(
        scenario,
        config,
        portal="http://flag.test",
        api_token="t",
        ckan_ini=Path("/flag.ini"),
        output=Path("/flag-out"),
    )
    assert (portal.url, portal.ckan_ini, output) == ("http://flag.test", Path("/flag.ini"), Path("/flag-out"))
