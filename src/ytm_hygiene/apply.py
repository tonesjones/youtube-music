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


def _check_allowed(playlist_ids, allow_playlist: str) -> None:
    bad = {p for p in playlist_ids if p != allow_playlist}
    if bad:
        raise ValueError(f"playlist {sorted(bad)} does not match --allow-playlist {allow_playlist}")


class _Writer:
    """Runs write calls: throttle, dry-run print, status check, log after each success."""

    def __init__(self, yt, playlist_id, throttle, dry_run, log_path=None, progress=print):
        self.yt, self.playlist_id, self.throttle = yt, playlist_id, throttle
        self.dry_run, self.log_path, self.progress = dry_run, log_path, progress
        self.steps: list[dict] = []

    def _save(self) -> None:
        if self.log_path:
            data = {"playlist_id": self.playlist_id, "steps": self.steps}
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

    def add(self, video_id: str) -> str | None:
        """Add a video; returns its new setVideoId (None on a dry run)."""
        response = self.run(
            lambda: self.yt.add_playlist_items(self.playlist_id, [video_id], duplicates=False),
            f"add {video_id}",
        )
        if response is None:
            return None
        try:
            new_set = response["playlistEditResults"][0]["setVideoId"]
        except (KeyError, IndexError, TypeError) as e:
            raise ApplyError(f"add {video_id}: no setVideoId in response {response!r}") from e
        self.steps.append({"op": "add", "videoId": video_id, "setVideoId": new_set})
        self._save()
        return new_set

    def move_before(self, set_id: str | None, before: str) -> None:
        response = self.run(
            lambda: self.yt.edit_playlist(self.playlist_id, moveItem=(set_id, before)),
            f"move {set_id} before {before}",
        )
        if response is not None:
            self.steps.append({"op": "move", "setVideoId": set_id, "before": before})
            self._save()

    def remove(self, video_id: str, set_id: str, **extra) -> None:
        response = self.run(
            lambda: self.yt.remove_playlist_items(
                self.playlist_id, [{"videoId": video_id, "setVideoId": set_id}]
            ),
            f"remove {video_id} ({set_id})",
        )
        if response is not None:
            self.steps.append({"op": "remove", "videoId": video_id, "setVideoId": set_id, **extra})
            self._save()


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
        log_path = log_dir / f"undo-{datetime.now():%Y%m%d-%H%M%S}.json"
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
    allow_playlist: str,
    dry_run: bool = False,
    throttle: Throttle | None = None,
    progress=print,
) -> dict:
    """Replay a log in reverse. Returns the number of steps undone."""
    log = json.loads(Path(log_path).read_text(encoding="utf-8"))
    _check_allowed({log["playlist_id"]}, allow_playlist)
    w = _Writer(yt, allow_playlist, throttle or Throttle(WRITE_DELAY_S), dry_run, None, progress)
    undone = 0
    for step in reversed(log["steps"]):
        if step["op"] == "remove":
            # Put the old video back, directly before the new one it was swapped for.
            restored = w.add(step["videoId"])
            w.move_before(restored, step["new_setVideoId"])
        elif step["op"] == "add":
            w.remove(step["videoId"], step["setVideoId"])
        undone += 1  # a move needs nothing
    return {"undone": undone}
