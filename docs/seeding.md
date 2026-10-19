# Seeding

A good demo starts from the same state every time: the same people, the same
data, nothing left over from the last take. ckan-demo doesn't know what your
extension's data looks like (tickets, harvest sources, datastore tables…), so
it gives seeding one place to run and two ways to reach CKAN. What to create is
up to the scenario.

## What ckan-demo always does

Before your hook runs, every `User` in the scenario is created, or, if the
account exists, brought in line: full name, email, password and the sysadmin
flag are set to what the scenario says, so the browser can always log in.

Use dedicated demo accounts: ckan-demo resets the password of any account a
scenario names.

The hook then receives them, with their CKAN ids, in `setup.users`.

## Two ways to seed

```python
@scenario.setup                      # through the API
def prepare(setup: Setup) -> None: ...

@scenario.setup(in_process=True)     # inside CKAN
def prepare(setup: Setup) -> None: ...
```

| | Through the API | In-process |
| --- | --- | --- |
| `setup.ckan` is | ckanapi's `RemoteCKAN`, calling the action API with the token | ckanapi's `LocalCKAN`, acting as the site user; models, toolkit and test factories work too |
| The run needs | a sysadmin's API token (`--api-token` or `$CKAN_DEMO_API_TOKEN`) | the portal's `ckan.ini` (`--ckan-ini`, `$CKAN_INI` or [`[tool.ckan-demo]`](../README.md#configuration)), and CKAN installed where ckan-demo runs |
| Works against | any portal ckan-demo can reach | a portal whose database you can reach (usually your own) |
| Good for | demos recorded on staging or someone else's portal | reusing the factories and seed code your extension already has; data the API can't express (timestamps in the past) |

Either way, `setup.ckan` is a [ckanapi](https://github.com/ckan/ckanapi)
client with the same interface, so calling actions looks the same in both:

```python
setup.ckan.action.package_create(name="air-quality", title="Hourly air quality", owner_org="demo-org")
setup.ckan.call_action("package_show", {"id": "air-quality"})
```

Errors are ckanapi's: `ckanapi.NotFound`, `ckanapi.ValidationError`,
`ckanapi.NotAuthorized`.

If the run lacks what the scenario needs, `record` warns and records the portal
as it is, and `setup` stops with an error. `ckan-demo list` shows which way a
scenario seeds.

### Optional seeding

When the scenes work with whatever the portal has, and seeding only makes the
video show known content, mark the hook optional:

```python
@scenario.setup(optional=True)
def seed(setup: Setup) -> None: ...
```

Then `record` doesn't stop when seeding can't run or fails part-way: no token
(or ckan.ini), a token without permission (`NotAuthorized`, e.g. on someone
else's portal), CKAN rejecting the data, or the portal not answering. It prints
one line saying why and records the portal as it is. Anything already created
before the failure stays; keep the hook idempotent so the next run picks up
from there. Bugs in the hook itself (a typo, a missing file) still stop the
run. [`examples/dataset_search.py`](../examples/dataset_search.py) works this
way.

### The `Setup` object

| | |
| --- | --- |
| `setup.ckan` | the ckanapi client: `setup.ckan.action.<name>(**data)` or `call_action(name, data)` |
| `setup.users` | role → the CKAN user dict (`id`, `name`, …) of each scenario user |
| `setup.reset` | the run was given `--reset`: delete what the demo owns and rebuild it |
| `setup.in_process` | the hook runs inside CKAN |
| `setup.portal` | the `Portal`: `url`, `ckan_ini`, `get_json(path, **params)` for JSON pages that aren't actions, `local_ckan()` |

`exists(ckan, action, **data)` (from `ckan_demo`) returns the action's result,
or `None` when CKAN says Not Found; handy for "create if missing".

### Through the API

```python
from ckan_demo import Setup, exists


@scenario.setup
def prepare(setup: Setup) -> None:
    ckan = setup.ckan
    if setup.reset and exists(ckan, "package_show", id="air-quality"):
        ckan.action.dataset_purge(id="air-quality")

    if not exists(ckan, "organization_show", id="demo-org"):
        ckan.action.organization_create(name="demo-org", title="Demo Organisation")
    if not exists(ckan, "package_show", id="air-quality"):
        ckan.action.package_create(
            name="air-quality",
            title="Hourly air quality",
            owner_org="demo-org",
            notes="Readings from city sensors.",
        )
```

ckanapi can also upload files, e.g.
`ckan.action.resource_create(package_id=..., name="data.csv", upload=open("data.csv", "rb"))`.

For the odd thing the API can't do, an API hook can still step in-process for a
moment with `with setup.portal.local_ckan() as local: ...` (needs `--ckan-ini`).

### In-process

The hook runs inside CKAN's app context, as a CLI command would. Import CKAN
and your extension *inside* the hook, so the scenario can still be listed and
loaded where CKAN isn't installed:

```python
@scenario.setup(in_process=True)
def prepare(setup: Setup) -> None:
    from ckan.tests import factories

    if exists(setup.ckan, "package_show", id="river-levels"):
        return
    org = factories.Organization(name="demo-org", title="Environment Agency", image_url="")
    factories.Dataset(
        name="river-levels",
        title="River levels, hourly",
        notes="Water levels from 120 river gauges.",
        owner_org=org["id"],
    )
```


## Reusing your extension's test code

Most extensions already know how to create their data: in their test
factories and fixtures. Reuse the right half of it.

- **Factories: yes** (in-process). CKAN's `ckan.tests.factories` and the
  factories extensions build on them (`CKANFactory` subclasses) are thin
  wrappers around actions, and work outside pytest inside an app context. They
  import `pytest` and `factory_boy`, so CKAN's development requirements must be
  installed.
- **conftest fixtures: no.** They only exist inside pytest, and some of them
  (`clean_db`, `reset_db`) drop and rebuild the database: pointed at a real
  portal, they wipe it, not just the demo's data. Call what the fixtures call
  (the factories, a seed function) instead.
- **Give factories presentable values.** Every field you leave out is filled
  with Faker data: lorem ipsum descriptions, `test_user_0412`, a random stock
  photo for an organisation. On camera that looks wrong, so pass a value for
  everything that shows (`description`, `notes`, `image_url=""`, …).

## Where the seeding code lives

Keep the scenario file readable as the story it tells.

| Seeding | Where |
| --- | --- |
| a few objects, only the demo needs them | in the scenario's setup hook |
| realistic sample content, or anything the tests could use too | its own module, which the hook calls |

A shared module pays off quickly. When the e2e tests and the demo seed the same
sample content, screenshots from both show the same believable portal, and
improving the sample data improves both. Split it into:

- **plain data** (names, titles, texts) with no CKAN imports, readable from
  anywhere;
- **a loader** that turns it into CKAN objects with factories or actions, used
  by the tests' fixtures and by the demo's in-process hook alike.

The scenario can import modules next to it (`demo/data.py`), and anything
importable in the environment, such as `ckanext.foo.tests.sample_data`.

## Reset and idempotence

Without `--reset`, a setup hook should be safe to run on every take:

- create what is missing (`exists` / `ObjectNotFound`), don't create
  duplicates;
- remove only what a previous take of *this* demo left behind: typically the
  records the scenes themselves create, found by a name or subject the
  scenario controls.

With `--reset`, delete what the demo owns and rebuild it, so the recording
starts from a known state. What "owns" means is the scenario's call; deleting
every record of a kind is only acceptable on a development portal, so say so
in the scenario's README.

## Only seeding

`ckan-demo setup SCENARIO [--reset]` seeds without recording, which is handy
before a live demo.
