"""Write path: swap tracks in place (keeping position) and undo from a log."""

import json
from datetime import datetime
from pathlib import Path

from .client import Throttle
from .scan import save_backup

WRITE_DELAY_S = 1.5
OK = "STATUS_SUCCEEDED"


class ApplyError(RuntimeError):
    pass


def select_rows(rows: list[dict]) -> list[dict]:
    """Rows to swap: SWAP rows, or REVIEW rows the user marked verdict=correct."""
    return [
        r for r in rows
        if r.get("candidate_videoId") and r.get("old_setVideoId")
        and r.get("verdict") != "wrong"
        and (r.get("action") == "SWAP" or r.get("verdict") == "correct")
    ]  # fmt: skip


def _check_allowed(playlist_ids, allow_playlists) -> None:
    allowed = [allow_playlists] if isinstance(allow_playlists, str) else list(allow_playlists)
    bad = {p for p in playlist_ids if p not in allowed}
    if bad:
        raise ValueError(f"playlist {sorted(bad)} does not match --allow-playlist {sorted(allowed)}")


class _Writer:
    """Runs write calls: throttle, dry-run print, status check, log after each success.

    Each call targets `playlist_id` (default: the writer's own); each logged step records it.
    """

    def __init__(self, yt, playlist_id, throttle, dry_run, log_path=None, progress=print):
        self.yt, self.playlist_id, self.throttle = yt, playlist_id, throttle
        self.dry_run, self.log_path, self.progress = dry_run, log_path, progress
        self.steps: list[dict] = []

    def _save(self) -> None:
        if self.log_path:
            ids = sorted({s["playlist_id"] for s in self.steps})
            data = {"playlist_ids": ids, "steps": self.steps}
            self.log_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def run(self, call, describe: str):
        """Returns the call's response, or None on a dry run. Does not log."""
        self.progress(("[dry-run] " if self.dry_run else "") + describe)
        if self.dry_run:
            return None
        self.throttle.wait()
        try:
            response = call()
        except Exception as e:
            raise ApplyError(f"{describe}: {e}") from e
        status = response.get("status") if isinstance(response, dict) else response
        if status != OK:
            raise ApplyError(f"{describe}: unexpected response {response!r}")
        return response

    def add(self, video_id: str, playlist_id: str | None = None) -> str | None:
        """Add a video; returns its new setVideoId (None on a dry run)."""
        pid = playlist_id or self.playlist_id
        response = self.run(
            lambda: self.yt.add_playlist_items(pid, [video_id], duplicates=False),
            f"add {video_id}",
        )
        if response is None:
            return None
        try:
            new_set = response["playlistEditResults"][0]["setVideoId"]
        except (KeyError, IndexError, TypeError) as e:
            raise ApplyError(f"add {video_id}: no setVideoId in response {response!r}") from e
        self.steps.append({"op": "add", "playlist_id": pid, "videoId": video_id, "setVideoId": new_set})
        self._save()
        return new_set

    def move_before(self, set_id: str | None, before: str, playlist_id: str | None = None) -> None:
        pid = playlist_id or self.playlist_id
        response = self.run(
            lambda: self.yt.edit_playlist(pid, moveItem=(set_id, before)),
            f"move {set_id} before {before}",
        )
        if response is not None:
            self.steps.append({"op": "move", "playlist_id": pid, "setVideoId": set_id, "before": before})
            self._save()

    def remove(self, video_id: str, set_id: str, playlist_id: str | None = None, **extra) -> None:
        pid = playlist_id or self.playlist_id
        response = self.run(
            lambda: self.yt.remove_playlist_items(pid, [{"videoId": video_id, "setVideoId": set_id}]),
            f"remove {video_id} ({set_id})",
        )
        if response is not None:
            self.steps.append(
                {"op": "remove", "playlist_id": pid, "videoId": video_id, "setVideoId": set_id, **extra}
            )
            self._save()

    def log_if_written(self) -> Path | None:
        return self.log_path if self.steps else None


def new_log_path(log_dir: Path) -> Path:
    return log_dir / f"undo-{datetime.now():%Y%m%d-%H%M%S}.json"


