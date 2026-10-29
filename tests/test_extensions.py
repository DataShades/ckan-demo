"""Browser extensions loaded into scenes."""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ckan_demo import BrowserExtension, Scenario, load_scenario, recorder
from ckan_demo.director import Options
from ckan_demo.extensions import Extension, ExtensionError, LoadedExtension, extension_id, find, prepare
from ckan_demo.scenario import ScenarioError

MANIFEST = {
    "manifest_version": 3,
    "name": "Marker",
    "version": "1.0",
    "background": {"service_worker": "worker.js"},
    "action": {"default_popup": "popup.html"},
    "content_scripts": [{"matches": ["http://127.0.0.1/*"], "js": ["content.js"]}],
    "permissions": ["storage"],
    "optional_permissions": ["tabs"],
    "optional_host_permissions": ["http://*/*"],
}


@pytest.fixture
def extension_dir(tmp_path):
    folder = tmp_path / "marker"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps(MANIFEST))
    (folder / "worker.js").write_text("self.marker = 'from the worker';\n")
    (folder / "content.js").write_text(
        "document.documentElement.dataset.marker = 'loaded';\n"
        # UI in a closed shadow root, which only the extension's world can reach.
        "const host = document.createElement('div');\n"
        "globalThis.Marker = { root: host.attachShadow({ mode: 'closed' }) };\n"
        "Marker.root.innerHTML = '<p>In the shadow</p>';\n"
        "document.body.append(host);\n"
    )
    (folder / "popup.html").write_text(
        "<!doctype html><body style='width: 300px; margin: 0'><h1 style='height: 150px; margin: 0'>Marker popup</h1>\n"
    )
    (folder / "page.html").write_text("<!doctype html><title>Marker page</title><h1>Marker page</h1>\n")
    return folder


def test_id_from_path_uses_letters_a_to_p(tmp_path):
    first = extension_id(tmp_path / "a", {})
    assert len(first) == 32
    assert set(first) <= set("abcdefghijklmnop")
    assert first != extension_id(tmp_path / "b", {})


def test_id_from_key_ignores_the_path(tmp_path):
    key = base64.b64encode(b"public key").decode()
    assert extension_id(tmp_path / "a", {"key": key}) == extension_id(tmp_path / "b", {"key": key})


def test_prepare_copies_and_grants_optional_permissions(extension_dir, tmp_path):
    (loaded,) = prepare([BrowserExtension(extension_dir, grant_optional_permissions=True)], tmp_path / "out")

    manifest = json.loads((loaded.path / "manifest.json").read_text())
    assert manifest["permissions"] == ["storage", "tabs"]
    assert manifest["host_permissions"] == ["http://*/*"]
    # Director.open_popup frames the popup in pages.
    assert manifest["web_accessible_resources"] == [{"resources": ["popup.html"], "matches": ["<all_urls>"]}]
    assert loaded.popup == "popup.html"
    assert json.loads((extension_dir / "manifest.json").read_text()) == MANIFEST, "the original is untouched"
    assert (loaded.name, loaded.folder, loaded.has_worker) == ("Marker", "marker", True)
    assert loaded.id == extension_id(loaded.path, manifest)


def test_prepare_without_a_manifest(tmp_path):
    with pytest.raises(ExtensionError, match=r"no manifest\.json"):
        prepare([BrowserExtension(tmp_path)], tmp_path / "out")


def _extension(name, folder):
    return Extension(None, LoadedExtension("id", name, folder, None, has_worker=False))


def test_find_by_name_or_folder():
    one, two = _extension("One", "one-dir"), _extension("Two", "two-dir")

    assert find([one], None) is one
    assert find([one, two], "Two") is two
    assert find([one, two], "one-dir") is one
    with pytest.raises(ExtensionError, match="name one"):
        find([one, two], None)
    with pytest.raises(ExtensionError, match="no extension 'Three'"):
        find([one, two], "Three")
    with pytest.raises(ExtensionError, match="loads no extensions"):
        find([], None)


def test_paths_are_relative_to_the_scenario_file(extension_dir, tmp_path):
    scenario_file = tmp_path / "demo.py"
    scenario_file.write_text(
        "from ckan_demo import Scenario\n"
        "scenario = Scenario('Demo', extensions=['marker'])\n"
        "scenario.scene('one')(lambda d: None)\n"
    )

    assert load_scenario(scenario_file).extensions == [BrowserExtension(extension_dir)]


def test_evaluate_in_page_without_a_content_script(extension_dir, site, tmp_path):
    pytest.importorskip("playwright.sync_api")
    scenario = Scenario("Demo", extensions=[extension_dir])
    errors = []

    @scenario.scene("one")
    def one(d):
        d.goto(d.extension().url("page.html"))  # content scripts don't run on extension pages
        try:
            d.extension().evaluate_in_page(d.page, "() => 1")
        except ExtensionError as error:
            errors.append(str(error))

    recorder.record(
        scenario, Options(base_url=site, output=tmp_path / "out"), scenario.scenes, on_scene=lambda line: None
    )
    assert errors and "no content script" in errors[0]


def test_a_path_can_be_a_string(tmp_path):
    assert BrowserExtension(str(tmp_path / "dist" / "chrome")).path.name == "chrome"


def test_a_missing_extension_stops_loading(tmp_path):
    scenario_file = tmp_path / "demo.py"
    scenario_file.write_text(
        "from ckan_demo import Scenario\n"
        "scenario = Scenario('Demo', extensions=['dist/chrome'])\n"
        "scenario.scene('one')(lambda d: None)\n"
    )

    with pytest.raises(ScenarioError, match="is the extension built"):
        load_scenario(scenario_file)


@pytest.fixture
def site():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<!doctype html><title>Site</title><h1>Site</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_a_scene_runs_with_the_extension(extension_dir, site, tmp_path):
    pytest.importorskip("playwright.sync_api")
    seen = {}
    scenario = Scenario("Demo", extensions=[extension_dir])

    @scenario.scene("one")
    def one(d):
        d.goto("/")
        seen["marker"] = d.page.evaluate("() => document.documentElement.dataset.marker")
        extension = d.extension()
        seen["ids"] = (extension.id, extension.evaluate("() => chrome.runtime.id"))
        seen["worker"] = extension.evaluate("() => self.marker")
        seen["shadow"] = extension.evaluate_in_page(
            d.page, "selector => Marker.root.querySelector(selector).textContent", "p"
        )
        seen["page world"] = d.page.evaluate("() => typeof Marker")
        popup = d.open_popup()
        seen["popup"] = popup.locator("h1").inner_text()
        seen["popup size"] = d.page.eval_on_selector("#demo-popup", "el => [el.offsetWidth, el.offsetHeight]")
        d.close_popup()
        d.goto(extension.url("page.html"))
        seen["page"] = d.page.title()

    try:
        (clip,) = recorder.record(
            scenario, Options(base_url=site, output=tmp_path / "out"), scenario.scenes, on_scene=lambda line: None
        )
    except recorder.RecordingError as error:
        if "Executable doesn't exist" in str(error):
            pytest.skip(f"no Chromium: {error}")
        raise

    assert seen["marker"] == "loaded", "the content script ran"
    assert seen["ids"][0] == seen["ids"][1], "the computed ID is Chromium's"
    assert seen["worker"] == "from the worker"
    assert seen["shadow"] == "In the shadow"
    assert seen["page world"] == "undefined", "the content script's globals are only in its world"
    assert seen["popup"] == "Marker popup"
    assert seen["popup size"] == [300, 150], "the frame fits the popup's body"
    assert seen["page"] == "Marker page"
    assert clip.path.stat().st_size > 0
