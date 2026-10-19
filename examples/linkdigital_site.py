"""A tour of a company website: linkdigital.com.au.

    ckan-demo record examples/linkdigital_site.py --portal https://linkdigital.com.au

ckan-demo only needs CKAN for seeding and logging in; a scenario without
users or a setup hook can record any site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ckan_demo import Director, Scenario

if TYPE_CHECKING:
    from playwright.sync_api import Locator

SITE = "linkdigital.com.au"

scenario = Scenario("Link Digital", independent_scenes=True, transition="crossfade:0.6")


def first(locator: Locator) -> Locator | None:
    """First visible match, or None. The site repeats its menu in a sticky
    header and a mobile sidebar, both hidden; waiting on those times out."""
    for index in range(locator.count()):
        if locator.nth(index).is_visible():
            return locator.nth(index)
    return None


# The block of FAQ questions after a heading's row (Elementor containers).
FAQ_BLOCK = "xpath=ancestor::div[contains(concat(' ', @class, ' '), ' e-flex ')][1]/following-sibling::div[1]"


def heading(d: Director, name: str) -> Locator | None:
    return first(d.page.get_by_role("heading", name=name))


def start(d: Director) -> None:
    """Off camera, before the scene's first ``d.goto``: check the site and
    accept the cookie banner, which would cover the bottom of every page.
    The browser context keeps the consent cookie for the rest of the scene."""
    if SITE not in d.options.base_url:
        raise RuntimeError(f"record this scenario with --portal https://{SITE}")
    d.page.goto(d.options.base_url + "/", wait_until="networkidle")
    accept = first(d.page.locator("#moove_gdpr_cookie_info_bar .moove-gdpr-infobar-allow-all"))
    if accept:
        accept.click()
        d.page.wait_for_timeout(500)


def open_menu_item(d: Director, menu: str, item: str, fallback: str) -> None:
    """Hover a top menu entry so its dropdown opens, then click an item in it.
    If the dropdown doesn't open (a narrow window shows the mobile menu),
    go to the page directly."""
    top = first(d.page.get_by_role("link", name=menu))
    if top:
        d.point(top)
        d.pause(0.6)
    entry = first(d.page.get_by_role("link", name=item, exact=True))
    if entry:
        with d.navigates():
            d.click(entry)
    else:
        d.goto(fallback)


@scenario.scene("01-home")
def home(d: Director) -> None:
    """Who Link Digital is, then a scroll down the home page."""
    start(d)
    d.goto("/")
    d.card("Since 2001", "Link Digital", "System architects of data and knowledge infrastructure", hold=3.5)

    title = first(d.page.locator("h1"))
    if title:
        d.caption("25 years of data infrastructure for governments and research", hold="read")
        d.spotlight(title, hold=2.5)

    for name, text in (
        ("What we do", "Data portals, hosting, and AI on top of open data"),
        ("What others say about Link Digital", "Trusted by agencies and research institutions"),
        ("Who we work with", "Clients across Australia, Canada, the Pacific and Latin America"),
    ):
        section = heading(d, name)
        if section:
            d.caption(text, hold="read", position="top")
            d.point(section)
            d.pause(1.5)

    d.caption(None, hold=0.3)


@scenario.scene("02-ckan")
def ckan(d: Director) -> None:
    """CKAN services, through the menu."""
    start(d)
    d.goto("/")
    d.caption("CKAN is at the heart of what Link Digital does", hold="read")
    open_menu_item(d, "CKAN & Open Data", "End-to-end CKAN Services", "/services/end-to-end-ckan/")
    d.pause(1.5)

    # The page is an FAQ: each heading's questions are in the block after it.
    for name, text in (
        ("CKAN Consultancy", "Consultancy, from custom builds to migrations"),
        ("CKAN Hosting", "Hosting on AWS, Google Cloud or Azure"),
        ("CKAN Support", "And support once it's live"),
    ):
        section = heading(d, name)
        if section is None:
            continue
        d.caption(text, hold="read", position="top")
        d.spotlight(section.locator(FAQ_BLOCK), hold=2)
        if name == "CKAN Hosting":
            # Questions are <details>; the first in each group starts open.
            question = first(d.page.locator("summary", has_text="cloud-based CKAN hosting"))
            if question:
                d.click(question)
                d.pause(3)

    d.caption(None, hold=0.3)


@scenario.scene("03-case-studies")
def case_studies(d: Director) -> None:
    """The case studies, then one of them."""
    start(d)
    d.goto("/")
    button = first(d.page.get_by_role("link", name="Browse case studies"))
    if button:
        d.caption("Real projects for real data publishers", hold="read")
        with d.navigates():
            d.click(button)
    else:
        d.goto("/case-studies/")
    d.pause(1)

    card = first(d.page.locator("article.post-wrapper"))
    if card is None:
        d.caption(None, hold=0.3)
        return
    d.caption("Each one tells how a portal was built or moved to CKAN", hold="read", position="top")
    d.spotlight(card, hold=2.5)

    link = first(card.locator("h2 a, h3 a")) or first(card.get_by_role("link", name="Read case study"))
    if link:
        with d.navigates():
            d.click(link)
        d.pause(1.5)
        for name, text in (
            ("At a glance", "The project at a glance"),
            ("Technology stack", "And the technology behind it"),
        ):
            section = heading(d, name)
            if section:
                d.caption(text, hold="read", position="top")
                d.point(section)
                d.pause(1.5)

    d.caption(None, hold=0.3)


@scenario.scene("04-ask-ai-and-contact")
def ask_ai_and_contact(d: Director) -> None:
    """Ask AI, then the contact page. Nothing is typed or sent."""
    start(d)
    d.goto("/")
    button = first(d.page.get_by_role("link", name="Discover Ask AI"))
    if button:
        d.caption("New: Ask AI for CKAN portals", hold="read")
        with d.navigates():
            d.click(button)
    else:
        d.goto("/ask-ai/")
    d.pause(1)

    preview = first(d.page.get_by_role("img", name="Ask AI"))
    if preview:
        d.caption("Users ask questions and get verified answers from your own data", hold="read", position="top")
        d.spotlight(preview, hold=3)

    contact = first(d.page.get_by_role("link", name="Get in touch", exact=True))
    if contact:
        d.caption("Want to talk about your data?", hold="read", position="top")
        with d.navigates():
            d.click(contact)
    else:
        d.goto("/get-in-touch/")
    d.pause(1)

    form = first(d.page.locator("form").filter(has_text="How can we help you"))
    if form:
        d.caption("Tell the team what you need", hold="read", position="top")
        d.spotlight(form, hold=2.5)
    offices = first(d.page.locator(".ldc-offices"))
    if offices:
        d.caption("Offices in Canberra and Toronto", hold="read", position="top")
        d.point(offices)
        d.pause(1.5)

    d.caption(None, hold=0.3)
    d.card("", "Link Digital", SITE, hold=3.5)
