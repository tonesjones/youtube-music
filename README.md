# ytm-hygiene

Replaces music videos in a YouTube Music playlist with their audio-only song
versions (Art Tracks), so offline downloads take less space. It only edits
playlists and never downloads media.

YouTube and YouTube Music share playlists, so a playlist you made on YouTube
works here with the same ID.

Status: `backup`, `scan`, `evaluate`, `apply`, `undo` and `sync` work. `sync`
writes only to your Obsidian vault and prints the playlist moves it proposes.

## Setup

```sh
pip install -e ".[dev]"
ytmusicapi browser        # paste request headers from a logged-in browser; writes browser.json
```

`browser.json` holds your session cookies and is git-ignored. The client uses
English and US settings.

If every request fails with an empty or non-JSON reply, open `browser.json` and
delete the `content-encoding` and `accept-encoding` lines. Headers copied from
Firefox include them, and they break ytmusicapi.

## Accuracy test

```sh
ytm-hygiene backup <playlist-id-or-url>    # backups/<id>-<timestamp>.json
ytm-hygiene scan <playlist-id-or-url>      # read-only; also writes a backup; creates report.csv
# open report.csv, fill the verdict column: correct / wrong / missed
ytm-hygiene evaluate report.csv
```

Verdicts:

- `correct`: the proposed song is the right one.
- `wrong`: the proposed song is a different track or version.
- `missed`: a song version exists, but the tool didn't propose it (mostly NO_MATCH rows).

The scan makes one song search per non-song track, at least 1 s apart. If the
filtered search finds nothing, it tries one unfiltered search.

`scan --clean` is for kid-friendly playlists. It flags explicit candidates and
prefers clean versions. By default, explicit is fine; a clean candidate for an
explicit original is flagged.

## How a track is classified

| Original type | Action |
|---|---|
| ATV (song) | KEEP |
| OMV, UGC | SWAP when the score is at least the threshold (default 0.90) and there are no flags; otherwise REVIEW, or NO_MATCH when the best usable candidate scores below 0.60 |
| OFFICIAL_SOURCE_MUSIC | always REVIEW (often live sets or compilations) |

Score = 0.50 × title + 0.35 × artist + 0.15 × length.

- **Title:** the mean of rapidfuzz `token_set_ratio` and `token_sort_ratio`
  on cleaned titles. Using token_set alone treats "Love" and "Love Story" as
  identical. Cleanup removes video noise such as "(Official Video)", "[4K]",
  "(lyrics on screen)", "(CDQ)", "(Explicit Version)" and feat. blocks.
- **Artist:** 1.0 when an artist ID overlaps; otherwise fuzzy match on
  normalized names. For user uploads, the "Artist - Title" prefix counts as
  an artist.
- **Length:** the song may run at most 15 s shorter than the video. It may run
  at most 75 s longer than an official video (OMV), which is often a shorter
  edit, and at most 5 s longer than a user upload (UGC).

Flags force REVIEW:

- `duration`, `no_duration`
- `artist`: the artist score is below 0.60, which usually means a cover or a
  lookalike
- `version:<tag>`: one side is live, remix, acoustic, sped up, slowed,
  instrumental, karaoke, cover or remaster, and the other isn't
- `version:remixer`: both sides are remixes, but by different remixers, or
  one remix names no remixer
- `clean_version` / `explicit`
- `official_source`
- `no_setVideoId`

Candidates must be available Art Tracks.

`report.csv` has two columns beyond the spec, `playlist_id` and
`old_setVideoId`, which `apply` uses.

## Apply the swaps

`apply` swaps each video for its song in the same playlist, at the same
position. Because the playlist is shared, youtube.com shows the songs too.

It swaps SWAP rows, and REVIEW rows you marked `correct`. It skips rows marked
`wrong`.

```sh
ytm-hygiene apply report.csv --allow-playlist <playlist-id> --dry-run   # print the writes, make none
ytm-hygiene apply report.csv --allow-playlist <playlist-id>
```

- `--allow-playlist` is required. If any row belongs to another playlist,
  `apply` stops before writing.
- `--max-ops` caps the swaps per run (default 20).
- Before writing, `apply` reads the playlist once and saves a backup. It skips
  rows whose video is no longer in the playlist, so an old report can't remove
  the wrong item.
- Each swap makes three writes, at least 1.5 s apart: add the song, move it
  before the video, and remove the video.
- On the first error, `apply` stops.

Every write is recorded in `undo-<timestamp>.json` before the next one starts.
To reverse a run, including one that stopped partway:

```sh
ytm-hygiene undo undo-20261018-120000.json --allow-playlist <playlist-id>
```

`undo` also takes `--dry-run`. It writes no log of its own.

## Curation: Obsidian song log

This uses two playlists you create in YouTube Music:

- **Inbox:** new songs on trial.
- **Rotation:** proven keepers, downloaded on your phone.

To skip the flags on every run, copy `ytm-hygiene.example.toml` to
`ytm-hygiene.toml` and fill in your vault folder and both playlist IDs. That
file is git-ignored. Command-line flags override it, and `--config <path>`
reads another file.

```sh
ytm-hygiene sync
ytm-hygiene sync --vault ~/Obsidian/MyVault --inbox <inbox-id> --rotation <rotation-id>
```

Run sync by hand whenever you like. It makes three read requests (both
playlists and your history). It writes one note per song to `Music/Songs/`,
then `Music/sync-state.yaml`, and creates `Music/Music Dashboard.md` once. The
dashboard needs the Dataview plugin.

Sync doesn't change YouTube. It prints the playlist moves it proposes.

### What counts as heard

A song is heard in a sync when it shows up in your history since the previous
sync. History has no timestamps, and a replayed song moves to the top instead
of showing up twice. So each sync saves the top 10 history songs in
`sync-state.yaml`. The next sync finds where those songs continue in their old
order and counts every song above that point as played, replays included.

If sync can't find them, it counts your whole history and prints a warning.
That happens on the first sync, or after roughly 200 plays since the last one.

Each note lists the syncs where its song was heard in `heard_syncs`. One sync
adds one entry, however many times the song played. `inbox_syncs` counts the
syncs that saw the song in the Inbox.

### How an Inbox song is decided

The first rule that matches wins:

| Signal | Result |
|---|---|
| Thumbs up | keeper, moves to Rotation |
| Thumbs down | rejected, removed from Inbox |
| Heard in 2 separate syncs | keeper |
| Never heard, in the Inbox for at least 3 syncs and at least 30 days (`--expire-days`) | expired, removed from Inbox |

A thumbs down on a Rotation song marks it rejected. You can also set `status`
(inbox / keeper / rejected) in any note yourself, and the next sync proposes
the matching move. Sync only changes a note's properties; anything you write
in the note body is kept. Notes from older versions keep working: sync adds the
new fields and drops `heard_days`. An older dashboard still shows the
`heard_days` column. Delete it, and the next sync writes the new one.

Skips aren't visible in YouTube data.

## Tests

```sh
python -m pytest -q   # no network; fixtures in tests/fixtures
```
