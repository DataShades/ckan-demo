# Writing scenarios

A scenario file is a Python module that defines one `Scenario`. Keep it next
to the code it demonstrates (for an extension: `ckanext-foo/demo/scenario.py`),
so the demo changes in the same commit as the feature.

## Scenario, users and scenes

```python
from ckan_demo import Director, Scenario, User

scenario = Scenario(
    "ckanext-issues",                      # title: also names the output files
    users={
        "author": User("maria", fullname="Maria Kovalenko"),
        "staff": User("anna-support", fullname="Anna Lindqvist", sysadmin=True),
    },
    size=(1920, 1080),                     # video size (the default: Full HD)
)


@scenario.scene("01-open-ticket", user="author")
def open_ticket(d: Director) -> None:
    """A user opens a ticket."""           # first line shows in `ckan-demo list`
    ...


@scenario.scene("02-browse")               # no user: an anonymous visitor
def browse(d: Director) -> None: ...
```

- **Users** are keyed by a role name you choose. `User` takes `name`,
  `fullname`, `password` (default `correct horse battery staple`),
  `sysadmin` and `email` (default `<name>@example.com`). Before recording,
  ckan-demo creates them or brings them in line, along with any data the
  scenario seeds; see [Seeding](seeding.md).
- **Scenes** are recorded in the order they are declared, each in a fresh
  browser that is already logged in as the scene's user, then joined.
  Prefix names with numbers to keep the order obvious.
- **Scenes build on each other** when the story does (a ticket created in one
  scene is answered in the next), so `--scenes` should pick a prefix of the
  story, or scenes that stand alone.
- The file can import modules that sit next to it.

## The Director

Each scene receives a `Director` bound to its page. Its helpers act like a
person on camera: the pointer glides to its target, typing is key by key, and
there is time to read. Durations are in seconds at `--speed 1`.

| Helper | |
| --- | --- |
| `d.goto(path)` | open a page (path or full URL) and wait until the network is idle |
| `d.click(locator)` | glide to the element, click, short pause |
| `d.type(locator, text, clear=False)` | click into a field and type; `clear=True` empties it first |
| `d.select(locator, value=..., label=...)` | choose an option in a native `<select>` |
| `d.press(key)` | press a key (`"Enter"`, `"Escape"`, `"Control+Enter"`) |
| `d.point(locator)` | glide to an element without clicking, to draw attention |
| `with d.navigates(): ...` | wrap an action that loads a new page; waits for it |
| `d.caption(text, hold=0)` | show a caption bar; `None` hides it |
| `d.card(kicker, title, text="", hold=3)` | full-screen title card, then fade out |
| `d.pause(seconds)` | hold still |
| `d.screenshot(name, locator=None)` | save `screenshots/<name>.png` without the overlay |
| `d.page` | the Playwright `Page`, for everything else |

Locators are ordinary Playwright locators. Prefer what a user sees:

```python
d.click(d.page.get_by_role("button", name="New support ticket"))
d.type(modal.get_by_label("Subject"), "Missing 2025 figures")
```

Use Playwright's `expect` to wait for results; it fails the run loudly instead
of recording a broken scene:

```python
from playwright.sync_api import expect

expect(d.page.locator(".message-card")).to_have_count(1)
```

### What ends up in the video

- **The start of a clip is cut** up to the moment the first `d.goto()`
  finished loading. Anything before it is off camera, which is the place for
  lookups:

  ```python
  def ticket_url(d):
      d.page.goto(d.options.base_url + "/issues/my-tickets")   # off camera
      return d.page.get_by_role("link", name=SUBJECT).get_attribute("href")

  @scenario.scene("03-reply", user="author")
  def reply(d):
      d.goto(ticket_url(d))                                     # the clip starts here
  ```

- **Native dropdowns** (`<select>`) aren't captured by the browser's video;
  `d.select` points at the field and the new value shows in it.
- **Development chrome** (CKAN's debug box, the Flask debug toolbar) is hidden
  automatically.

## Captions and cards

Write captions as short, plain sentences about what the viewer gets, not what
the script does: "New requests wait in Unassigned", not "Click the
Unassigned tab". Give each one time: `hold=2.5` to `3.5` for a sentence. Use
cards to open the video and to mark a change of person or topic.

Record without captions (`--no-captions`) when you will narrate.

## Stills for docs

`d.screenshot("queue")` saves `screenshots/queue.png` in the output folder,
without the pointer or the caption. Pass a locator to capture one element.
