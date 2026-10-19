import asyncio
from pathlib import Path

import pytest
from fakes import FakeYT, NoThrottle

from ytm_hygiene import apply, settings

pytest.importorskip("nicegui")
from nicegui import ui  # noqa: E402
from nicegui.testing.user_simulation import user_simulation  # noqa: E402

from ytm_hygiene.app import cleanup  # noqa: E402
from ytm_hygiene.app.shell import root  # noqa: E402


def click(user, label):
    user.find(kind=ui.button, content=label).click()


async def until(condition):
    for _ in range(100):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


def make_row(position, action, flags="", set_id=True):
    return {
        "position": position, "title": f"Video {position}", "artist": "Band",
        "old_videoId": f"old{position}", "old_url": f"https://x/old{position}",
        "candidate_title": f"Song {position}", "candidate_artist": "Band",
        "candidate_videoId": f"new{position}", "candidate_url": f"https://x/new{position}",
        "flags": flags, "action": action, "playlist_id": "PLa",
        "old_setVideoId": f"set{position}" if set_id else "", "verdict": "",
    }  # fmt: skip


class Library(FakeYT):
    def get_library_playlists(self, limit=None):
        self.calls.append(("get_library_playlists",))
        return [{"playlistId": "PLa", "title": "Road trip"}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / settings.AUTH_NAME).write_text("{}")
    fake = Library(playlists={"PLa": [{"videoId": "v", "setVideoId": "s"}]})
    monkeypatch.setattr(cleanup, "make_client", lambda a: fake)
    applied = []

    def fake_apply(yt, rows, allow_playlist, **kw):
        applied.append((rows, allow_playlist, kw))
        return {"selected": len(rows), "swapped": min(len(rows), 20), "stale": 0, "log": None,
                "positions": [r["position"] for r in rows[:20]]}  # fmt: skip

    monkeypatch.setattr(cleanup, "apply_rows", fake_apply)
    return fake, applied


def use_rows(monkeypatch, rows):
    def fake_scan(yt, playlist, playlist_id, progress=print, **kw):
        progress(f"[1/{len(rows)}] searching: q")
        return rows

    monkeypatch.setattr(cleanup, "scan_playlist", fake_scan)


async def scan(user):
    await user.open("/")
    click(user, "Choose a playlist")
    def picker():  # hidden until loaded, so find it in the client's element list
        return next(e for e in user.client.elements.values() if isinstance(e, ui.select) and e.props.get("label") == "Playlist")

    await until(lambda: picker().options)
    picker().set_value("PLa")
    click(user, "Check this playlist")


def test_plain_reasons():
    assert cleanup.plain_reasons(["duration", "artist"]) == ["different length", "different artist"]
    assert cleanup.plain_reasons("version:live;version:remixer") == ["one is a live version", "different remix"]
    assert cleanup.plain_reasons(["clean_version", "explicit", "official_source", "no_duration"]) == [
        "clean version of an explicit song", "explicit", "may be a live set or a compilation", "length unknown",
    ]  # fmt: skip
    assert cleanup.plain_reasons(["no_setVideoId"]) == ["can't be swapped in this playlist"]
    assert cleanup.plain_reasons(["version:acoustic"]) == ["different version: acoustic"]
    assert cleanup.plain_reasons(["some_new_flag"]) == ["some new flag"]
    assert cleanup.plain_reasons([]) == []


def test_no_network_on_start_then_groups_and_default_ticks(env, monkeypatch):
    fake, applied = env
    rows = [make_row(1, "SWAP"), make_row(2, "REVIEW", "duration"), make_row(3, "NO_MATCH", "no_setVideoId"),
            make_row(4, "KEEP")]  # fmt: skip
    use_rows(monkeypatch, rows)

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            assert fake.calls == []
            await scan(user)
            await user.should_see("Checked 4 tracks.", retries=50)
            await user.should_see("Ready to swap (1)")
            await user.should_see("Please check these (1)")
            await user.should_see("No song version found (1)")
            await user.should_see("1 track is already a song.")
            await user.should_see("different length")
            await user.should_see("Swap 1 song")
            assert [c[0] for c in fake.calls] == ["get_library_playlists", "get_playlist"]

    asyncio.run(run())
    assert applied == []
    assert list(Path("backups").glob("PLa-*.json"))


