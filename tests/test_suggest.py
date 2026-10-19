import json
from datetime import date

import pytest
from fakes import FakeYT, NoThrottle

from ytm_hygiene import cli
from ytm_hygiene.apply import ApplyError, undo
from ytm_hygiene.suggest import find_song, parse_lines, seed, suggest
from ytm_hygiene.sync import new_note
from ytm_hygiene.vault import load_songs, save_songs

INBOX = "PLinbox"
TODAY = date(2026, 10, 19)


def song(vid, title, artist, **kw):
    return {
        "videoId": vid,
        "title": title,
        "artists": [{"name": artist, "id": f"id-{artist}"}],
        "album": {"name": "Album"},
        "videoType": "MUSIC_VIDEO_TYPE_ATV",
        "isAvailable": True,
        "resultType": "song",
        **kw,
    }


def results(*pairs):
    """Search results keyed by the query find_song builds: '<artist> <title>'."""
    return {f"{artist} {title}": [song(vid, title, artist)] for vid, artist, title in pairs}


def note(vid, artist, title, status="inbox"):
    return {**new_note(song(vid, title, artist), "sync", status, TODAY)}


def run(yt, lines, notes=None, tmp_path=None, **kw):
    kw.setdefault("search_throttle", NoThrottle())
    kw.setdefault("write_throttle", NoThrottle())
    kw.setdefault("progress", lambda *_: None)
    return suggest(yt, lines, notes or {}, INBOX, TODAY, log_dir=tmp_path, **kw)


def test_parse_lines():
    text = "# header\n\nAdele - Hello\n  Queen - Bohemian Rhapsody  \n#skip\n"
    assert parse_lines(text) == ["Adele - Hello", "Queen - Bohemian Rhapsody"]


def test_seed_lists_keepers_then_rejected_and_expired():
    notes = {
        "k": note("k", "Adele", "Hello", "keeper"),
        "r": note("r", "Queen", "Radio", "rejected"),
        "e": note("e", "Abba", "Waterloo", "expired"),
        "i": note("i", "Pink", "Try", "inbox"),
    }
    out = seed(notes)
    assert "Adele - Hello" in out and "Queen - Radio" in out and "Abba - Waterloo" in out
    assert "Pink - Try" not in out
    assert out.index("Adele - Hello") < out.index("Queen - Radio")


def test_seed_cli_makes_no_requests(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    save_songs(vault, {}, {"k": note("k", "Adele", "Hello", "keeper")})

    def boom(_auth):
        raise AssertionError("network used")

    monkeypatch.setattr(cli, "make_client", boom)
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'vault = "{vault.as_posix()}"\n')  # no inbox needed for --seed
    (tmp_path / "browser.json").write_text("{}")
    cli.main(["--auth", str(tmp_path / "browser.json"), "suggest", "--seed", "--config", str(cfg)])
    assert "Adele - Hello" in capsys.readouterr().out


def test_one_search_per_line_and_adds_to_inbox(tmp_path):
    yt = FakeYT(search_results=results(("v1", "Adele", "Hello"), ("v2", "Queen", "Radio Ga Ga")))
    res = run(yt, ["Adele - Hello", "Queen - Radio Ga Ga", "Nobody - Nothing"], tmp_path=tmp_path)
    searches = [c for c in yt.calls if c[0] == "search"]
    # one search per line; only the empty result retries once, unfiltered (search_songs fallback)
    assert len(searches) == 2 + 2
    assert yt.writes() == [("add", INBOX, "v1"), ("add", INBOX, "v2")]
    assert res["not_found"] == ["Nobody - Nothing"]


def test_max_ops_caps_adds(tmp_path):
    yt = FakeYT(search_results=results(("v1", "Adele", "Hello"), ("v2", "Queen", "Radio Ga Ga")))
    res = run(yt, ["Adele - Hello", "Queen - Radio Ga Ga"], max_ops=1, tmp_path=tmp_path)
    assert yt.writes() == [("add", INBOX, "v1")]
    assert list(res["new_notes"]) == ["v1"]


def test_dry_run_writes_nothing(tmp_path):
    yt = FakeYT(search_results=results(("v1", "Adele", "Hello")))
    res = run(yt, ["Adele - Hello"], dry_run=True, tmp_path=tmp_path)
    assert yt.writes() == [] and res["new_notes"] == {} and res["log"] is None
    assert not list(tmp_path.glob("undo-*.json"))
    assert [c[0] for c in yt.calls] == ["search"]


