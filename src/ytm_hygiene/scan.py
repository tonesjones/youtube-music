"""Read-only: back up a playlist and classify every track into report rows."""

import csv
import json
from datetime import datetime
from pathlib import Path

from .client import Throttle
from .match import DEFAULT_THRESHOLD, Decision, decide, needs_search, parse_original

COLUMNS = [
    "position", "title", "artist", "old_videoId", "old_type", "old_url",
    "candidate_title", "candidate_artist", "candidate_videoId", "candidate_url",
    "score", "duration_delta_s", "explicit_match", "flags", "action",
    "playlist_id", "old_setVideoId", "verdict",
]  # fmt: skip


def watch_url(video_id: str | None) -> str:
    return f"https://music.youtube.com/watch?v={video_id}" if video_id else ""


def save_backup(playlist: dict, playlist_id: str, directory: Path = Path("backups")) -> Path:
    directory.mkdir(exist_ok=True)
    path = directory / f"{playlist_id}-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(playlist, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def search_songs(yt, query: str, throttle: Throttle) -> list[dict]:
    throttle.wait()
    results = yt.search(query, filter="songs")
    if results:
        return results
    # Filtered search can come back empty for some languages; fall back once.
    throttle.wait()
    return [r for r in yt.search(query) if r.get("resultType") == "song"]


def _artists(item: dict) -> str:
    return ", ".join(a.get("name") or "" for a in item.get("artists") or [])


def make_row(position: int, playlist_id: str, track: dict, decision: Decision) -> dict:
    row = dict.fromkeys(COLUMNS, "")
    row.update(
        position=position,
        title=track.get("title") or "",
        artist=_artists(track),
        old_videoId=track.get("videoId") or "",
        old_type=(track.get("videoType") or "").removeprefix("MUSIC_VIDEO_TYPE_"),
        old_url=watch_url(track.get("videoId")),
        flags=";".join(decision.flags),
        action=decision.action,
        playlist_id=playlist_id,
        old_setVideoId=track.get("setVideoId") or "",
    )
    if decision.best:
        cand = decision.best.candidate
        row.update(
            candidate_title=cand.get("title") or "",
            candidate_artist=_artists(cand),
            candidate_videoId=cand["videoId"],
            candidate_url=watch_url(cand["videoId"]),
            score=f"{decision.best.score:.3f}",
            duration_delta_s="" if decision.best.duration_delta is None else decision.best.duration_delta,
            explicit_match="yes" if decision.best.explicit_match else "no",
        )
    return row


def scan_playlist(
    yt,
    playlist: dict,
    playlist_id: str,
    threshold: float = DEFAULT_THRESHOLD,
    clean: bool = False,
    throttle: Throttle | None = None,
    progress=print,
) -> list[dict]:
    throttle = throttle or Throttle()
    rows = []
    tracks = playlist.get("tracks") or []
    for position, track in enumerate(tracks, 1):
        candidates = []
        if needs_search(track):
            query = parse_original(track).query
            progress(f"[{position}/{len(tracks)}] searching: {query}")
            candidates = search_songs(yt, query, throttle)
        rows.append(make_row(position, playlist_id, track, decide(track, candidates, threshold, clean)))
    return rows


def write_report(rows: list[dict], path: Path) -> None:
    # utf-8-sig so Excel shows non-English titles correctly.
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_report(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

