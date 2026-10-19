"""Suggest step: a taste summary to paste into a chat, and a way to add the
"Artist - Title" lines Claude replies with to the Inbox."""

from datetime import date
from pathlib import Path

from .apply import ApplyError, add_songs
from .client import Throttle
from .match import (
    WEIGHTS,
    artist_score,
    clean_title,
    is_usable,
    normalize,
    normalize_artist,
    parse_original,
    title_score,
    version_tags,
)
from .scan import search_songs
from .sync import EXPIRED, INBOX, KEEPER, REJECTED, new_note

MIN_SCORE = 0.85  # title + artist only
SEARCH_DELAY_S = 1.0


def _label(meta: dict) -> str:
    artists = meta.get("artists") or []
    return f"{artists[0] if artists else 'Unknown'} - {meta.get('title') or meta.get('videoId')}"


def seed(notes: dict[str, dict]) -> str:
    """Keepers, then rejected and expired songs, as 'Artist - Title' lines. No network."""
    keepers = sorted(_label(m) for m in notes.values() if m.get("status") == KEEPER)
    rejected = sorted(_label(m) for m in notes.values() if m.get("status") in (REJECTED, EXPIRED))
    parts = ["Songs I keep:", *(keepers or ["(none yet)"])]
    parts += ["", "Songs I rejected or let expire (don't suggest these):", *(rejected or ["(none)"])]
    parts += ["", "Suggest new songs I might like, one per line, as: Artist - Title"]
    return "\n".join(parts)


def parse_lines(text: str) -> list[str]:
    """One 'Artist - Title' per line; blank lines and lines starting with # are skipped."""
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def find_song(yt, line: str, throttle: Throttle) -> dict | None:
    """Best usable Art Track for an 'Artist - Title' line, or None. One search."""
    artist, sep, title = line.partition(" - ")
    artist, title = artist.strip(), title.strip()
    if not sep or not artist or not title:
        return None
    orig = parse_original({"title": title, "artists": [{"name": artist}]})
    scored = []
    for cand in search_songs(yt, orig.query, throttle):
        if not is_usable(orig.track, cand):
            continue
        t = title_score(orig.clean, clean_title(cand.get("title") or ""))
        a = artist_score(orig, cand.get("artists") or [])
        score = (WEIGHTS["title"] * t + WEIGHTS["artist"] * a) / (WEIGHTS["title"] + WEIGHTS["artist"])
        scored.append((score, cand))
    if not scored:
        return None
    score, best = max(scored, key=lambda s: s[0])
    if score < MIN_SCORE or orig.tags ^ version_tags(best.get("title") or ""):
        return None
    return best


def _key(meta: dict) -> tuple[str, str]:
    artists = meta.get("artists") or []
    return normalize_artist(artists[0] if artists else ""), normalize(meta.get("title") or "")


def find_new(
    yt,
    lines: list[str],
    notes: dict[str, dict],
    throttle: Throttle | None = None,
    progress=print,
) -> dict:
    """Search each line (one search per line, paced by `throttle`). Writes nothing.
    Returns found (candidate songs not in notes), skipped (lines whose song is
    already in notes) and not_found (lines)."""
    throttle = throttle or Throttle(SEARCH_DELAY_S)
    known = {_key(m) for m in notes.values()}
    found: list[dict] = []
    result = {"found": found, "skipped": [], "not_found": []}
    for line in lines:
        cand = find_song(yt, line, throttle)
        if cand is None:
            result["not_found"].append(line)
            progress(f"not found: {line}")
            continue
        cand_key = _key({"artists": [a.get("name") for a in cand.get("artists") or []], "title": cand.get("title")})
        if cand["videoId"] in notes or cand_key in known:
            result["skipped"].append(line)
            progress(f"already have a note: {line}")
            continue
        known.add(cand_key)
        found.append(cand)
        progress(f"found: {line} -> {cand['videoId']}")
    return result


def add_found(
    yt,
    found: list[dict],
    inbox_id: str,
    today: date,
    max_ops: int | None = 20,
    dry_run: bool = False,
    write_throttle: Throttle | None = None,
    log_dir: Path = Path("."),
    progress=print,
) -> dict:
    """Add candidates from find_new to the Inbox. Returns new_notes (for songs
    actually added; empty on a dry run) and the undo log path.

    On ApplyError the exception carries .new_notes and .log so the caller can still
    save notes for the songs that did get in."""

    def notes_for(video_ids) -> dict[str, dict]:
        by_id = {c["videoId"]: c for c in found}
        out = {}
        for vid in video_ids:
            note = new_note(by_id[vid], "claude", INBOX, today)
            note["playlist"] = "inbox"
            out[vid] = note
        return out

    try:
        added = add_songs(
            yt, [c["videoId"] for c in found], inbox_id, max_ops, dry_run, write_throttle, log_dir, progress
        )
    except ApplyError as e:
        e.new_notes = {} if dry_run else notes_for(e.added)
        raise
    result = {"new_notes": {}, "log": added["log"]}
    if not dry_run:
        result["new_notes"] = notes_for(added["added"])
    return result


def suggest(
    yt,
    lines: list[str],
    notes: dict[str, dict],
    inbox_id: str,
    today: date,
    max_ops: int | None = 20,
    dry_run: bool = False,
    search_throttle: Throttle | None = None,
    write_throttle: Throttle | None = None,
    log_dir: Path = Path("."),
    progress=print,
) -> dict:
    """find_new, then add_found. Returns found (candidates to add), skipped,
    not_found (lines), new_notes (for songs actually added; empty on a dry run) and
    the undo log path.

    On ApplyError the exception carries .new_notes and .log so the caller can still
    save notes for the songs that did get in."""
    found = find_new(yt, lines, notes, search_throttle, progress)
    added = add_found(
        yt, found["found"], inbox_id, today, max_ops, dry_run, write_throttle, log_dir, progress
    )
    return {**found, **added}
