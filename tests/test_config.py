from __future__ import annotations

from pathlib import Path

import pytest

from ckan_demo import Scenario
from ckan_demo.cli import DEFAULT_PORTAL, resolve_settings
from ckan_demo.config import Brand, Config, ConfigError, load_config


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


def test_music_is_a_path_and_its_volume_a_number(tmp_path):
    config = load_config(_project(tmp_path, '[tool.ckan-demo]\nmusic = "demo/bed.mp3"\nmusic-volume = -18\n'))

    assert config.music == (tmp_path / "demo" / "bed.mp3").resolve()
    assert config.music_volume == -18.0


@pytest.mark.parametrize("value", ['"-18"', "true"])
def test_music_volume_must_be_a_number(tmp_path, value):
    with pytest.raises(ConfigError, match="music-volume must be a number"):
        load_config(_project(tmp_path, f"[tool.ckan-demo]\nmusic-volume = {value}\n"))


def test_brand_is_a_sub_table(tmp_path):
    scenario = _project(
        tmp_path,
        '[tool.ckan-demo]\nportal = "http://portal.test"\n\n'
        '[tool.ckan-demo.brand]\nlogo = "demo/logo.svg"\nbackground = ["#002b49", "rgb(0 94 151)"]\n'
        'text = "white"\naccent = "#ffb81c"\n',
    )

    config = load_config(scenario)

    assert config.brand == Brand(
        logo=(tmp_path / "demo" / "logo.svg").resolve(),
        background=("#002b49", "rgb(0 94 151)"),
        text="white",
        accent="#ffb81c",
    )
    assert config.keys == {"portal", "brand"}


def test_no_brand_keeps_the_built_in_card():
    assert Brand().overlay() == {}


def test_brand_overlay_settings(tmp_path):
    logo = tmp_path / "logo.svg"
    logo.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")

    settings = Brand(logo=logo, background=("#002b49", "#005e97"), text="#fff", accent="gold").overlay()

    assert settings["logo"].startswith("data:image/svg+xml;base64,")
    assert settings["background"] == "linear-gradient(135deg, #002b49, #005e97)"
    assert settings["text"] == "#fff"
    assert settings["muted"] == "color-mix(in srgb, #fff 80%, transparent)"
    assert settings["accent"] == "gold"
    assert Brand(background=("#002b49",)).overlay() == {"background": "#002b49"}


@pytest.mark.parametrize(("name", "message"), [("missing.png", "is not a file"), ("logo.bmp", "use one of")])
def test_bad_logo_is_an_error(tmp_path, name, message):
    (tmp_path / "logo.bmp").write_bytes(b"BM")

    with pytest.raises(ConfigError, match=message):
        Brand(logo=tmp_path / name).overlay()


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ('brand = "navy"\n', "must be a table"),
        ('[tool.ckan-demo.brand]\ncolour = "navy"\n', "unknown key"),
        ('[tool.ckan-demo.brand]\nbackground = "#12"\n', "must be a CSS colour"),
        ("[tool.ckan-demo.brand]\nbackground = []\n", "a colour or a list"),
        ('[tool.ckan-demo.brand]\ntext = "red; display: none"\n', "must be a CSS colour"),
        ("[tool.ckan-demo.brand]\naccent = 5\n", "must be a CSS colour"),
        ("[tool.ckan-demo.brand]\nlogo = 5\n", "logo must be a non-empty string"),
    ],
)
def test_malformed_brand_is_an_error(tmp_path, table, message):
    if not table.startswith("["):
        table = "[tool.ckan-demo]\n" + table
    with pytest.raises(ConfigError, match=message):
        load_config(_project(tmp_path, table))