def test_looks_right_and_wrong_change_what_is_swapped(env, monkeypatch):
    fake, applied = env
    use_rows(monkeypatch, [make_row(1, "SWAP"), make_row(2, "REVIEW", "artist"), make_row(3, "REVIEW", "artist")])

    async def run():
        async with user_simulation(root) as user:
            await scan(user)
            await user.should_see("Swap 1 song", retries=50)
            user.find(kind=ui.toggle).elements.pop().set_value("right")  # first review row
            await user.should_see("Swap 2 songs")
            toggles = list(user.find(kind=ui.toggle).elements)
            assert len(toggles) == 2
            # Changing the same choice to Wrong unticks it again.
            for t in toggles:
                if t.value == "right":
                    t.set_value("wrong")
            await user.should_see("Swap 1 song")

    asyncio.run(run())


def test_confirm_then_apply_only_ticked_rows(env, monkeypatch):
    fake, applied = env
    use_rows(monkeypatch, [make_row(1, "SWAP"), make_row(2, "SWAP"), make_row(3, "REVIEW", "artist")])

    async def run():
        async with user_simulation(root) as user:
            await scan(user)
            await user.should_see("Swap 2 songs", retries=50)
            click(user, "Swap 2 songs")
            await user.should_see("You can undo this from History.")
            await user.should_see('Swap 2 songs in "Road trip"?')
            assert applied == []  # nothing before confirming
            click(user, "Yes, swap them")
            await until(lambda: applied)
            await until(lambda: "Swapped 2 songs." in " ".join(e.text for e in user.find(kind=ui.label).elements))
            await user.should_see("Please check these (1)")

    asyncio.run(run())
    rows, playlist_id, kw = applied[0]
    assert [r["position"] for r in rows] == [1, 2]
    assert all(r["verdict"] == "correct" for r in rows)
    assert playlist_id == "PLa" and kw["max_ops"] == 20


def test_twenty_at_a_time_with_the_real_apply(env, monkeypatch):
    fake, _ = env
    tracks = [{"videoId": f"old{i}", "setVideoId": f"set{i}", "title": "t"} for i in range(1, 26)]
    fake.playlists["PLa"] = tracks
    monkeypatch.setattr(cleanup, "apply_rows", lambda *a, **kw: apply.apply_rows(*a, throttle=NoThrottle(), **kw))
    use_rows(monkeypatch, [make_row(i, "SWAP") for i in range(1, 26)])

    def swaps():
        return len([c for c in fake.writes() if c[0] == "remove"])

    async def run():
        async with user_simulation(root) as user:
            await scan(user)
            await user.should_see("Swap 25 songs", retries=50)
            click(user, "Swap 25 songs")
            await user.should_see("20 at a time")
            click(user, "Yes, swap them")
            await until(lambda: swaps() == 20)
            await user.should_see("Swap 5 songs", retries=50)
            click(user, "Swap 5 songs")
            click(user, "Yes, swap them")
            await until(lambda: swaps() == 25)

    asyncio.run(run())


def test_error_shows_plain_message_and_undo_note(env, monkeypatch):
    fake, _ = env
    use_rows(monkeypatch, [make_row(1, "SWAP")])

    def failing(yt, rows, allow_playlist, log_dir, **kw):
        (log_dir / "undo-20260101-000000.json").write_text("{}")
        raise apply.ApplyError("add new1: boom")

    monkeypatch.setattr(cleanup, "apply_rows", failing)

    async def run():
        async with user_simulation(root) as user:
            await scan(user)
            await user.should_see("Swap 1 song", retries=50)
            click(user, "Swap 1 song")
            click(user, "Yes, swap them")
            await user.should_see("History can undo them", retries=50)
            await user.should_see("Stopped: add new1: boom.")

    asyncio.run(run())
