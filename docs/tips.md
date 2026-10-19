# Tips and troubleshooting

## Pacing

- GIFs get large quickly; make them from a single scene, e.g.
  `--scenes 02-staff-triage --gif`.
- Captions pace themselves: each stays up long enough to read before the next
  one replaces it, with or without `--no-captions` (so a voice-over gets the
  same room).
- Scenes fade through black into each other by default, so a change of page
  between scenes isn't a hard cut. Choose another transition per run
  (`--transition crossfade:0.6`), per scenario (`Scenario(transition=...)`) or
  per project (`transition` in `[tool.ckan-demo]`): `cut`, `fade[:seconds]` or
  `crossfade[:seconds]`. A crossfade overlaps the scenes, so the video gets a
  little shorter. Start a scene with a card or a caption when the viewer needs
  to know where they are.
- Tune the whole video with `--speed` (1.3 is 30% faster) rather than editing
  every pause.
- Watch it with `--headed` while writing scenes: you see what the camera sees.

## Recording faster

If no scene depends on another (no scene uses data an earlier one created or
changed), set `Scenario(..., independent_scenes=True)` and record several at
once with `--jobs 2` or `--jobs 3`. Each scene gets its own browser; the clips
are joined in scenario order as usual. Scenarios without the flag ignore
`--jobs` with a warning.

## A step fails or flickers

- **Wait for what the user waits for.** After an action that loads a page, use
  `with d.navigates():`. After one that updates the page in place, use
  Playwright's `expect(...)` on the result. Don't add fixed pauses to "wait
  for" things.
- **Interacting right after a reload.** Pages that enhance themselves with
  JavaScript (htmx, Bootstrap) need a moment after loading; `d.goto` and
  `d.navigates` wait for the network to go idle, so use them rather than
  `page.goto`/`page.click` directly.
- **Dialogs that animate in** ignore keys like Escape until they are shown.
  Wait for something inside them first, e.g.
  `expect(dialog.locator("#ckan-confirm-cancel")).to_be_focused()`.
- **A scene fails**: the error names the scene, and the clips recorded before
  it are kept. Fix it and run `--scenes` from that scene on, or the whole
  story if scenes depend on each other.
- **Logging in fails**: record with an API token or `--ckan-ini`, so the demo
  users are created with the scenario's passwords.

## Development portals

`ckan-demo` hides CKAN's `debug = true` box and the Flask debug toolbar, so a
dev portal records cleanly. Anything else that shouldn't be on camera can be
hidden from a scene with CSS:

```python
d.page.add_style_tag(content=".beta-banner { display: none !important; }")
```

## Video quality

Videos are recorded at the scenario's size (1920×1080, Full HD, by default)
and encoded as H.264 at CRF 18, which keeps text crisp. The browser window is
the video, so the size also decides CKAN's layout: at 1080p its content area
leaves wide side margins, so text looks smaller. For demos of small UI
(forms, dialogs), a smaller 16:9 size such as `--size 1280x720` makes it
easier to read.
