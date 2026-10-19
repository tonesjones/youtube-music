import json

import pytest
from fakes import FakeYT, NoThrottle

from ytm_hygiene import cli
from ytm_hygiene.apply import ApplyError, apply_moves, undo
from ytm_hygiene.sync import Move
from ytm_hygiene.vault import load_songs, load_state

INBOX, ROT = "PLinbox", "PLrot"


def t(vid, set_id):
    return {"videoId": vid, "setVideoId": set_id}


def go(yt, moves, inbox, rot, tmp_path, **kw):
    kw.setdefault("throttle", NoThrottle())
    kw.setdefault("progress", lambda *_: None)
    return apply_moves(yt, moves, INBOX, ROT, inbox, rot, log_dir=tmp_path, **kw)


def mv(action, vid):
    return Move(action, vid, vid, "test")


def test_promote_adds_to_rotation_then_removes_from_inbox(tmp_path):
    yt = FakeYT()
    go(yt, [mv("promote", "a")], [t("a", "sa")], [], tmp_path)
    assert yt.writes() == [("add", ROT, "a"), ("remove", INBOX, "a", "sa")]


def test_promote_already_in_rotation_only_removes(tmp_path):
    yt = FakeYT()
    go(yt, [mv("promote", "a")], [t("a", "sa")], [t("a", "ra")], tmp_path)
    assert yt.writes() == [("remove", INBOX, "a", "sa")]


def test_removes_hit_the_right_playlist_without_reads(tmp_path):
    yt = FakeYT()
    go(yt, [mv("remove_inbox", "a"), mv("remove_rotation", "b")], [t("a", "sa")], [t("b", "rb")], tmp_path)
    assert yt.writes() == [("remove", INBOX, "a", "sa"), ("remove", ROT, "b", "rb")]
    assert yt.calls == yt.writes()  # no reads
    assert {c[1] for c in yt.writes()} <= {INBOX, ROT}


def test_dry_run_no_writes_no_log(tmp_path):
    yt = FakeYT()
    msgs = []
    res = go(yt, [mv("promote", "a")], [t("a", "sa")], [], tmp_path, dry_run=True, progress=msgs.append)
    assert yt.calls == [] and res["log"] is None and not list(tmp_path.glob("undo-*.json"))
    assert any("promote" in m for m in msgs) and any("remove" in m for m in msgs)


def test_max_ops_counts_moves_and_throttles_every_write(tmp_path):
    yt, th = FakeYT(), NoThrottle()
    inbox = [t("a", "sa"), t("b", "sb"), t("c", "sc")]
    res = go(yt, [mv("promote", v) for v in "abc"], inbox, [], tmp_path, max_ops=2, throttle=th)
    assert res["done"] == 2 and len(yt.writes()) == 4 and th.waits == 4


def test_missing_setvideoid_is_skipped(tmp_path):
    yt = FakeYT()
    res = go(yt, [mv("remove_inbox", "zzz")], [], [], tmp_path)
    assert res["skipped"] == 1 and yt.writes() == []


def test_stop_on_first_error_and_log_has_both_playlists(tmp_path):
    yt = FakeYT(fail_on=3)  # move 1 ok (2 writes), move 2's remove fails
    moves = [mv("promote", "a"), mv("remove_rotation", "b")]
    with pytest.raises(ApplyError) as ei:
        go(yt, moves, [t("a", "sa")], [t("b", "rb")], tmp_path)
    assert len(yt.writes()) == 3
    log = json.loads(ei.value.log.read_text())
    assert log["playlist_ids"] == sorted([INBOX, ROT])
    assert [(s["op"], s["playlist_id"]) for s in log["steps"]] == [("add", ROT), ("remove", INBOX)]


def test_undo_restores_both_playlists(tmp_path):
    moves = [mv("promote", "a"), mv("remove_rotation", "b")]
    log = go(FakeYT(), moves, [t("a", "sa")], [t("b", "rb")], tmp_path)["log"]
    yt = FakeYT()
    out = undo(yt, log, [INBOX, ROT], throttle=NoThrottle(), progress=lambda *_: None)
    assert out["undone"] == 3
    # reverse order: re-add b to Rotation (no move), re-add a to Inbox (no move), remove a from Rotation
    assert yt.writes() == [("add", ROT, "b"), ("add", INBOX, "a"), ("remove", ROT, "a", "new1")]


def test_undo_needs_every_playlist_allowed(tmp_path):
    log = go(FakeYT(), [mv("promote", "a")], [t("a", "sa")], [], tmp_path)["log"]
    yt = FakeYT()
    with pytest.raises(ValueError):
        undo(yt, log, [INBOX], throttle=NoThrottle(), progress=lambda *_: None)
    assert yt.calls == []


# --- CLI ---


def setup_cli(tmp_path, monkeypatch, yt):
    vault = tmp_path / "vault"
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'vault = "{vault.as_posix()}"\ninbox = "{INBOX}"\nrotation = "{ROT}"\n')
    auth = tmp_path / "browser.json"
    auth.write_text("{}")
    monkeypatch.setattr(cli, "make_client", lambda _auth: yt)
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.chdir(tmp_path)
    return vault, ["--auth", str(auth), "sync", "--config", str(cfg)]


def liked(vid, set_id):
    return {
        **t(vid, set_id),
        "title": "Song",
        "artists": [{"name": "A", "id": "u"}],
        "likeStatus": "LIKE",
        "videoType": "MUSIC_VIDEO_TYPE_ATV",
    }


def test_sync_without_apply_makes_no_writes(tmp_path, monkeypatch):
    yt = FakeYT({INBOX: [liked("a", "sa")]})
    vault, argv = setup_cli(tmp_path, monkeypatch, yt)
    cli.main(argv)
    assert yt.writes() == []
    assert load_songs(vault)["a"][1]["status"] == "keeper"


def test_sync_apply_writes_after_notes_and_state_saved(tmp_path, monkeypatch):
    yt = FakeYT({INBOX: [liked("a", "sa")]})
    vault, argv = setup_cli(tmp_path, monkeypatch, yt)
    seen = []
    orig = yt.add_playlist_items

    def spy(*a, **k):
        seen.append(("a" in load_songs(vault), load_state(vault) != {}))
        return orig(*a, **k)

    yt.add_playlist_items = spy
    cli.main(argv + ["--apply"])
    assert seen == [(True, True)]
    assert yt.writes() == [("add", ROT, "a"), ("remove", INBOX, "a", "sa")]
    assert list(tmp_path.glob("undo-*.json"))


def test_sync_apply_dry_run_and_max_ops(tmp_path, monkeypatch):
    yt = FakeYT({INBOX: [liked("a", "sa"), liked("b", "sb")]})
    vault, argv = setup_cli(tmp_path, monkeypatch, yt)
    cli.main(argv + ["--apply", "--dry-run"])
    assert yt.writes() == []
    cli.main(argv + ["--apply", "--max-ops", "1"])
    assert len(yt.writes()) == 2


def test_sync_apply_error_exits(tmp_path, monkeypatch):
    yt = FakeYT({INBOX: [liked("a", "sa")]}, fail_on=1)
    _, argv = setup_cli(tmp_path, monkeypatch, yt)
    with pytest.raises(SystemExit):
        cli.main(argv + ["--apply"])
    assert len(yt.writes()) == 1
