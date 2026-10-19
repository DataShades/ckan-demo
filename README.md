# ckan-demo

Record demo videos of a CKAN portal or a CKAN extension from a short Python
**scenario**: who appears in the demo, what data it needs, and the scenes they
play.

`ckan-demo` drives a real browser with [Playwright](https://playwright.dev),
logs each person in off camera, draws a mouse pointer and click ripples,
types at a human pace, shows captions and title cards, and joins the scenes
into one MP4. Re-recording after a UI change is one command.

It is a standalone tool, not a CKAN plugin: it records any portal it can
reach. Seeding the data a demo needs goes through
[ckanapi](https://github.com/ckan/ckanapi): over the action API, or in-process
alongside the test factories your extension already has.

## Install

```sh
pip install -e .
playwright install chromium
```

You also need `ffmpeg` on `PATH` to join the scenes (without it you get one
`.webm` per scene).

## Quick start

A scenario is a Python file:

```python
# demo.py
from ckan_demo import Director, Scenario, User

scenario = Scenario("Dataset search", users={"visitor": User("demo-visitor", fullname="Dana Visitor")})


@scenario.scene("search", user="visitor")
def search(d: Director) -> None:
    """Dana searches the catalogue."""
    d.goto("/dataset/")
    d.card("CKAN", "Find open data", hold=3)
    d.caption("Search by keyword")
    d.type(d.page.get_by_placeholder("Search datasets"), "population")
    d.press("Enter")
    d.pause(3)
```

Record it:

```sh
export CKAN_DEMO_API_TOKEN=...   # a sysadmin's API token, to create demo-visitor
ckan-demo record demo.py --portal http://127.0.0.1:5000
# Video: demo-output/dataset-search/dataset-search.mp4
```

[`examples/dataset_search.py`](examples/dataset_search.py) needs no users or
token at all; try it against any CKAN site.
[`examples/factories_seed.py`](examples/factories_seed.py) seeds an
organisation and a dataset in-process with CKAN's factories
(`--ckan-ini`, no token).

## Commands

| Command | |
| --- | --- |
| `ckan-demo record SCENARIO` | seed (when the run has what the scenario needs), record every scene, join them |
| `ckan-demo setup SCENARIO` | only seed: create the demo users and run the scenario's setup hook |
| `ckan-demo list SCENARIO` | show the scenario's users and scenes |

`record` options:

| Option | Default | |
| --- | --- | --- |
| `--portal URL` | config, else `http://127.0.0.1:5000` | the CKAN site |
| `--api-token TOKEN` | `$CKAN_DEMO_API_TOKEN` | a sysadmin's token, for scenarios that seed through the API |
| `--ckan-ini PATH` | `$CKAN_INI`, else config | the portal's config, for scenarios that seed in-process |
| `--reset` | | ask the scenario to reset its data to a clean slate |
| `--no-setup` | | record without seeding |
| `--scenes a,b` | all | record only these scenes (in scenario order) |
| `--size WxH` | scenario's (`1920x1080`) | video size |
| `--speed X` | `1.0` | pace; `1.3` is 30% faster |
| `--no-captions` | | for a voice-over |
| `--gif` | | also write a GIF (best for short scenes) |
| `--headed` | | watch the browser while it records |
| `--output DIR` | config, else `demo-output/<title>` | where clips, video and stills go |

## Configuration

Settings that would otherwise be repeated on every command can go in the
project's `pyproject.toml` (the nearest one above the scenario file):

```toml
[tool.ckan-demo]
portal = "http://127.0.0.1:5000"
output = "demo/output"
ckan-ini = "../config/ckan.ini"
```

- Paths are relative to that `pyproject.toml`.
- Command-line flags always win; then environment variables
  (`CKAN_DEMO_API_TOKEN`, and `CKAN_INI`, which CKAN's own CLI uses); then this
  table; then the built-in defaults.
- `pyproject.toml` is usually committed, so keep machine-specific values
  (like the path to your `ckan.ini`) in `CKAN_INI` or on the command line.
  API tokens are never read from it.
- Unknown keys are an error, so a typo doesn't go unnoticed.
- `ckan-demo list` shows which settings were picked up.

## Documentation

- [Writing scenarios](docs/scenarios.md): scenes, users, the `Director`
  helpers, stills
- [Seeding](docs/seeding.md): demo users, seeding through the API or
  in-process with your test factories, where seeding code lives, `--reset`
- [Tips and troubleshooting](docs/tips.md): pacing, flaky steps, dev-only
  chrome, video quality

## Who uses it

- [ckanext-issues](../ckanext-issues/demo/): the support tickets demo

## Development

```sh
pip install -e '.[test]'
pytest
ruff check . && ruff format --check .
```
