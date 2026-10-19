from datetime import date, timedelta

from ytm_hygiene.sync import EXPIRED, INBOX, KEEPER, REJECTED, sync
from ytm_hygiene.vault import DASHBOARD, load_songs, load_state, save_songs, save_state

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


def hist(*vids):
    return [{"videoId": v, "played": "Today"} for v in vids]


OLD = hist("o1", "o2", "o3")  # history at the previous sync
STATE = {"last_sync": TODAY - timedelta(days=7), "anchor": ["o1", "o2", "o3"]}


def run(notes=None, inbox=(), rotation=(), history=OLD, today=TODAY, state=STATE):
    """One sync; returns (notes, moves). History defaults to 'nothing new played'."""
    result = sync(notes or {}, list(inbox), list(rotation), list(history), state, today)
    return result.notes, result.moves


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


def test_heard_in_two_syncs_promotes():
    day1 = TODAY - timedelta(days=3)
    notes, _ = run(inbox=[track("a")], history=hist("a", "o1", "o2", "o3"), today=day1)
    assert notes["a"]["status"] == INBOX
    state = {"last_sync": day1, "anchor": ["a", "o1", "o2"]}
    notes, _ = run(notes, inbox=[track("a")], history=hist("a", "o1", "o2", "o3"), state=state)
    assert notes["a"]["status"] == INBOX  # nothing new since day1: the replay isn't visible
    notes, _ = run(notes, inbox=[track("a")], history=hist("x", "a", "o1", "o2"), state=state)
    assert notes["a"]["status"] == INBOX  # "a" is still at its anchor spot, so not replayed
    notes, moves = run(notes, inbox=[track("a")], history=hist("a", "x", "o1", "o2"), state=state)
    assert notes["a"]["status"] == KEEPER
    assert moves[0].reason == "heard in 2 syncs"


def test_never_heard_expires():
    notes = None
    for days_ago in (30, 15, 0):
        notes, moves = run(notes, inbox=[track("a")], today=TODAY - timedelta(days=days_ago))
    assert notes["a"]["status"] == EXPIRED
    assert (moves[0].action, moves[0].reason) == ("remove_inbox", "never heard")


def test_state_round_trip(tmp_path):
    assert load_state(tmp_path) == {}
    save_state(tmp_path, STATE)
    assert load_state(tmp_path) == STATE


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
    notes, _ = run(inbox=[track("a", title="夜に駆ける")], history=hist("a", "o1", "o2", "o3"))
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
    notes, _ = run(inbox=[track("a")], history=hist("a", "o1", "o2", "o3"))
    save_songs(tmp_path, {}, notes)
    text = next((tmp_path / "Music/Songs").glob("*.md")).read_text(encoding="utf-8")
    assert "&id" not in text and "*id" not in text


def _heard_in_two_syncs(like="INDIFFERENT"):
    """Song "a" heard on two syncs (3 days ago and today). Returns (result, day1)."""
    day1 = TODAY - timedelta(days=3)
    first = sync({}, [track("a")], [], hist("a", "o1", "o2", "o3"), STATE, day1)
    second = sync(first.notes, [track("a", like=like)], [], hist("a", "b", "o1", "o2", "o3"), first.state, TODAY)
    return second, day1


def _inbox_on_days(days_ago, like="INDIFFERENT"):
    """Song "a" seen in the Inbox on one sync per entry in days_ago, never heard."""
    notes = None
    for i, days in enumerate(days_ago):
        last = i == len(days_ago) - 1  # the thumb is set only before the final sync
        notes, moves = run(notes, inbox=[track("a", like=like if last else "INDIFFERENT")],
                           today=TODAY - timedelta(days=days))
    return notes, moves


def test_new_play_above_anchor_is_heard_and_song_below_is_not():
    notes, _ = run(inbox=[track("x"), track("b1")], history=hist("x", "o1", "o2", "o3", "b1"))
    assert notes["x"]["heard_syncs"] == [TODAY]
    assert notes["b1"]["heard_syncs"] == []


def test_replayed_anchor_song_is_heard():
    notes, _ = run(inbox=[track("o2")], history=hist("o2", "o1", "o3"))
    assert notes["o2"]["heard_syncs"] == [TODAY]


def test_no_anchor_counts_all_history_and_warns():
    result = sync({}, [track("x"), track("y")], [], hist("x", "y"), {}, TODAY)
    assert result.warning
    assert result.notes["x"]["heard_syncs"] == [TODAY]
    assert result.notes["y"]["heard_syncs"] == [TODAY]


def test_no_new_plays_hears_nothing_and_updates_last_sync():
    result = sync({}, [track("x")], [], OLD, STATE, TODAY)
    assert result.notes["x"]["heard_syncs"] == []
    assert result.state["last_sync"] == TODAY
    assert result.warning is None


