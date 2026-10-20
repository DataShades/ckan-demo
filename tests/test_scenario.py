from __future__ import annotations

import textwrap

import pytest

from ckan_demo import Scenario, User, load_scenario
from ckan_demo.scenario import ScenarioError


def _scenario() -> Scenario:
    return Scenario("Demo", users={"staff": User("anna", sysadmin=True)})


def test_scenes_keep_declaration_order_and_first_doc_line():
    scenario = _scenario()

    @scenario.scene("one", user="staff")
    def one(d):
        """Open the queue.

        Longer notes that the listing should not show.
        """

    @scenario.scene("two")
    def two(d): ...

    assert [scene.name for scene in scenario.scenes] == ["one", "two"]
    assert scenario.scenes[0].description == "Open the queue."
    assert scenario.scenes[0].user == "staff"
    assert scenario.scenes[1].user is None
    assert scenario.scenes[1].description == ""


@pytest.mark.parametrize(
    ("name", "title", "chapter"),
    [
        ("02-staff-triage", "", "Staff triage"),
        ("01_open ticket", "", "Open ticket"),
        ("search", "", "Search"),
        ("007", "", "007"),  # nothing left without the number
        ("01-open-ticket", "Open a ticket", "Open a ticket"),
    ],
)
def test_chapter_titles_come_from_the_title_or_the_name(name, title, chapter):
    scenario = _scenario()
    scenario.scene(name, title=title)(lambda d: None)

    assert scenario.scenes[0].chapter == chapter


def test_duplicate_scene_names_are_rejected():
    scenario = _scenario()
    scenario.scene("one")(lambda d: None)

    with pytest.raises(ScenarioError, match="defined twice"):
        scenario.scene("one")(lambda d: None)


def test_unknown_user_is_rejected():
    with pytest.raises(ScenarioError, match="unknown user 'author'"):
        _scenario().scene("one", user="author")(lambda d: None)


def test_select_keeps_scenario_order_and_rejects_unknown_names():
    scenario = _scenario()
    for name in ("a", "b", "c"):
        scenario.scene(name)(lambda d: None)

    assert [scene.name for scene in scenario.select(["c", "a"])] == ["a", "c"]
    assert len(scenario.select(None)) == 3
    with pytest.raises(ScenarioError, match="unknown scene"):
        scenario.select(["nope"])


def test_setup_hook_is_registered():
    scenario = _scenario()

    @scenario.setup
    def prepare(portal, reset): ...

    assert scenario.setup_hook is prepare


@pytest.mark.parametrize(
    ("title", "slug"),
    [("ckanext-issues", "ckanext-issues"), ("Dataset search: 2026!", "dataset-search-2026"), ("***", "demo")],
)
def test_slug(title, slug):
    assert Scenario(title).slug == slug


def test_user_default_email():
    assert User("maria").email_address == "maria@example.com"
    assert User("maria", email="m@x.org").email_address == "m@x.org"


def test_load_scenario_from_file_with_a_sibling_helper(tmp_path):
    (tmp_path / "helpers.py").write_text("SUBJECT = 'Hello'\n")
    path = tmp_path / "my_demo.py"
    path.write_text(
        textwrap.dedent(
            """
            from ckan_demo import Scenario
            from helpers import SUBJECT

            scenario = Scenario(SUBJECT)

            @scenario.scene("intro")
            def intro(d): ...
            """
        )
    )

    scenario = load_scenario(path)

    assert scenario.title == "Hello"
    assert [scene.name for scene in scenario.scenes] == ["intro"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("x = 1\n", "exactly one Scenario, found 0"),
        ("from ckan_demo import Scenario\na = Scenario('a')\nb = Scenario('b')\n", "found 2"),
        ("from ckan_demo import Scenario\nscenario = Scenario('a')\n", "no scenes"),
    ],
)
def test_load_scenario_rejects_bad_files(tmp_path, body, message):
    path = tmp_path / "bad.py"
    path.write_text(body)

    with pytest.raises(ScenarioError, match=message):
        load_scenario(path)


def test_load_scenario_missing_file(tmp_path):
    with pytest.raises(ScenarioError, match="not found"):
        load_scenario(tmp_path / "nope.py")
