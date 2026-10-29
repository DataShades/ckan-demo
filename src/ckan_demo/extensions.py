"""Browser extensions loaded into every scene, for demos of the extension itself.

Chromium runs extensions only in a persistent context launched with the full
browser (``channel="chromium"``), not the headless shell Playwright uses by
default, so scenes with extensions are recorded that way. Firefox isn't
supported: Playwright's Firefox can't load extensions.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page, Worker

# Granted permissions and their optional counterparts in a manifest.
OPTIONAL = {"permissions": "optional_permissions", "host_permissions": "optional_host_permissions"}

# How long a scene waits for an extension's service worker to start.
WORKER_TIMEOUT_MS = 10_000


class ExtensionError(Exception):
    """An extension that can't be loaded or reached."""


@dataclass(frozen=True)
class BrowserExtension:
    """An unpacked Chromium extension: the folder with its ``manifest.json``.

    ``grant_optional_permissions`` grants its optional permissions and host
    permissions up front. A user grants them from a prompt, which a headless
    browser can't show.
    """

    path: Path
    grant_optional_permissions: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))  # accept a string too

    def manifest(self) -> dict[str, Any]:
        manifest = self.path / "manifest.json"
        if not manifest.is_file():
            raise ExtensionError(f"no manifest.json in {self.path}; is the extension built?")
        return json.loads(manifest.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class LoadedExtension:
    """A copy of an extension, ready to load, and the ID Chromium gives it."""

    id: str
    name: str
    folder: str  # name of the original folder, e.g. "chrome" for dist/chrome
    path: Path
    has_worker: bool
    popup: str | None = None  # the toolbar popup's page, e.g. "popup/popup.html"


def extension_id(path: Path, manifest: dict[str, Any]) -> str:
    """The ID Chromium gives an unpacked extension: from the manifest's
    ``key`` if it has one, else from its absolute path. The first 32 hex
    digits of a SHA-256, written with the letters a to p."""
    source = base64.b64decode(manifest["key"]) if "key" in manifest else str(path.resolve()).encode()
    digest = hashlib.sha256(source).hexdigest()[:32]
    return "".join(chr(ord("a") + int(digit, 16)) for digit in digest)


def prepare(extensions: list[BrowserExtension], target: Path) -> list[LoadedExtension]:
    """Copy each extension under ``target`` and apply its options. The copy
    keeps the original untouched and gives it the same ID in every scene."""
    loaded: list[LoadedExtension] = []
    for index, extension in enumerate(extensions):
        manifest = extension.manifest()
        copy = target / f"{index}-{extension.path.name}"
        shutil.copytree(extension.path, copy)
        if extension.grant_optional_permissions:
            for granted, optional in OPTIONAL.items():
                extra = [item for item in manifest.get(optional, []) if item not in manifest.get(granted, [])]
                if extra:
                    manifest[granted] = [*manifest.get(granted, []), *extra]
        popup = manifest.get("action", {}).get("default_popup")
        if popup:
            # Director.open_popup frames it in the page, which needs it to be
            # web accessible.
            popup = popup.lstrip("/")
            resources = manifest.setdefault("web_accessible_resources", [])
            resources.append({"resources": [popup], "matches": ["<all_urls>"]})
        (copy / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        loaded.append(
            LoadedExtension(
                id=extension_id(copy, manifest),
                name=manifest.get("name", ""),
                folder=extension.path.name,
                path=copy.resolve(),
                has_worker="service_worker" in manifest.get("background", {}),
                popup=popup,
            )
        )
    return loaded


def launch_args(extensions: list[LoadedExtension]) -> list[str]:
    paths = ",".join(str(extension.path) for extension in extensions)
    return [f"--disable-extensions-except={paths}", f"--load-extension={paths}"]


class Extension:
    """An extension loaded in the scene's browser, from :meth:`Director.extension`."""

    def __init__(self, context: BrowserContext, loaded: LoadedExtension) -> None:
        self._context = context
        self._loaded = loaded

    @property
    def id(self) -> str:
        return self._loaded.id

    @property
    def name(self) -> str:
        return self._loaded.name

    @property
    def folder(self) -> str:
        return self._loaded.folder

    def wait_until_ready(self) -> None:
        """Wait for the service worker, if the extension has one."""
        if self._loaded.has_worker:
            self.worker  # noqa: B018

    def url(self, path: str = "") -> str:
        """URL of one of the extension's pages, e.g. ``url("popup/popup.html")``."""
        return f"chrome-extension://{self.id}/{path.lstrip('/')}"

    @property
    def worker(self) -> Worker:
        """The extension's service worker, waiting for it to start."""
        if not self._loaded.has_worker:
            raise ExtensionError(f"extension {self.name!r} has no service worker")
        prefix = self.url()
        for worker in self._context.service_workers:
            if worker.url.startswith(prefix):
                return worker
        try:
            return self._context.wait_for_event(
                "serviceworker", lambda worker: worker.url.startswith(prefix), timeout=WORKER_TIMEOUT_MS
            )
        except Exception as error:
            raise ExtensionError(f"the service worker of extension {self.name!r} did not start") from error

    def evaluate(self, expression: str, arg: Any = None) -> Any:
        """Run JavaScript in the extension's service worker, where its
        ``chrome.*`` APIs are, e.g. ``evaluate("() => chrome.storage.local.set({on: true})")``."""
        return self.worker.evaluate(expression, arg)

    def evaluate_in_page(self, page: Page, function: str, arg: Any = None) -> Any:
        """Run a JavaScript function in the world the extension's content
        scripts share in ``page``: their globals, and the closed shadow
        roots they make, which the page and Playwright's locators can't
        reach. ``function`` is called with ``arg`` and its result returned,
        e.g. ``evaluate_in_page(d.page, "() => MyExt.panel.getBoundingClientRect().toJSON()")``.
        Raises :class:`ExtensionError` if no content script runs there yet."""
        cdp = self._context.new_cdp_session(page)
        try:
            worlds: list[dict[str, Any]] = []
            cdp.on("Runtime.executionContextCreated", lambda event: worlds.append(event["context"]))
            cdp.send("Runtime.enable")  # reports the frame's worlds, before it returns
            frame = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
            origin = self.url().rstrip("/")
            world = next(
                (
                    world["id"]
                    for world in reversed(worlds)  # the newest, after a reload
                    # A content script's isolated world. Not the page's own or
                    # Playwright's, which an extension page gives its origin.
                    if world.get("origin") == origin
                    and world.get("auxData", {}).get("frameId") == frame
                    and world.get("auxData", {}).get("isDefault") is False
                    and not world.get("name", "").startswith("__playwright")
                ),
                None,
            )
            if world is None:
                raise ExtensionError(f"no content script of extension {self.name!r} runs in {page.url}")
            reply = cdp.send(
                "Runtime.evaluate",
                {
                    "expression": f"({function})({json.dumps(arg)})",
                    "contextId": world,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            )
        finally:
            cdp.detach()
        if "exceptionDetails" in reply:
            details = reply["exceptionDetails"]
            raise ExtensionError(details.get("exception", {}).get("description") or details.get("text", "error"))
        return reply["result"].get("value")

    @property
    def popup_url(self) -> str:
        if not self._loaded.popup:
            raise ExtensionError(f"extension {self.name!r} has no toolbar popup (action.default_popup)")
        return self.url(self._loaded.popup)


def find(extensions: list[Extension], name: str | None) -> Extension:
    """The extension called ``name`` (its manifest name or folder), or the
    only one when ``name`` is None."""
    if not extensions:
        raise ExtensionError("the scenario loads no extensions; add them with Scenario(extensions=[...])")
    if name is None:
        if len(extensions) > 1:
            raise ExtensionError(
                f"the scenario loads {len(extensions)} extensions; name one: "
                + ", ".join(repr(extension.name) for extension in extensions)
            )
        return extensions[0]
    for extension in extensions:
        if name in (extension.name, extension.folder):
            return extension
    raise ExtensionError(f"no extension {name!r} (loaded: {', '.join(repr(e.name) for e in extensions)})")
