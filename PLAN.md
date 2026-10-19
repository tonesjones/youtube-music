# Plan

Last updated: 2026-10-18. Work goes directly on `main` (project rule).

Rules that apply to every item: Python 3.11+, small readable code, never download
media, keep request volume low, `browser.json` auth only (never OAuth).

## Status

- Done: `backup`, `scan`, `evaluate`. T1–T2 approved 2026-10-18. T3–T7 built
  2026-10-18: sync rework with TOML config and vault anchor, sync tests, README,
  `apply` + `undo` (in place, your choice).
- Not yet run against YouTube: `apply` and `undo`. Start with
  `apply report.csv --allow-playlist <id> --dry-run`, then a real run with
  `--max-ops 1`, then `undo` on that log.
- T8 (`suggest`) and T9 (`sync --apply`) built 2026-10-18 by the worker; Main
  reviewed the diff and added two guards (`suggest --seed` needs no
  browser.json; sync refuses to apply moves when Inbox and Rotation are the
  same playlist). 125 tests pass. Neither has run against YouTube yet.
- Expiry extended 2026-10-18 (your call): a song heard in 1 sync, then not
  again for 3 syncs and 30 days, also expires. Notes count `quiet_syncs`
  (Inbox syncs since the last play). 128 tests pass.
- Desktop app plan approved 2026-10-18 (NiceGUI, venv first, `.exe` after the
  screens work). U1 done: `ytm-hygiene-app` opens a window with the five screens;
  Setup shows what's configured, the others are placeholders. Settings live in
  `settings.py`, shared with the CLI. 132 tests pass.
- U2 done 2026-10-18: Setup is a 3-step wizard. Sign in by pasting headers
  (`auth.py` cleans them, including the Firefox ones, checks them with one
  read, and only then writes `browser.json`), pick the vault (Browse button in
  the desktop window), pick or create the Inbox and Rotation by name. Vault and
  playlists can be skipped. 137 tests pass. Not yet tried with real headers.
- U3 done 2026-10-18 (worker built it, Main reviewed the diff and fixed two
  bugs): pick a playlist by name, check it with a progress bar, see results in
  plain words (Ready to swap / Please check these / No song version found), tick
  or mark Looks right / Wrong, confirm, swap 20 at a time. 143 tests pass. Not
  yet run on a real playlist. The confirm dialog points to History, which U6 builds.
- U4–U6 done 2026-10-18 (worker built U4, scouts built U5 and U6 in parallel;
  Main reviewed all three and made small fixes). Inbox: one check, plain-word
  groups, apply ticked moves. Suggestions: copy taste summary, paste reply, find,
  add ticked songs (`suggest.py` split into `find_new` and `add_found` so the app
  searches once). History: every run newest first, Undo renames the log to
  `undone-*.json`; the list reloads whenever the tab opens. 162 tests pass.
  None of the screens has touched a real account yet.
- Next: try the app on real playlists, then U7 (`.exe`) and U8 (README).

## T1–T2 results (2026-10-18)

Scanned two real YouTube playlists (they are the same playlists in YouTube Music):
`2025` (57 tracks, 12 videos) and `Music` (52 tracks, 16 videos). Most videos are fan
remixes and mashups with no song version, so few swaps are possible.

| | Before T2 | After T2 |
|---|---|---|
| Correct SWAPs | 0 of 2 possible | 2 of 2 |
| Wrong SWAPs | 0 | 0 |
| Misses | Sweeterman (both playlists) | Sweeterman (both playlists) |

T2 changes in `match.py`:

- Official videos (OMV) may be up to 75 s shorter than the song (`MAX_LONGER_OMV_S`).
  User uploads keep the 5 s limit.
- `artist` flag when the artist score is below 0.60 (covers and lookalikes).
- `version:remixer` flag when both sides are remixes by different or unnamed remixers.
- Strips "(lyrics on screen)", "(CDQ…)", "(Explicit/Clean Version)" from titles.
- Threshold stays at 0.90. `evaluate` suggested 0.70–0.77, but that rests on one
  unflagged correct row, and wrong unflagged rows sit at 0.73–0.77.

Sweeterman is probably an unreleased leak: the cleaned search ("Drake Sweeterman")
finds no song. Treat it as no song version, not a matcher bug.

Login note: headers copied from Firefox include `content-encoding: gzip` and
`accept-encoding: … br, zstd`, which break ytmusicapi (empty, non-JSON reply). They
were removed from `browser.json` by hand. Document this in the README setup (T6), or
strip them in code.

