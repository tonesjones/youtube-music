from datetime import date, timedelta

from ytm_hygiene.sync import EXPIRED, INBOX, KEEPER, REJECTED, heard_on, sync
from ytm_hygiene.vault import DASHBOARD, load_songs, save_songs

TODAY = date(2026, 10, 19)


def track(vid, title="Song", like="INDIFFERENT"):
    return {
        "videoId": vid,
        "title": title,
        "artists": [{"name": "Artist", "id": "UC1"}],
        "album": {"name": "Album", "id": "MPRE1"},
        "videoType": "MUSIC_VIDEO_TYPE_ATV",
        "likeStatus": like,
    }


def played(vid, when):
    return {"videoId": vid, "played": when}


def run(notes=None, inbox=(), rotation=(), history=(), today=TODAY):
    return sync(notes or {}, list(inbox), list(rotation), list(history), today)


def test_heard_on_maps_buckets_to_days():
    heard = heard_on([played("a", "Today"), played("b", "Yesterday"), played("c", "This week")], TODAY)
    assert heard == {"a": TODAY, "b": TODAY - timedelta(days=1), "c": None}


def test_new_inbox_song_gets_note_and_no_move():
    notes, moves = run(inbox=[track("a")])
    assert notes["a"]["status"] == INBOX
    assert notes["a"]["playlist"] == "inbox"
    assert notes["a"]["added"] == TODAY
    assert moves == []


def test_thumbs_up_promotes():
    notes, moves = run(inbox=[track("a", like="LIKE")])
    assert notes["a"]["status"] == KEEPER
    assert [(m.action, m.reason) for m in moves] == [("promote", "thumbs up")]


def test_thumbs_down_rejects():
    notes, moves = run(inbox=[track("a", like="DISLIKE")])
    assert notes["a"]["status"] == REJECTED
    assert moves[0].action == "remove_inbox"


def test_heard_on_two_days_promotes():
    notes, _ = run(inbox=[track("a")], history=[played("a", "Yesterday")])
    assert notes["a"]["status"] == INBOX
    notes, moves = run(notes, inbox=[track("a")], history=[played("a", "Today")])
    assert notes["a"]["status"] == KEEPER
    assert moves[0].reason == "heard on 2 days"


def test_same_day_twice_counts_once():
    notes, _ = run(inbox=[track("a")], history=[played("a", "Today")])
    notes, _ = run(notes, inbox=[track("a")], history=[played("a", "Today")])
    assert notes["a"]["heard_days"] == [TODAY]
    assert notes["a"]["status"] == INBOX


def test_never_heard_expires():
    notes, _ = run(inbox=[track("a")], today=TODAY - timedelta(days=14))
    notes, moves = run(notes, inbox=[track("a")])
    assert notes["a"]["status"] == EXPIRED
    assert (moves[0].action, moves[0].reason) == ("remove_inbox", "never heard")


def test_undated_history_counts_as_heard_not_as_a_day():
    notes, _ = run(inbox=[track("a")], history=[played("a", "Last week")])
    assert notes["a"]["first_heard"] == TODAY
    assert notes["a"]["heard_days"] == []


def test_status_edited_in_note_is_respected():
    notes, _ = run(inbox=[track("a")])
    notes["a"]["status"] = KEEPER
    _, moves = run(notes, inbox=[track("a")])
    assert [(m.action, m.reason) for m in moves] == [("promote", "status set in note")]


def test_rotation_song_disliked_is_removed():
    notes, moves = run(rotation=[track("r", like="DISLIKE")])
    assert notes["r"]["status"] == REJECTED
    assert moves[0].action == "remove_rotation"


def test_rotation_song_starts_as_keeper():
    notes, moves = run(rotation=[track("r")])
    assert notes["r"]["status"] == KEEPER and notes["r"]["source"] == "rotation"
    assert moves == []


def test_song_removed_from_playlists_keeps_status():
    notes, _ = run(inbox=[track("a", like="LIKE")])
    notes, moves = run(notes)
    assert notes["a"]["playlist"] is None and notes["a"]["status"] == KEEPER
    assert moves == []


def test_vault_round_trip_keeps_body_and_skips_unchanged(tmp_path):
    notes, _ = run(inbox=[track("a", title="夜に駆ける")], history=[played("a", "Today")])
    assert save_songs(tmp_path, {}, notes) == 1
    assert (tmp_path / DASHBOARD).exists()

    loaded = load_songs(tmp_path)
    path, meta, body = loaded["a"]
    assert path.name == "Artist - 夜に駆ける.md"
    assert meta == notes["a"]
    path.write_text(path.read_text(encoding="utf-8") + "my thoughts\n", encoding="utf-8")

    loaded = load_songs(tmp_path)
    assert save_songs(tmp_path, loaded, {"a": loaded["a"][1]}) == 0
    meta = {**loaded["a"][1], "status": KEEPER}
    assert save_songs(tmp_path, loaded, {"a": meta}) == 1
    _, meta, body = load_songs(tmp_path)["a"]
    assert meta["status"] == KEEPER
    assert "my thoughts" in body


def test_name_collision_gets_video_id_suffix(tmp_path):
    notes, _ = run(inbox=[track("a"), track("b")])
    save_songs(tmp_path, {}, notes)
    names = sorted(p.name for p in (tmp_path / "Music/Songs").glob("*.md"))
    assert names == ["Artist - Song (b).md", "Artist - Song.md"]


def test_notes_have_no_yaml_anchors(tmp_path):
    notes, _ = run(inbox=[track("a")], history=[played("a", "Today")])
    save_songs(tmp_path, {}, notes)
    text = next((tmp_path / "Music/Songs").glob("*.md")).read_text(encoding="utf-8")
    assert "&id" not in text and "*id" not in text
