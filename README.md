# ytm-hygiene

Replaces music videos in a YouTube Music playlist with their audio-only song
versions (Art Tracks), so offline downloads take less space. It only edits
playlists and never downloads media.

Status: `backup`, `scan`, `evaluate` and `sync` (vault only) work. `apply` and `undo` aren't built
yet; they come after the accuracy test.

## Setup

```sh
pip install -e ".[dev]"
ytmusicapi browser        # paste request headers from a logged-in browser; writes browser.json
```

`browser.json` holds your session cookies and is git-ignored. The client uses
English and US settings.

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
  identical.
- **Artist:** 1.0 when an artist ID overlaps; otherwise fuzzy match on
  normalized names. For user uploads, the "Artist - Title" prefix counts as
  an artist.
- **Length:** the song may run at most 5 s longer or 15 s shorter than the
  video.

Flags force REVIEW:

- `duration`, `no_duration`
- `version:<tag>`: one side is live, remix, acoustic, sped up, slowed,
  instrumental, karaoke, cover or remaster, and the other isn't
- `clean_version` / `explicit`
- `official_source`
- `no_setVideoId`

Candidates must be available Art Tracks.

`report.csv` has two columns beyond the spec, `playlist_id` and
`old_setVideoId`, for `apply` to use later.

## Curation: Obsidian song log

This uses two playlists you create in YouTube Music:

- **Inbox:** new songs on trial.
- **Rotation:** proven keepers, downloaded on your phone.

```sh
ytm-hygiene sync --vault ~/Obsidian/MyVault --inbox <inbox-id> --rotation <rotation-id>
```

It makes three read requests (both playlists and your history). It then writes
one note per song to `Music/Songs/` and creates `Music/Music Dashboard.md`
once. The dashboard needs the Dataview plugin.

It doesn't change YouTube yet. It prints the playlist moves it would make;
applying them comes later with `apply`.

An Inbox song is decided by the first rule that matches:

| Signal | Result |
|---|---|
| Thumbs up | keeper, moves to Rotation |
| Thumbs down | rejected, removed from Inbox |
| Heard on 2 different days | keeper |
| Nothing after 14 days (`--expire-days`) | expired, removed from Inbox |

A thumbs down on a Rotation song marks it rejected. You can also set `status`
(inbox / keeper / rejected) in any note yourself, and the next sync proposes
the matching move. Sync only changes a note's properties; anything you write
in the note body is kept.

Listening history has no timestamps or play counts, only buckets like
"Today" and "This week". A day counts as heard only when the song shows up
under "Today" or "Yesterday", so run sync daily. Skips aren't visible in
YouTube data.

## Tests

```sh
python3 -m pytest -q   # no network; fixtures in tests/fixtures
```
