import asyncio
from datetime import date

import pytest
from fakes import FakeYT, NoThrottle

from ytm_hygiene import apply, settings, vault
from ytm_hygiene.sync import new_note

pytest.importorskip("nicegui")
from nicegui import ui  # noqa: E402
from nicegui.testing.user_simulation import user_simulation  # noqa: E402

from ytm_hygiene.app import inbox  # noqa: E402
from ytm_hygiene.app.shell import root  # noqa: E402


def click(user, label):
    user.find(kind=ui.button, content=label).click()


async def until(condition):
    for _ in range(100):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


def labels(user):
    return " | ".join(e.text for e in user.find(kind=ui.label).elements)


def track(video_id, like="INDIFFERENT", title=None):
    return {
        "videoId": video_id, "setVideoId": f"set{video_id}", "title": title or f"Song {video_id}",
        "artists": [{"name": "Band"}], "likeStatus": like,
    }  # fmt: skip


class Listening(FakeYT):
    def get_history(self):
        self.calls.append(("get_history",))
        return [{"videoId": "v2"}]


def configure(tmp_path, inbox_id="PLin", rotation_id="PLrot", complete=True):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    cfg = {"vault": str(vault_dir), "inbox": inbox_id, "rotation": rotation_id} if complete else {}
    settings.save(tmp_path / settings.CONFIG_NAME, cfg)
    (tmp_path / settings.AUTH_NAME).write_text("{}")
    return vault_dir


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    vault_dir = configure(tmp_path)
    # v2 was heard once at an earlier check, so hearing it now makes two.
    old = new_note(track("v2"), "inbox", "inbox", date(2020, 1, 1))
    old["heard_syncs"] = [date(2020, 1, 2)]
    vault.save_songs(vault_dir, {}, {"v2": old})
    fake = Listening(
        playlists={
            "PLin": [track("v1", "LIKE"), track("v2"), track("v3", "DISLIKE"), track("v4")],
            "PLrot": [track("r1", "DISLIKE")],
        }
    )
    monkeypatch.setattr(inbox, "make_client", lambda a: fake)
    monkeypatch.setattr(inbox, "Throttle", NoThrottle)
    applied = []

    def fake_apply(yt, moves, inbox_id, rotation_id, inbox_tracks, rotation_tracks, **kw):
        applied.append((list(moves), inbox_id, rotation_id, inbox_tracks, rotation_tracks, kw))
        todo = moves[: kw["max_ops"]]
        return {"done": len(todo), "skipped": 0, "log": None}

    monkeypatch.setattr(inbox, "apply_moves", fake_apply)
    return fake, applied, vault_dir


async def check(user):
    await user.open("/")
    click(user, "Check what I've listened to")
    await until(lambda: "Checked." in labels(user))


def test_setup_missing_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure(tmp_path, complete=False)

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            await user.should_see("Finish the Setup screen first", retries=50)

    asyncio.run(run())


def test_check_writes_notes_and_state_and_shows_groups(env):
    fake, applied, vault_dir = env

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            assert fake.calls == []  # no network on start
            click(user, "Check what I've listened to")
            await until(lambda: "Checked." in labels(user))
            await user.should_see("Move to Rotation (2)")
            await user.should_see("Remove from Inbox (1)")
            await user.should_see("Remove from Rotation (1)")
            await user.should_see("Still on trial (1)")
            await user.should_see("heard in 2 checks")  # "syncs" becomes "checks"
            await user.should_see("thumbs up")
            await user.should_see("Apply 4 changes")
            assert "syncs" not in labels(user).replace("keep/expire", "")
            assert [c[0] for c in fake.calls] == ["get_playlist", "get_playlist", "get_history"]

    asyncio.run(run())
    assert applied == []
    assert (vault_dir / vault.STATE).exists()
    assert set(vault.load_songs(vault_dir)) == {"v1", "v2", "v3", "v4", "r1"}
    assert vault.load_state(vault_dir)["anchor"] == ["v2"]


def test_unticked_move_is_left_out_and_confirm_passes_ids_and_tracks(env):
    fake, applied, _ = env

    async def run():
        async with user_simulation(root) as user:
            await check(user)
            boxes = [e for e in user.client.elements.values() if isinstance(e, ui.checkbox)]
            assert len(boxes) == 4 and all(b.value for b in boxes)
            boxes[0].set_value(False)
            await user.should_see("Apply 3 changes")
            click(user, "Apply 3 changes")
            await user.should_see("You can undo this from History.")
            assert applied == []  # nothing before confirming
            click(user, "Yes, apply them")
            await until(lambda: applied)
            await until(lambda: "Done: 3 changes." in labels(user))

    asyncio.run(run())
    moves, inbox_id, rotation_id, inbox_tracks, rotation_tracks, kw = applied[0]
    assert len(moves) == 3
    assert (inbox_id, rotation_id) == ("PLin", "PLrot")
    assert [t["videoId"] for t in inbox_tracks] == ["v1", "v2", "v3", "v4"]
    assert [t["videoId"] for t in rotation_tracks] == ["r1"]
    assert kw["max_ops"] == 20 and kw["log_dir"].name == kw["log_dir"].resolve().name
    left_out = {"v1", "v2", "v3", "r1"} - {m.video_id for m in moves}
    assert len(left_out) == 1


def test_same_playlist_is_refused(tmp_path, env):
    fake, applied, _ = env
    configure_same = {"vault": str(tmp_path / "vault"), "inbox": "PLin", "rotation": "PLin"}
    settings.save(tmp_path / settings.CONFIG_NAME, configure_same)

    async def run():
        async with user_simulation(root) as user:
            await check(user)
            click(user, "Apply 1 change")  # the same list is fetched twice; only v3 is left to remove
            await user.should_see("same playlist", retries=50)

    asyncio.run(run())
    assert applied == []


def test_apply_error_is_plain_and_mentions_history(env, monkeypatch):
    fake, applied, _ = env

    def failing(yt, moves, inbox_id, rotation_id, inbox_tracks, rotation_tracks, **kw):
        e = apply.ApplyError("add v1: boom")
        e.log = kw["log_dir"] / "undo-20260101-000000.json"
        raise e

    monkeypatch.setattr(inbox, "apply_moves", failing)

    async def run():
        async with user_simulation(root) as user:
            await check(user)
            click(user, "Apply 4 changes")
            click(user, "Yes, apply them")
            await user.should_see("Stopped: add v1: boom.", retries=50)
            await user.should_see("History can undo them")

    asyncio.run(run())
