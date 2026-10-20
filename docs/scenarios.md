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
    transition="crossfade:0.6",            # between scenes (the default: fade:0.4)
    independent_scenes=False,              # True lets --jobs record scenes at once
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
- **Each scene is a chapter** in the video. The title comes from the name
  without its number (`02-staff-triage` is "Staff triage"); pass
  `title="Staff triage and reply"` to `scenario.scene` for a different one.
  See [Chapters](tips.md#chapters).
- **Scenes build on each other** when the story does (a ticket created in one
  scene is answered in the next), so `--scenes` should pick a prefix of the
  story, or scenes that stand alone.
- The file can import modules that sit next to it.

## The Director

Each scene receives a `Director` bound to its page. Its helpers act like a
person on camera: the page scrolls smoothly to bring an off-screen target to
the middle, the pointer glides to it on a slight curve, easing in and out,
typing is key by key, and there is time to read. Durations are in seconds at
`--speed 1`.

| Helper | |
| --- | --- |
| `d.goto(path)` | open a page (path or full URL) and wait until the network is idle |
| `d.click(locator)` | glide to the element, click, short pause |
| `d.type(locator, text, clear=False)` | click into a field and type; `clear=True` empties it first |
| `d.select(locator, value=..., label=...)` | choose an option in a native `<select>` |
| `d.press(key, badge=None)` | press a key (`"Enter"`, `"Escape"`, `"Control+Enter"`). Shortcuts show a key badge (<kbd>Ctrl</kbd> + <kbd>Enter</kbd>) next to the caption just before the press; `badge=True` or `False` turns it on or off for any key |
| `d.point(locator)` | glide to an element without clicking, to draw attention |
| `d.spotlight(locator, hold=2, padding=8)` | dim the rest of the page around an element for `hold` seconds, to say "look here". The pointer and caption stay on top |
| `with d.navigates(): ...` | wrap an action that loads a new page; waits for it |
| `d.caption(text, hold=0, position="bottom")` | show a caption bar; `None` hides it. `hold=` seconds keeps the page still, `hold="read"` for the caption's reading time. The previous caption stays up until it could be read. `position=` is `"bottom"`, `"top"` or `"auto"` (see below) |
| `d.card(kicker, title, text="", hold=3)` | full-screen title card; it fades out at the next action or use of `d.page`, so a card that ends the scene stays up. Right after the scene's first `d.goto`, it's up from the clip's first frame |
| `d.pause(seconds)` | hold still |
| `d.screenshot(name, locator=None)` | save `screenshots/<name>.png` without the overlay |
| `d.page` | the Playwright `Page`, for everything else. Using it hides a card that is still up |

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
Unassigned tab". You don't need to time them: a caption stays on screen until
it could be read (about 0.6 s plus a third of a second per word, at least
1.8 s), and time spent on clicks and typing counts towards it.

To have the viewer read a caption *before* the next action starts, hold the
page still for its reading time with `hold="read"`; it follows the wording
and `--speed`, so there are no numbers to keep in sync. Use `hold=<seconds>`
for a deliberate longer look, e.g. at a page of results:

```python
d.caption("Use the filters on the left to narrow it down", hold="read")
d.click(facet)
d.caption(f"Here's what matches “{term}”", hold=3)
```

Captions sit at the bottom. When one would cover what the scene is about,
put it at the top with `position="top"`, or use `position="auto"`: it starts
at the bottom (at the top if the pointer is already there) and moves to the
top, with a quick fade, when the pointer is about to go to something it
covers. It stays there until the next caption.

```python
d.caption("Assign the ticket to yourself", position="auto")
d.click(page.get_by_role("button", name="Assign to me"))  # low on the page: the caption moves up
```

`auto` only knows where the pointer goes. Something that appears under the
caption without being clicked, such as a toast or a dialog's buttons, needs
`position="top"`.

Use cards to open the video and to mark a change of person or topic. Their logo
and colours come from `[tool.ckan-demo.brand]` (see the
[README](../README.md#configuration)).

Record without captions (`--no-captions`) when you will narrate.

## Screenshots for docs

`d.screenshot("queue")` saves `screenshots/queue.png` in the output folder,
without the pointer or the caption. Pass a locator to capture one element.
