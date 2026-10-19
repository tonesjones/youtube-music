# Plan

Last updated: 2026-10-18. Work goes directly on `main` (project rule).

Rules that apply to every item: Python 3.11+, small readable code, never download
media, keep request volume low, `browser.json` auth only (never OAuth).

## Status

- Done: `backup`, `scan`, `evaluate`, `sync` (vault writes only). 63 tests pass.
- Next: T1 (accuracy test). Waiting on the scan run and verdicts.
- Blocked: T7 `apply` / `undo` waits for approval of the accuracy results (T1–T2).

## Checkpoint (2026-10-18)

Where T1 stopped:

- Done: `.venv` created (Python 3.14.3), `pip install -e ".[dev]"` installed
  ytmusicapi 1.12.3, rapidfuzz 3.14.6, PyYAML 6.0.3 and pytest 9.1.1. All 63 tests pass.
- Not done: `browser.json`. Run `.\.venv\Scripts\ytmusicapi.exe browser`, then in
  Firefox open music.youtube.com with DevTools on the Network tab. Right-click a
  `POST` to `music.youtube.com` with status 200 (`browse?…` or `player?prettyPrint=false`),
  choose Copy Value, then Copy Request Headers, paste it, press Enter, then Ctrl+Z and Enter.
- Then: `.\.venv\Scripts\ytm-hygiene.exe scan "<youtube.com playlist URL>"`.
  The playlists live on YouTube, which is fine: YouTube and YouTube Music share
  playlists and IDs, and `scan` is read-only, so a real playlist is safe to scan.

## Routing

Main session runs on Opus. "Main" means the work stays in the main session.

| ID | Task | Tier | Depends on |
|---|---|---|---|
| T1 | Review accuracy results | Main | Scan run + verdicts |
| T2 | Tune match settings | Main | T1 |
| T3 | Write the sync rules (this file) | Main | none |
| T4 | Build sync rework + config | Main | T3 |
| T5 | Tests for the new sync rules | Haiku (`scout`) | T4 |
| T6 | Update README | Main, `technical-writing` skill | T4 |
| T7 | `apply` + `undo` | Sonnet (`worker`), flagged: Main reviews the diff | Approval of T1–T2 |
| T8 | Suggest step | Not routed yet | T7 |

## T1. Accuracy test

Run on the throwaway playlist:

1. `pip install -e ".[dev]"`, then `ytmusicapi browser`.
2. `ytm-hygiene scan <playlist>`, fill the `verdict` column, `ytm-hygiene evaluate report.csv`.

Done when:

- Every SWAP and REVIEW row has a verdict.
- Each wrong SWAP and each miss has a named cause (title cleanup, artist, length, flag,
  or search query).

## T2. Tune match settings

Change only what T1's causes point to: `DEFAULT_THRESHOLD`, `MIN_USABLE`, the length
limits, the noise and version regexes, or the search query.

Done when:

- `evaluate` on the sample shows 0 wrong SWAPs.
- Each wrong or missed row from T1 gets a case in `tests/fixtures/match_cases.json`.
- All tests pass.
- You approve the results. Only then does T7 start.

## T3–T4. Sync rework for manual runs

You run sync by hand every so often, not daily. A sync is one command.

### Config

`ytm-hygiene.toml` in the working directory, read with the built-in `tomllib`
(no new dependency). Git-ignored; `ytm-hygiene.example.toml` is committed.

```toml
vault = "C:/Users/me/Obsidian/MyVault"
inbox = "PL..."
rotation = "PL..."
```

CLI flags still override the file. `--config <path>` picks another file.

### State in the vault

`Music/sync-state.yaml` holds:

- `last_sync`: the date of the previous sync.
- `anchor`: the top 10 history videoIds from the previous sync, in order.

### "Heard" = in history since the last sync

History has no timestamps, and a replayed song moves to the top instead of
showing up twice. So comparing sets of videoIds misses replays. Instead:

- Find where the old anchor sequence resumes in the current history: the first
  position where an anchor song is followed by the next anchor songs in their old order.
- Everything above that position was played since the last sync, including
  replayed anchor songs.
- If no anchor song is found (more than about 200 plays since, or first sync), treat
  the whole history as new and print a warning.

Each note records the syncs where its song was heard: `heard_syncs: [dates]`.
One sync adds at most one entry, however many times the song played.

### Inbox rules, first match wins

| Signal | Result |
|---|---|
| Thumbs up | keeper, moves to Rotation |
| Thumbs down | rejected, removed from Inbox |
| Heard in 2 separate syncs | keeper |
| In the Inbox for at least 3 syncs and at least 30 days, never heard | expired, removed from Inbox |

Each note counts `inbox_syncs`: how many syncs saw the song in the Inbox.
`--expire-days` defaults to 30. The Rotation and manual `status` rules stay the same.

### Existing notes

Notes written by the old sync still load. New fields get defaults
(`heard_syncs: []`, `inbox_syncs: 0`). `heard_days` is dropped on the next write.

Done when (T4):

- `ytm-hygiene sync` with no flags reads `ytm-hygiene.toml` and still makes only
  3 read requests.
- `sync-state.yaml` is written after the notes, so a failed run doesn't advance the anchor.
- `ytm-hygiene.toml` is in `.gitignore`.
- Existing tests are updated and pass.

Done when (T5), one test each:

- New plays above the anchor count as heard; songs below it don't.
- A replayed anchor song counts as heard.
- No anchor found: all history counts, and a warning is returned.
- No new plays: nothing is heard, and `last_sync` still updates.
- Two plays in one sync add one `heard_syncs` entry.
- Heard in 2 syncs → keeper. Heard in 1 → stays in the Inbox.
- 3 syncs and 30 days, never heard → expired. 3 syncs but 29 days → stays.
  30 days but 2 syncs → stays.
- Thumbs up/down still win over everything else.
- An old-format note loads and gets the new defaults.

Done when (T6): the README sync section matches the rules above, and the
"run sync daily" advice is gone.

## T7. apply + undo (blocked until you approve T1–T2)

Follows the safety spec in the README:

- `--dry-run` prints every planned write and makes no write calls.
- `--allow-playlist <id>` is required and must match the target playlist.
- `--max-ops N` caps writes per run.
- 1–2 s between writes.
- Stop on the first error.
- Every write is appended to `undo-<timestamp>.json` before the next one, and
  `undo` replays the log in reverse.
- A swap keeps the track's position in the playlist.

Done when: tests with a fake client cover each rule above, all tests pass, and Main
has reviewed the diff (it removes playlist items).

## T8. Suggest step (later)

Add new songs to the Inbox tagged `source: claude`. The dashboard's hit-rate-by-source
table already tracks how many get kept. Design after T7.

## Open decisions

- None for T3–T4. The anchor approach and TOML config are approved (2026-10-18).
- T7: swap in place or on a copy? The playlists are YouTube playlists, so a swap
  in place also replaces the video with the song on youtube.com. A copy keeps the
  original playlist as it is. Decide before T7.