## Routing

Main session runs on Opus. "Main" means the work stays in the main session.

| ID | Task | Tier | Depends on |
|---|---|---|---|
| T1 | Review accuracy results | Main | Scan run + verdicts |
| T2 | Tune match settings | Main | T1 |
| T3 | Write the sync rules (this file) | Main, done | none |
| T4 | Build sync rework + config | Main, done | T3 |
| T5 | Tests for the new sync rules | Haiku (`scout`), done | T4 |
| T6 | Update README | Main, `technical-writing` skill, done | T4, T7 |
| T7 | `apply` + `undo` | Sonnet (`worker`), Main reviewed the diff, done | Approval of T1–T2 |
| T8 | Suggest step | Sonnet (`worker`) P3, Main reviewed the diff, done | T7; design approved 2026-10-18 |
| T9 | Apply sync moves | Sonnet (`worker`) P3, Main reviewed the diff, done | T7; approved 2026-10-18 |

## T1. Accuracy test

Done 2026-10-18; see T1–T2 results. Run on a playlist:

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
| Heard in 1 sync, then not again for 3 syncs and 30 days (added 2026-10-18) | expired, removed from Inbox |

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

## T7. apply + undo (done 2026-10-18, in place)

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

Built as `apply.py`. Rows applied: SWAP rows and REVIEW rows with verdict `correct`,
never `wrong`. `--max-ops` counts swaps (default 20); each swap is three writes
(add, move before the old item, remove the old item), 1.5 s apart. A stale-report
check reads the playlist once and skips rows whose item is gone.

Nice later: `undo` keeps no log of its own, so an undo that stops partway can't
be resumed cleanly. A re-run fails safely at the first add instead.

## T8. Suggest step (design approved 2026-10-18)

Claude suggests new songs for the Inbox; the vault tracks how many get kept.

1. `ytm-hygiene suggest --seed` prints a short taste summary from the vault:
   keepers, rejected and expired songs (artist and title only, no network). You
   paste it into a Claude chat and ask for suggestions.
2. Claude replies with lines of `Artist - Title`. Save them to a text file.
3. `ytm-hygiene suggest songs.txt --dry-run` searches each line once (songs
   filter, 1 s apart), picks the best Art Track with the `match.py` scoring
   (title + artist only), and skips songs that already have a note in any
   status, so rejected songs never come back.
4. Without `--dry-run`, it adds the found songs to the Inbox with the `apply.py`
   writer (throttle, stop on first error, undo log, `--max-ops`) and writes
   notes with `source: claude`. `undo` reverses the adds.

Done when:

- `--seed` makes no requests.
- One search per line, at most `--max-ops` adds, and nothing written on `--dry-run`.
- A song with an existing note is skipped, whatever its status.
- New notes have `source: claude` and `status: inbox`.
- `undo` on the log removes the added songs.
- Tests with a fake client cover each point; all tests pass.

Minimum match score for an add: 0.85 on title + artist (approved), and no
`version:` flag; otherwise listed as not found. Also skipped: a song whose
normalized artist and title match an existing note, even with another videoId.

## T9. Apply sync moves (approved 2026-10-18)

`ytm-hygiene sync --apply` carries out the moves sync proposes, after it saves
the notes and `sync-state.yaml`. Without `--apply`, sync only prints them, as now.

