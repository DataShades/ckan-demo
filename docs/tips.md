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

## Subtitles

Every caption is also written to `<scenario>.vtt` (WebVTT) next to the MP4,
timed to the joined video: lead-ins are cut and crossfades accounted for, as
in the video. Upload it to YouTube as a caption track, give it to a `<track>`
element, or translate it. With `--no-captions` nothing is drawn on the page,
but the subtitles are still written, so viewers can turn captions on and off.
A run without captions removes an old `.vtt`, so the file always matches the
video beside it.

Each clip's recording starts a little after its scene does: usually a few
hundredths of a second, but a second or more on a busy machine, as with
`--jobs`. So that neither the lead-in cut nor the subtitles drift, the first
page load flashes a small magenta square in the corner, inside the part that
is cut, and ckan-demo finds it in the video to measure the difference for
each clip. Without ffmpeg it can't, and it falls back to the scene's timing.

## Chapters

With more than one scene, the MP4 gets a chapter per scene, which players
such as VLC and QuickTime list, and `record` prints them as YouTube
timestamps, ready to paste into the video's description:

```
Chapters:
0:00 Open ticket
0:42 Staff triage
1:15 Conversation
```

Each chapter starts where its scene lands in the joined video (as the blend
begins, with crossfades). Chapter titles come from the scene names, or from
`title=` on `scenario.scene`; see [Writing scenarios](scenarios.md).

YouTube only shows chapters for at least 3 timestamps, each 10 s or longer;
`record` prints a note when the scenes don't meet that. Embedding the chapters
copies the streams without re-encoding; if it fails, `record` warns and the
timestamps are still printed.

## Background music

`--music FILE` (or `music = "..."` in `[tool.ckan-demo]`) lays one track
under the finished video, after the scenes are joined. A track shorter than
the video loops, a longer one is cut where the video ends, and it fades in
over 1 s and out over 3 s. The video stream is copied, so adding music doesn't
re-encode or soften the picture.

`--music-volume` is in dB relative to the track (`-12` by default). Most
music is mastered loud, so going below `-12` suits a calm demo, and `0`
plays the track as it is.

The music is for videos that go out as they are. For a voice-over, record
with `--no-captions --no-music` and mix the narration and music in a video
editor, where the music can duck under the voice. Use music you're allowed to
publish; ckan-demo doesn't ship any.

A `music` file named in `[tool.ckan-demo]` that isn't there only gets a warning,
and the video is recorded without music. A missing `--music` file is an error.
