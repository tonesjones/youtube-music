"""Turn playlist contents, listening history and thumbs into song-note updates
and proposed playlist moves. Pure logic: the caller fetches and writes.

Statuses: inbox (on trial), keeper, rejected, expired.
Signals: thumbs up/down, and the syncs where a song showed up in history.
History has no timestamps and a replay moves a song to the top, so each sync
stores the top of history as an anchor. The next sync counts everything above
where that anchor resumes as played since.
"""

from dataclasses import dataclass
from datetime import date

INBOX, KEEPER, REJECTED, EXPIRED = "inbox", "keeper", "rejected", "expired"
KEEP_AFTER_SYNCS_HEARD = 2
EXPIRE_AFTER_SYNCS = 3
DEFAULT_EXPIRE_DAYS = 30
ANCHOR_SIZE = 10


@dataclass
class Move:
    action: str  # promote (Inbox -> Rotation) / remove_inbox / remove_rotation
    video_id: str
    title: str
    reason: str


@dataclass
class Result:
    notes: dict[str, dict]
    moves: list[Move]
    state: dict  # next sync-state.yaml: last_sync, anchor
    warning: str | None = None


def plays_since(history_ids: list[str], anchor: list[str]) -> tuple[list[str], bool]:
    """(videoIds played since the anchor was taken, whether the anchor was found).

    Below the resume point, history is the old history minus the songs replayed
    since, in the same order. So the resume point is the first position where
    the anchor songs not seen above it follow in their old order.
    """
    for i in range(len(history_ids)):
        above = set(history_ids[:i])
        rest = [v for v in anchor if v not in above]
        if rest and history_ids[i : i + len(rest)] == rest[: len(history_ids) - i]:
            return history_ids[:i], True
    return history_ids, False


def new_note(track: dict, source: str, status: str, today: date) -> dict:
    return {
        "videoId": track["videoId"],
        "title": track.get("title") or "",
        "artists": [a["name"] for a in track.get("artists") or [] if a.get("name")],
        "album": (track.get("album") or {}).get("name"),
        "videoType": (track.get("videoType") or "").removeprefix("MUSIC_VIDEO_TYPE_"),
        "url": f"https://music.youtube.com/watch?v={track['videoId']}",
        "status": status,
        "source": source,
        "playlist": None,
        "added": today,
        "first_heard": None,
        "last_heard": None,
        "heard_syncs": [],
        "inbox_syncs": 0,
        "like": "INDIFFERENT",
    }


def _upgrade(meta: dict) -> dict:
    """Copy a note, giving notes from the old daily sync the new fields."""
    meta = {k: v for k, v in meta.items() if k != "heard_days"}
    meta["heard_syncs"] = list(meta.get("heard_syncs") or [])
    meta["inbox_syncs"] = meta.get("inbox_syncs") or 0
    return meta


def sync(
    notes: dict[str, dict],
    inbox: list[dict],
    rotation: list[dict],
    history: list[dict],
    state: dict,
    today: date,
    expire_days: int = DEFAULT_EXPIRE_DAYS,
) -> Result:
    notes = {vid: _upgrade(meta) for vid, meta in notes.items()}

    for meta in notes.values():
        meta["playlist"] = None
    for name, tracks, default_status in (("inbox", inbox, INBOX), ("rotation", rotation, KEEPER)):
        for track in tracks:
            if not track.get("videoId"):
                continue
            meta = notes.setdefault(track["videoId"], new_note(track, name, default_status, today))
            meta["playlist"] = name
            meta["like"] = track.get("likeStatus") or meta.get("like") or "INDIFFERENT"
            if name == "inbox":
                meta["inbox_syncs"] += 1

    history_ids = [h["videoId"] for h in history if h.get("videoId")]
    played, found = plays_since(history_ids, state.get("anchor") or [])
    warning = None
    if not found:
        warning = (
            "No anchor from the last sync found in history (first sync, or ~200+ plays since). "
            "Counting all of history as heard."
        )
    for video_id in set(played):
        meta = notes.get(video_id)
        if meta is None:
            continue
        if today not in meta["heard_syncs"]:
            meta["heard_syncs"].append(today)
        meta["first_heard"] = meta.get("first_heard") or today
        meta["last_heard"] = today

    moves = []
    for video_id, meta in notes.items():
        title = f"{', '.join(meta.get('artists') or [])} - {meta.get('title')}"
        if meta["playlist"] == "inbox":
            if meta["status"] == INBOX:
                meta["status"], reason = _judge(meta, today, expire_days)
            else:
                reason = "status set in note"
            if meta["status"] == KEEPER:
                moves.append(Move("promote", video_id, title, reason))
            elif meta["status"] in (REJECTED, EXPIRED):
                moves.append(Move("remove_inbox", video_id, title, reason))
        elif meta["playlist"] == "rotation":
            if meta["like"] == "DISLIKE":
                meta["status"] = REJECTED
            if meta["status"] in (REJECTED, EXPIRED):
                moves.append(Move("remove_rotation", video_id, title, f"status {meta['status']}"))

    new_state = {"last_sync": today, "anchor": history_ids[:ANCHOR_SIZE]}
    return Result(notes, moves, new_state, warning)


def _judge(meta: dict, today: date, expire_days: int) -> tuple[str, str]:
    if meta["like"] == "LIKE":
        return KEEPER, "thumbs up"
    if meta["like"] == "DISLIKE":
        return REJECTED, "thumbs down"
    if len(meta["heard_syncs"]) >= KEEP_AFTER_SYNCS_HEARD:
        return KEEPER, f"heard in {len(meta['heard_syncs'])} syncs"
    if (
        not meta["heard_syncs"]
        and meta["inbox_syncs"] >= EXPIRE_AFTER_SYNCS
        and (today - meta["added"]).days >= expire_days
    ):
        return EXPIRED, "never heard"
    return INBOX, ""