def test_two_plays_in_one_sync_add_one_heard_entry():
    notes, _ = run(inbox=[track("a")], history=hist("a", "a", "o1", "o2", "o3"))
    assert notes["a"]["heard_syncs"] == [TODAY]


def test_heard_in_two_syncs_is_keeper():
    result, day1 = _heard_in_two_syncs()
    assert result.notes["a"]["heard_syncs"] == [day1, TODAY]
    assert result.notes["a"]["status"] == KEEPER
    assert [(m.action, m.reason) for m in result.moves] == [("promote", "heard in 2 syncs")]


def test_heard_in_one_sync_stays_in_inbox():
    notes, moves = run(inbox=[track("a")], history=hist("a", "o1", "o2", "o3"))
    assert notes["a"]["heard_syncs"] == [TODAY]
    assert notes["a"]["status"] == INBOX
    assert moves == []


def test_three_syncs_and_30_days_never_heard_expires():
    notes, moves = _inbox_on_days((30, 15, 0))
    assert notes["a"]["inbox_syncs"] == 3
    assert notes["a"]["status"] == EXPIRED
    assert [(m.action, m.reason) for m in moves] == [("remove_inbox", "never heard")]


def test_three_syncs_and_29_days_stays_in_inbox():
    notes, moves = _inbox_on_days((29, 15, 0))
    assert notes["a"]["status"] == INBOX
    assert moves == []


def test_30_days_and_two_syncs_stays_in_inbox():
    notes, moves = _inbox_on_days((30, 0))
    assert notes["a"]["inbox_syncs"] == 2
    assert notes["a"]["status"] == INBOX
    assert moves == []


def test_thumbs_up_beats_heard():
    result, _ = _heard_in_two_syncs(like="LIKE")
    assert result.notes["a"]["status"] == KEEPER
    assert [(m.action, m.reason) for m in result.moves] == [("promote", "thumbs up")]


def test_thumbs_down_beats_heard():
    result, _ = _heard_in_two_syncs(like="DISLIKE")
    assert result.notes["a"]["status"] == REJECTED
    assert [(m.action, m.reason) for m in result.moves] == [("remove_inbox", "thumbs down")]


def test_thumbs_up_beats_expiry():
    notes, moves = _inbox_on_days((30, 15, 0), like="LIKE")
    assert notes["a"]["status"] == KEEPER
    assert [(m.action, m.reason) for m in moves] == [("promote", "thumbs up")]


def test_thumbs_down_beats_expiry():
    notes, moves = _inbox_on_days((30, 15, 0), like="DISLIKE")
    assert notes["a"]["status"] == REJECTED
    assert [(m.action, m.reason) for m in moves] == [("remove_inbox", "thumbs down")]


def test_old_format_note_loads_gets_defaults_and_drops_heard_days(tmp_path):
    old = {
        "videoId": "a",
        "title": "Song",
        "artists": ["Artist"],
        "status": "inbox",
        "source": "inbox",
        "playlist": "inbox",
        "added": TODAY - timedelta(days=5),
        "first_heard": TODAY - timedelta(days=5),
        "last_heard": TODAY - timedelta(days=5),
        "heard_days": [TODAY - timedelta(days=5)],
        "like": "INDIFFERENT",
    }
    save_songs(tmp_path, {}, {"a": old})
    _, meta, _ = load_songs(tmp_path)["a"]
    assert "heard_days" in meta and "heard_syncs" not in meta

    result = sync({"a": meta}, [], [], OLD, STATE, TODAY)
    note = result.notes["a"]
    assert note["heard_syncs"] == []
    assert note["inbox_syncs"] == 0
    assert "heard_days" not in note

    save_songs(tmp_path, load_songs(tmp_path), result.notes)
    _, saved, _ = load_songs(tmp_path)["a"]
    assert "heard_days" not in saved
    assert saved["heard_syncs"] == [] and saved["inbox_syncs"] == 0


def _heard_once_then_quiet(quiet_days_after):
    """Song "a" heard in the first sync (60 days ago), then one quiet sync per entry."""
    heard_day = TODAY - timedelta(days=60)
    result = sync({}, [track("a")], [], hist("a", "o1", "o2", "o3"), STATE, heard_day)
    for days in quiet_days_after:
        result = sync(result.notes, [track("a")], [], hist("a", "o1", "o2", "o3"), result.state,
                      heard_day + timedelta(days=days))
    return result


def test_heard_once_then_3_quiet_syncs_and_30_days_expires():
    result = _heard_once_then_quiet([10, 20, 30])
    assert result.notes["a"]["status"] == EXPIRED
    assert [(m.action, m.reason) for m in result.moves] == [("remove_inbox", "heard once, not again")]


def test_heard_once_then_3_quiet_syncs_but_29_days_stays():
    assert _heard_once_then_quiet([10, 20, 29]).notes["a"]["status"] == INBOX


def test_heard_once_then_2_quiet_syncs_and_30_days_stays():
    assert _heard_once_then_quiet([15, 30]).notes["a"]["status"] == INBOX