def apply_rows(
    yt,
    rows: list[dict],
    allow_playlist: str,
    max_ops: int | None = None,
    dry_run: bool = False,
    throttle: Throttle | None = None,
    log_dir: Path = Path("."),
    backup_dir: Path = Path("backups"),
    progress=print,
) -> dict:
    """Swap each selected row's track in place. Returns counts and the undo log path."""
    selected = select_rows(rows)
    _check_allowed({r["playlist_id"] for r in selected}, allow_playlist)
    result = {"selected": len(selected), "swapped": 0, "stale": 0, "log": None}
    if not selected:
        return result

    playlist = yt.get_playlist(allow_playlist, limit=None)  # the one read
    present = {(t.get("setVideoId"), t.get("videoId")) for t in playlist.get("tracks") or []}
    todo = []
    for r in selected:
        if (r["old_setVideoId"], r["old_videoId"]) in present:
            todo.append(r)
        else:
            result["stale"] += 1
            progress(f"skip position {r['position']} {r['title']!r}: no longer in playlist (stale report)")
    if max_ops is not None:
        todo = todo[:max_ops]
    if not todo:
        return result

    log_path = None
    if not dry_run:
        save_backup(playlist, allow_playlist, backup_dir)
        log_path = new_log_path(log_dir)
        result["log"] = log_path
    w = _Writer(yt, allow_playlist, throttle or Throttle(WRITE_DELAY_S), dry_run, log_path, progress)
    for r in todo:
        progress(f"swap position {r['position']}: {r['title']!r}")
        new_set = w.add(r["candidate_videoId"])
        w.move_before(new_set, r["old_setVideoId"])
        w.remove(r["old_videoId"], r["old_setVideoId"], new_setVideoId=new_set)
        result["swapped"] += 1
    return result


def undo(
    yt,
    log_path: Path,
    allow_playlists: list[str],
    dry_run: bool = False,
    throttle: Throttle | None = None,
    progress=print,
) -> dict:
    """Replay a log in reverse. Every playlist in the log must be allowed."""
    log = json.loads(Path(log_path).read_text(encoding="utf-8"))
    _check_allowed(log["playlist_ids"], allow_playlists)
    w = _Writer(yt, None, throttle or Throttle(WRITE_DELAY_S), dry_run, None, progress)
    undone = 0
    for step in reversed(log["steps"]):
        if step["op"] == "remove":
            # Put the old video back, directly before the new one it was swapped for.
            # A removal with no replacement goes back at the end of the playlist.
            pid = step["playlist_id"]
            restored = w.add(step["videoId"], pid)
            if step.get("new_setVideoId"):
                w.move_before(restored, step["new_setVideoId"], pid)
        elif step["op"] == "add":
            w.remove(step["videoId"], step["setVideoId"], step["playlist_id"])
        undone += 1  # a move needs nothing
    return {"undone": undone}


def apply_moves(
    yt,
    moves: list,
    inbox_id: str,
    rotation_id: str,
    inbox_tracks: list[dict],
    rotation_tracks: list[dict],
    max_ops: int | None = 20,
    dry_run: bool = False,
    throttle: Throttle | None = None,
    log_dir: Path = Path("."),
    progress=print,
) -> dict:
    """Carry out sync moves on the Inbox and Rotation only, using the setVideoIds
    from the tracks sync already fetched. max_ops counts moves, not writes.

    Returns done/skipped counts and the undo log path. On ApplyError the exception
    carries .done and .log."""
    sets = {
        inbox_id: {t["videoId"]: t.get("setVideoId") for t in inbox_tracks if t.get("videoId")},
        rotation_id: {t["videoId"]: t.get("setVideoId") for t in rotation_tracks if t.get("videoId")},
    }
    result = {"done": 0, "skipped": 0, "log": None}
    todo = moves[:max_ops] if max_ops is not None else list(moves)
    if not todo:
        return result
    log_path = None if dry_run else new_log_path(log_dir)
    w = _Writer(yt, None, throttle or Throttle(WRITE_DELAY_S), dry_run, log_path, progress)
    try:
        for m in todo:
            source = rotation_id if m.action == "remove_rotation" else inbox_id
            set_id = sets[source].get(m.video_id)
            if not set_id:
                result["skipped"] += 1
                progress(f"skip {m.action} {m.title!r}: not in the playlist or no setVideoId")
                continue
            progress(f"{m.action}: {m.title} ({m.reason})")
            if m.action == "promote" and m.video_id not in sets[rotation_id]:
                w.add(m.video_id, rotation_id)
            w.remove(m.video_id, set_id, source)
            result["done"] += 1
    except ApplyError as e:
        e.done, e.log = result["done"], w.log_if_written()
        raise
    result["log"] = w.log_if_written()
    return result


def add_songs(
    yt,
    video_ids: list[str],
    playlist_id: str,
    max_ops: int | None = 20,
    dry_run: bool = False,
    throttle: Throttle | None = None,
    log_dir: Path = Path("."),
    progress=print,
) -> dict:
    """Add songs to one playlist, stopping on the first error. Returns the video IDs
    added (on a dry run, those that would be) and the undo log path. On ApplyError the
    exception carries .added and .log."""
    todo = video_ids[:max_ops] if max_ops is not None else list(video_ids)
    result = {"added": [], "log": None}
    if not todo:
        return result
    log_path = None if dry_run else new_log_path(log_dir)
    w = _Writer(yt, playlist_id, throttle or Throttle(WRITE_DELAY_S), dry_run, log_path, progress)
    try:
        for vid in todo:
            w.add(vid)
            result["added"].append(vid)
    except ApplyError as e:
        e.added, e.log = result["added"], w.log_if_written()
        raise
    result["log"] = w.log_if_written()
    return result
