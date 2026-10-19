"""Core CKAN, no extensions: a visitor searches for data and opens a dataset.

    ckan-demo record examples/dataset_search.py --portal https://demo.ckan.org

No users and no data setup: it records whatever datasets the portal has.
"""

from __future__ import annotations

from ckan_demo import Director, Scenario

scenario = Scenario("Dataset search")


@scenario.scene("search")
def search(d: Director) -> None:
    """Search the catalogue and open the first result."""
    d.goto("/")
    d.card("CKAN", "Find open data", "Search, filter and preview datasets.", hold=3)

    d.caption("Start from the dataset search")
    with d.navigates():
        d.click(d.page.get_by_role("link", name="Datasets").first)
    d.pause(1.5)

    d.caption("Narrow the results with the facets on the left")
    facet = d.page.locator(".module-facet .nav-item a, .module-facet li a").first
    if facet.count():
        with d.navigates():
            d.click(facet)
        d.pause(2)

    d.caption("Open a dataset to see its resources")
    first = d.page.locator(".dataset-heading a, .dataset-item a").first
    with d.navigates():
        d.click(first)
    d.pause(3)
    d.caption(None, hold=0.5)
    d.screenshot("dataset-page")
