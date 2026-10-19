"""Core CKAN, as an anonymous visitor: search, filter, explore, browse.

    ckan-demo record examples/dataset_search.py --portal https://demo.ckan.org
    ckan-demo record examples/dataset_search.py --api-token "$TOKEN" --reset

The scenes discover their content as they go (a search term from the portal's
own datasets, the first facet, the first resource…) and skip what a portal
doesn't have, so they work on any CKAN site.

Seeding is optional. With a sysadmin's API token, it adds an organisation and
two datasets with real CSV files (data/*.csv) through the API, so the video
shows known content. Without a token, or without permission to create them,
ckan-demo says so and records the portal as it is.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from ckan_demo import Director, Scenario, Setup, exists

if TYPE_CHECKING:
    from playwright.sync_api import Locator

scenario = Scenario("Dataset search")

DATA = Path(__file__).parent / "data"
ORG = {
    "name": "demo-environment-agency",
    "title": "Environment Agency",
    "description": "Rivers, air and land monitoring.",
}
DATASETS = [
    {
        "name": "demo-river-levels",
        "title": "River levels, hourly",
        "notes": "Water levels from river gauges across the country, updated every hour.",
        "tags": [{"name": "rivers"}, {"name": "monitoring"}],
        "file": DATA / "river-levels-2026.csv",
        "description": "Hourly readings from four river gauges, one row per gauge and hour.",
    },
    {
        "name": "demo-air-quality",
        "title": "Air quality, daily averages",
        "notes": "Daily PM2.5, PM10 and NO2 averages from city monitoring stations.",
        "tags": [{"name": "air"}, {"name": "monitoring"}],
        "file": DATA / "air-quality-2026.csv",
        "description": "Daily averages per station, in micrograms per cubic metre.",
    },
]


@scenario.setup(optional=True)
def seed(setup: Setup) -> None:
    """Through the API (ckanapi's RemoteCKAN), so it also works on a remote
    portal you have a sysadmin token for."""
    ckan = setup.ckan
    if setup.reset:
        for spec in DATASETS:
            if exists(ckan, "package_show", id=spec["name"]):
                ckan.action.dataset_purge(id=spec["name"])
        if exists(ckan, "organization_show", id=ORG["name"]):
            ckan.action.organization_purge(id=ORG["name"])

    if not exists(ckan, "organization_show", id=ORG["name"]):
        ckan.action.organization_create(**ORG)

    for spec in DATASETS:
        if exists(ckan, "package_show", id=spec["name"]):
            continue
        dataset = ckan.action.package_create(
            name=spec["name"], title=spec["title"], notes=spec["notes"], tags=spec["tags"], owner_org=ORG["name"]
        )
        # A real file, uploaded into the portal's storage (it needs
        # ckan.storage_path); ckanapi turns an open file into an upload.
        with spec["file"].open("rb") as data:
            ckan.action.resource_create(
                package_id=dataset["id"],
                name=spec["file"].name,
                format="CSV",
                description=spec["description"],
                upload=data,
            )


DATASET_LINKS = ".dataset-heading a"
FACET_LINKS = ".module-facet .nav-item a, .module-facet li a, .filters"
# Organisation cards: .groups-cards (CKAN 2.11+), .media-item (earlier).
ORG_LINKS = ".groups-cards a[href*='/organization/'], .media-item a[href*='/organization/']"


def first(locator: Locator) -> Locator | None:
    """The first match, or None when the portal doesn't have it."""
    return locator.first if locator.count() else None


def search_term(d: Director) -> str:
    """A word from the portal's newest dataset title, looked up off camera
    (before the first ``d.goto``, so it's cut from the clip)."""
    d.page.goto(d.options.base_url + "/dataset/?sort=metadata_modified+desc", wait_until="networkidle")
    title = d.page.locator(DATASET_LINKS).first.inner_text() if d.page.locator(DATASET_LINKS).count() else ""
    words = [word for word in re.findall(r"[^\W\d_]{4,}", title)]
    return words[0].lower() if words else "data"


@scenario.scene("01-search")
def search(d: Director) -> None:
    """Search the catalogue, narrow it with a facet and change the order."""
    term = search_term(d)

    d.goto("/")
    d.card("CKAN", "Find open data", "Search, filter and explore datasets.", hold=3.5)

    d.caption("Start with a search", hold="read")
    with d.navigates():
        d.click(d.page.get_by_role("link", name="Datasets").first)

    search_box = d.page.get_by_placeholder(re.compile("Search", re.I)).first
    d.type(search_box, term, clear=True)
    with d.navigates():
        d.press("Enter")
    d.caption(f"Here's what matches “{term}”", hold=3)

    facet = first(d.page.locator(FACET_LINKS))

    if facet:
        d.caption("Use the filters on the left to narrow it down", hold="read")
        with d.navigates():
            d.click(facet)
        d.pause(2)

    order = first(d.page.locator("#field-order-by"))
    if order and order.locator("option[value='metadata_modified desc']").count():
        d.caption("Sort by last modified to see the newest first", hold="read")
        with d.navigates():
            d.select(order, value="metadata_modified desc")
        d.pause(2)

    d.caption(None, hold=0.3)


@scenario.scene("02-dataset")
def dataset(d: Director) -> None:
    """Open a dataset, then one of its resources."""
    d.goto("/dataset/")

    link = first(d.page.locator(DATASET_LINKS))
    if link is None:
        d.caption("No public datasets here yet", hold=3)
        return

    d.caption("Open a dataset to see what's in it", hold="read")
    with d.navigates():
        d.click(link)
    d.pause(2)

    resources = d.page.locator(".resource-item")
    if resources.count():
        count = resources.count()
        d.caption(f"This one has {count} resource{'s' if count != 1 else ''}, the actual data", hold="read")
        d.point(resources.first)
        d.pause(1.5)

        resource_link = first(resources.first.locator("a.heading, a[href*='/resource/']"))
        if resource_link:
            d.caption("Each resource has its own page", hold="read")
            with d.navigates():
                d.click(resource_link)
            d.pause(3)
            d.screenshot("resource-page")
    else:
        d.screenshot("dataset-page")

    d.caption(None, hold=0.3)


@scenario.scene("03-organisations")
def organisations(d: Director) -> None:
    """Browse the publishers, and the dark theme where the portal has one."""
    d.goto("/organization/")

    org = first(d.page.locator(ORG_LINKS))
    if org:
        d.caption("Datasets belong to organisations", hold="read")
        d.point(org)
        d.pause(1.5)
        with d.navigates():
            d.click(org)
        d.caption("Open one to see everything it publishes", hold="read")

    theme = first(d.page.get_by_role("button", name=re.compile("dark theme", re.I)))
    if theme:
        d.caption("There's a dark theme too", hold="read")
        d.click(theme)
        d.pause(2.5)

    d.caption(None, hold=0.3)
    host = re.sub(r"^https?://", "", d.options.base_url)
    d.card("", "Find open data", host, hold=3.5)