- `promote`: add to Rotation (skip the add if it's already there), then remove
  from Inbox.
- `remove_inbox`, `remove_rotation`: remove from that playlist.
- Allowed playlists: only the configured Inbox and Rotation. Sync never writes
  anywhere else, so it needs no `--allow-playlist`.
- `--dry-run` (with `--apply`) prints the writes and makes none. `--max-ops`
  caps moves per run (default 20). Same 1.5 s throttle and stop on first error.
- Removes use the setVideoIds from the playlists sync already fetched: no extra reads.
- The undo log records each step's playlist, so one log covers both playlists.
  `undo --allow-playlist` can be given more than once, and every playlist in
  the log must be allowed. A removal with no replacement is undone by adding
  the song back at the end of the playlist.

Done when: fake-client tests cover each point, the existing apply and undo tests
still pass, sync without `--apply` makes no writes, and Main has reviewed the diff.

## Desktop app (approved 2026-10-18)

Goal: a first-time user can clean up a playlist and curate the Inbox without a
terminal, playlist IDs, CSV files or terms like OMV and ATV. The CLI stays for
tests and power use; the app calls the same functions.

### Toolkit: NiceGUI in native mode (recommended)

A Python UI library that opens its own desktop window (through pywebview), so
the app stays in Python and small enough for you to review.

| Option | For | Against |
|---|---|---|
| **NiceGUI 3.x + pywebview 6.x** | Python only; ready-made tables, dialogs, progress bars and file pickers; can be packaged as one `.exe` | Two new dependencies (both MIT/BSD, released monthly, widely used) |
| Tkinter | Built into Python, no new dependency | Tables and layout take a lot of code and look dated |
| PySide6 (Qt) | Most native look | Large dependency, much more code |
| Electron or Tauri | Polished | A second language (JavaScript) and a build chain |

Dependency risk: NiceGUI runs a local web server bound to 127.0.0.1 inside the
app. Pin exact versions. No install scripts beyond normal wheels.

### Screens

1. **First-run setup** (wizard, 3 steps):
   - Sign in: a page with pictures that shows where to copy the request headers
     in Chrome, Edge or Firefox, one paste box, and a **Test** button. The app
     strips the headers that break ytmusicapi (the Firefox issue) and writes
     `browser.json`. Never OAuth, never a password field.
   - Obsidian vault: a folder picker.
   - Inbox and Rotation: dropdowns of your playlists by name (one read), with a
     **Create it for me** option.
   Saves `ytm-hygiene.toml`; nobody types an ID.
2. **Clean up a playlist** (scan + apply): pick a playlist by name, press
   **Scan**, watch a progress bar. Results show side by side: *the video you
   have* and *the song we found*, each with a play link, plus a plain reason
   ("same song, same artist" / "different version: live"). Sure matches come
   ticked; doubtful ones unticked, with a **Looks right / Wrong** choice that
   fills the verdict. **Swap N songs** asks once to confirm, then shows
   progress.
3. **Inbox** (sync): **Check what I've listened to** runs sync and shows three
   groups: songs to keep (move to Rotation), songs to drop, songs still on
   trial with how often you've heard them. **Apply** carries out the ticked moves.
4. **Get suggestions**: **Copy my taste summary** puts the seed on the
   clipboard; paste Claude's reply into a box; **Find songs** shows what was
   found; **Add to Inbox**.
5. **History**: every write run with date, what changed, and an **Undo** button.

Plain words throughout: "music video" and "song", never OMV/UGC/ATV;
"play count since last check", never anchor.

### Tasks

| ID | Task | Tier | Depends on |
|---|---|---|---|
| U1 | App shell: window, navigation, settings load/save | Main, done | approval |
| U2 | Setup wizard (sign-in paste + header cleanup + test, vault picker, playlist dropdowns) | Main (touches auth), done | U1 |
| U3 | Clean-up screen over `scan` + `apply_rows` | Sonnet (`worker`), done | U1 |
| U4 | Inbox screen over `sync` + `apply_moves` | Sonnet (`worker`), done | U1 |
| U5 | Suggestions screen over `suggest` | Haiku (`scout`), done | U1 |
| U6 | History + undo screen | Haiku (`scout`), done | U1 |
| U7 | Package as a Windows `.exe` with a Start-menu shortcut | Sonnet (`worker`) | U2–U6 |
| U8 | README rewritten for app users first, CLI second | Main, `technical-writing` | U7 |

Done when:

- U1: `ytm-hygiene-app` opens a window; no terminal input needed afterwards.
- U2: with no `browser.json`, the app opens on the wizard; a bad paste shows a
  plain error; a good one passes **Test** with one read request; Firefox headers
  work without hand edits; `browser.json` stays git-ignored.
- U3–U6: every action that writes to YouTube shows a confirm dialog with the
  count, runs with the same throttle, max-ops and undo log as the CLI, and the
  UI stays responsive (work runs off the UI thread). Logic stays in the
  existing modules; UI files hold no matching or sync rules.
- U3–U6: tests drive each screen's handlers with the fake client (NiceGUI's
  test `User` fixture), no network.
- U7: one `.exe` runs on a PC without Python installed.
- U8: a first-time user can follow the README from download to first swap.
- All of them: request volume no higher than the CLI (no auto-refresh or
  background polling).

## Open decisions

- None. (App files in `%APPDATA%\ytm-hygiene` approved 2026-10-18.)
