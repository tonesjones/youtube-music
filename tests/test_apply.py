import json

import pytest

from ytm_hygiene.apply import ApplyError, apply_rows, select_rows, undo

PID = "PL123"


class NoThrottle:
    def __init__(self):
        self.waits = 0

    def wait(self):
        self.waits += 1


class FakeYT:
    def __init__(self, tracks, fail_on=None, log_check=None):
        self.tracks = tracks
        self.calls = []
        self.fail_on = fail_on  # 1-based index of the write call that fails
        self.log_check = log_check
        self.n = 0

    def get_playlist(self, pid, limit=None):
        self.calls.append(("get_playlist", pid))
        return {"tracks": self.tracks}

    def _write(self, name, args, response):
        if self.log_check:
            self.log_check(name)
        self.calls.append((name, *args))
        self.n += 1
        if self.fail_on == self.n:
            return {"error": "boom"}
        return response

    def add_playlist_items(self, pid, ids, duplicates=False):
        assert duplicates is False
        ok = {
            "status": "STATUS_SUCCEEDED",
            "playlistEditResults": [{"videoId": ids[0], "setVideoId": f"new{self.n + 1}"}],
        }
        return self._write("add", (ids[0],), ok)

    def edit_playlist(self, pid, moveItem=None):
        return self._write("move", moveItem, "STATUS_SUCCEEDED")

    def remove_playlist_items(self, pid, videos):
        return self._write("remove", (videos[0]["videoId"], videos[0]["setVideoId"]), "STATUS_SUCCEEDED")

    def writes(self):
        return [c for c in self.calls if c[0] != "get_playlist"]


def row(n, action="SWAP", verdict="", pid=PID):
    return {
        "position": n, "title": f"t{n}", "old_videoId": f"o{n}", "old_setVideoId": f"s{n}",
        "candidate_videoId": f"c{n}", "action": action, "verdict": verdict, "playlist_id": pid,
    }  # fmt: skip


def tracks(*ns):
    return [{"videoId": f"o{n}", "setVideoId": f"s{n}"} for n in ns]


def run(yt, rows, tmp_path, **kw):
    kw.setdefault("throttle", NoThrottle())
    kw.setdefault("progress", lambda *_: None)
    return apply_rows(yt, rows, PID, log_dir=tmp_path, backup_dir=tmp_path / "b", **kw)


def quiet_undo(yt, log, allow=(PID,), **kw):
    return undo(yt, log, list(allow), throttle=NoThrottle(), progress=lambda *_: None, **kw)


def test_row_selection():
    rows = [
        row(1),
        row(2, action="REVIEW"),
        row(3, action="REVIEW", verdict="correct"),
        row(4, verdict="wrong"),
        row(5, action="SWAP", verdict="correct"),
        {**row(6), "candidate_videoId": ""},
        {**row(7), "old_setVideoId": ""},
    ]
    assert [r["position"] for r in select_rows(rows)] == [1, 3, 5]


def test_allow_playlist_mismatch_refuses(tmp_path):
    yt = FakeYT(tracks(1, 2))
    with pytest.raises(ValueError):
        run(yt, [row(1), row(2, pid="OTHER")], tmp_path)
    assert yt.calls == []


def test_stale_row_skipped(tmp_path):
    yt = FakeYT(tracks(2))
    msgs = []
    res = run(yt, [row(1), row(2)], tmp_path, progress=msgs.append)
    assert res["stale"] == 1 and res["swapped"] == 1
    assert any("stale" in m for m in msgs)
    assert [c for c in yt.calls if c[0] == "get_playlist"] == [("get_playlist", PID)]
    assert all("o1" not in c and "s1" not in c for c in yt.writes())


def test_max_ops_cap(tmp_path):
    yt = FakeYT(tracks(1, 2, 3))
    res = run(yt, [row(1), row(2), row(3)], tmp_path, max_ops=2)
    assert res["swapped"] == 2
    assert len(yt.writes()) == 6


def test_dry_run_makes_no_writes(tmp_path):
    yt = FakeYT(tracks(1))
    msgs = []
    res = run(yt, [row(1)], tmp_path, dry_run=True, progress=msgs.append)
    assert yt.writes() == []
    assert any("add" in m for m in msgs) and any("remove" in m for m in msgs)
    assert res["log"] is None and not list(tmp_path.glob("undo-*.json"))


def test_write_order_and_move_before_old(tmp_path):
    yt = FakeYT(tracks(1))
    th = NoThrottle()
    res = run(yt, [row(1)], tmp_path, throttle=th)
    assert yt.writes() == [("add", "c1"), ("move", "new1", "s1"), ("remove", "o1", "s1")]
    assert th.waits == 3
    assert (tmp_path / "b").exists()
    assert res["log"].exists()


def test_stop_on_first_error_log_has_completed_steps(tmp_path):
    yt = FakeYT(tracks(1, 2), fail_on=2)  # move fails
    with pytest.raises(ApplyError):
        run(yt, [row(1), row(2)], tmp_path)
    assert len(yt.writes()) == 2
    log = json.loads(next(tmp_path.glob("undo-*.json")).read_text())
    assert [s["op"] for s in log["steps"]] == ["add"]
    assert log["playlist_ids"] == [PID]
    assert all(s["playlist_id"] == PID for s in log["steps"])


def test_exception_is_error(tmp_path):
    yt = FakeYT(tracks(1))

    def boom(*a, **k):
        raise RuntimeError("net")

    yt.add_playlist_items = boom
    with pytest.raises(ApplyError):
        run(yt, [row(1)], tmp_path)


def test_log_rewritten_after_each_write(tmp_path):
    seen = []

    def check(name):
        files = list(tmp_path.glob("undo-*.json"))
        ops = [s["op"] for s in json.loads(files[0].read_text())["steps"]] if files else []
        seen.append((name, ops))

    yt = FakeYT(tracks(1), log_check=check)
    run(yt, [row(1)], tmp_path)
    assert seen == [("add", []), ("move", ["add"]), ("remove", ["add", "move"])]
    final = json.loads(next(tmp_path.glob("undo-*.json")).read_text())
    assert [s["op"] for s in final["steps"]] == ["add", "move", "remove"]
    assert final["steps"][0]["setVideoId"] == "new1"


def test_undo_reverses_full_swap(tmp_path):
    log = run(FakeYT(tracks(1)), [row(1)], tmp_path)["log"]
    yt2 = FakeYT([])
    assert quiet_undo(yt2, log)["undone"] == 3
    # re-add old, move it before the new item, then remove the new item
    assert yt2.writes() == [("add", "o1"), ("move", "new1", "new1"), ("remove", "c1", "new1")]


def test_undo_partial_swap(tmp_path):
    with pytest.raises(ApplyError):
        run(FakeYT(tracks(1), fail_on=3), [row(1)], tmp_path)  # remove fails: add+move logged
    yt2 = FakeYT([])
    quiet_undo(yt2, next(tmp_path.glob("undo-*.json")))
    assert yt2.writes() == [("remove", "c1", "new1")]


def test_undo_refuses_wrong_playlist_and_dry_run(tmp_path):
    log = run(FakeYT(tracks(1)), [row(1)], tmp_path)["log"]
    yt2 = FakeYT([])
    with pytest.raises(ValueError):
        quiet_undo(yt2, log, allow=["OTHER"])
    quiet_undo(yt2, log, dry_run=True)
    assert yt2.calls == []
