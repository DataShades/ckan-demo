"""In-process seeding with CKAN's own test factories.

    ckan-demo record examples/factories_seed.py --ckan-ini /path/to/ckan.ini

Needs CKAN, with its development requirements (factory_boy, pytest), installed
where ckan-demo runs, and the portal's ckan.ini. No API token: the demo
user and the data are created inside CKAN.
"""

from __future__ import annotations

from ckan_demo import Director, Scenario, Setup, User, exists

ORG = "demo-environment-agency"
DATASET = "demo-river-levels"

scenario = Scenario("Seeded with factories", users={"editor": User("demo-editor", fullname="Eli Editor")})


@scenario.setup(in_process=True)
def seed(setup: Setup) -> None:
    """Runs inside CKAN: setup.ckan (ckanapi's LocalCKAN), the toolkit, the
    models and the test factories all work here."""
    from ckan.tests import factories

    if setup.reset:
        if exists(setup.ckan, "package_show", id=DATASET):
            setup.ckan.action.dataset_purge(id=DATASET)
        if exists(setup.ckan, "organization_show", id=ORG):
            setup.ckan.action.organization_purge(id=ORG)

    if exists(setup.ckan, "package_show", id=DATASET):
        return  # already seeded

    # Factories fill every field you leave out with fake data (lorem ipsum,
    # stock photos): pass presentable values for everything that shows.
    editor = setup.users["editor"]
    org = factories.Organization(
        name=ORG,
        title="Environment Agency",
        description="Rivers, air and land monitoring.",
        image_url="",
        users=[{"name": editor["name"], "capacity": "editor"}],
    )
    dataset = factories.Dataset(
        name=DATASET,
        title="River levels, hourly",
        notes="Water levels from 120 river gauges, updated every hour.",
        owner_org=org["id"],
        tags=[{"name": "rivers"}, {"name": "monitoring"}],
    )
    factories.Resource(
        package_id=dataset["id"],
        name="river-levels-2026.csv",
        format="CSV",
        description="Hourly readings for 2026, one row per gauge and hour.",
        url="https://example.com/river-levels-2026.csv",
    )


@scenario.scene("dataset", user="editor")
def dataset_page(d: Director) -> None:
    """The editor opens the seeded dataset."""
    d.goto(f"/dataset/{DATASET}")
    d.caption("Seeded in-process with CKAN's own factories", hold=3)
    d.point(d.page.get_by_role("heading", level=1, name="River levels, hourly"))
    d.pause(2)
    d.caption(None, hold=0.3)
    d.screenshot("seeded-dataset")
