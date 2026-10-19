"""Turn playlist contents, listening history and thumbs into song-note updates
and proposed playlist moves. Pure logic: the caller fetches and writes.

Statuses: inbox (on trial), keeper, rejected, expired.
Signals: thumbs up/down, and the days a song showed up in history. History has
no timestamps or play counts, only buckets like "Today" and "This week", so a
song counts as heard on a day only when synced daily ("Today"/"Yesterday").
"""

from dataclasses import dataclass
from datetime import date, timedelta

INBOX, KEEPER, REJECTED, EXPIRED = "inbox", "keeper", "rejected", "expired"
KEEP_AFTER_DAYS_HEARD = 2
DEFAULT_EXPIRE_DAYS = 14


@dataclass
class Move:
    action: str  # promote (Inbox -> Rotation) / remove_inbox / remove_rotation
    video_id: str
    title: str
    reason: str


def heard_on(history: list[dict], today: date) -> dict[str, date | None]:
    """videoId -> day heard, or None when history only says 'This week' etc."""
    offsets = {"today": 0, "yesterday": 1}
    heard: dict[str, date | None] = {}
    for item in history:
        offset = offsets.get((item.get("played") or "").strip().lower())
        day = today - timedelta(days=offset) if offset is not None else None
        if item.get("videoId") and (heard.get(item["videoId"]) is None):
            heard[item["videoId"]] = day
    return heard


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
        "heard_days": [],
        "like": "INDIFFERENT",
    }


def sync(
    notes: dict[str, dict],
    inbox: list[dict],
    rotation: list[dict],
    history: list[dict],
    today: date,
    expire_days: int = DEFAULT_EXPIRE_DAYS,
) -> tuple[dict[str, dict], list[Move]]:
    """Returns (all notes after the update, proposed playlist moves)."""
    notes = {vid: {**meta, "heard_days": list(meta.get("heard_days") or [])} for vid, meta in notes.items()}

    for meta in notes.values():
        meta["playlist"] = None
    for name, tracks, default_status in (("inbox", inbox, INBOX), ("rotation", rotation, KEEPER)):
        for track in tracks:
            if not track.get("videoId"):
                continue
            meta = notes.setdefault(track["videoId"], new_note(track, name, default_status, today))
            meta["playlist"] = name
            meta["like"] = track.get("likeStatus") or meta.get("like") or "INDIFFERENT"

    for video_id, day in heard_on(history, today).items():
        meta = notes.get(video_id)
        if meta is None:
            continue
        if day and day not in meta["heard_days"]:
            meta["heard_days"] = sorted(meta["heard_days"] + [day])
        seen = day or today
        meta["first_heard"] = meta.get("first_heard") or seen
        if not meta.get("last_heard") or seen > meta["last_heard"]:
            meta["last_heard"] = seen

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
    return notes, moves


def _judge(meta: dict, today: date, expire_days: int) -> tuple[str, str]:
    if meta["like"] == "LIKE":
        return KEEPER, "thumbs up"
    if meta["like"] == "DISLIKE":
        return REJECTED, "thumbs down"
    if len(meta["heard_days"]) >= KEEP_AFTER_DAYS_HEARD:
        return KEEPER, f"heard on {len(meta['heard_days'])} days"
    if (today - meta["added"]).days >= expire_days:
        return EXPIRED, "never heard" if not meta.get("first_heard") else "heard once, not again"
    return INBOX, ""