def test_existing_note_skipped_any_status(tmp_path):
    yt = FakeYT(search_results=results(("v1", "Adele", "Hello"), ("v2", "Queen", "Radio Ga Ga")))
    notes = {"v1": note("v1", "Adele", "Hello", "rejected")}
    # a note under another videoId but the same artist and title also blocks the add
    notes["old"] = note("old", "Queen", "Radio Ga Ga", "expired")
    res = run(yt, ["Adele - Hello", "Queen - Radio Ga Ga"], notes, tmp_path=tmp_path)
    assert yt.writes() == [] and len(res["skipped"]) == 2


def test_new_notes_are_claude_inbox(tmp_path):
    yt = FakeYT(search_results=results(("v1", "Adele", "Hello")))
    note_ = run(yt, ["Adele - Hello"], tmp_path=tmp_path)["new_notes"]["v1"]
    assert note_["source"] == "claude" and note_["status"] == "inbox" and note_["playlist"] == "inbox"
    assert note_["added"] == TODAY


def test_low_score_and_version_mismatch_are_not_found():
    th = NoThrottle()
    yt = FakeYT(
        search_results={
            "Adele Hello": [song("v1", "Hello (Live)", "Adele")],
            "Adele Skyfall": [song("v2", "Someone Like You", "Adele")],
            "Adele Water": [song("v3", "Water", "Other Person")],
        }
    )
    assert find_song(yt, "Adele - Hello", th) is None  # version:live
    assert find_song(yt, "Adele - Skyfall", th) is None  # title mismatch
    assert find_song(yt, "Adele - Water", th) is None  # artist mismatch
    assert find_song(yt, "no separator here", th) is None


def test_non_art_track_is_not_used():
    yt = FakeYT(search_results={"Adele Hello": [song("v1", "Hello", "Adele", videoType="MUSIC_VIDEO_TYPE_OMV")]})
    assert find_song(yt, "Adele - Hello", NoThrottle()) is None


def test_undo_removes_added_songs(tmp_path):
    yt = FakeYT(search_results=results(("v1", "Adele", "Hello"), ("v2", "Queen", "Radio Ga Ga")))
    log = run(yt, ["Adele - Hello", "Queen - Radio Ga Ga"], tmp_path=tmp_path)["log"]
    yt2 = FakeYT()
    undo(yt2, log, [INBOX], throttle=NoThrottle(), progress=lambda *_: None)
    assert yt2.writes() == [("remove", INBOX, "v2", "new2"), ("remove", INBOX, "v1", "new1")]


def test_stop_on_error_keeps_notes_for_added(tmp_path):
    yt = FakeYT(search_results=results(("v1", "Adele", "Hello"), ("v2", "Queen", "Radio Ga Ga")), fail_on=2)
    with pytest.raises(ApplyError) as ei:
        run(yt, ["Adele - Hello", "Queen - Radio Ga Ga"], tmp_path=tmp_path)
    assert list(ei.value.new_notes) == ["v1"]
    assert len(yt.writes()) == 2
    assert json.loads(ei.value.log.read_text())["playlist_ids"] == [INBOX]


def test_cli_suggest_saves_notes_only_for_real_adds(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'vault = "{vault.as_posix()}"\ninbox = "{INBOX}"\n')
    auth = tmp_path / "browser.json"
    auth.write_text("{}")
    songs = tmp_path / "songs.txt"
    songs.write_text("Adele - Hello\n")
    yt = FakeYT(search_results=results(("v1", "Adele", "Hello")))
    monkeypatch.setattr(cli, "make_client", lambda _auth: yt)
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.chdir(tmp_path)
    base = ["--auth", str(auth), "suggest", str(songs), "--config", str(cfg)]
    cli.main(base + ["--dry-run"])
    assert yt.writes() == [] and not (vault / "Music/Songs").exists()
    cli.main(base)
    assert yt.writes() == [("add", INBOX, "v1")]
    assert load_songs(vault)["v1"][1]["source"] == "claude"


def test_exactly_one_search_per_line_when_results_exist(tmp_path):
    yt = FakeYT(search_results=results(("v1", "Adele", "Hello"), ("v2", "Queen", "Radio Ga Ga")))
    run(yt, ["Adele - Hello", "Queen - Radio Ga Ga"], dry_run=True, tmp_path=tmp_path)
    assert [c[0] for c in yt.calls] == ["search", "search"]
