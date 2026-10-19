import asyncio
import json

import pytest

from ytm_hygiene import apply, settings

pytest.importorskip("nicegui")
from nicegui import ui  # noqa: E402
from nicegui.testing.user_simulation import user_simulation  # noqa: E402

from ytm_hygiene.app import history  # noqa: E402
from ytm_hygiene.app.shell import root  # noqa: E402


class NoThrottle:
    def wait(self):
        pass


class FakeYT:
    """Records writes. Responses are shaped like the real client's."""

    def __init__(self):
        self.calls = []

    def add_playlist_items(self, pid, ids, duplicates=False):
        self.calls.append(("add", pid, ids[0]))
        return {"status": "STATUS_SUCCEEDED", "playlistEditResults": [{"setVideoId": "newX"}]}

    def edit_playlist(self, pid, moveItem=None):
        self.calls.append(("move", pid, *moveItem))
        return "STATUS_SUCCEEDED"

    def remove_playlist_items(self, pid, videos):
        self.calls.append(("remove", pid, videos[0]["videoId"], videos[0]["setVideoId"]))
        return "STATUS_SUCCEEDED"


def click(user, label):
    user.find(kind=ui.button, content=label).click()


def texts(user):
    return [e.text for e in user.find(kind=ui.label).elements]


def button_texts(user):
    return [e.text for e in user.find(kind=ui.button).elements]


async def until(condition):
    for _ in range(100):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


def add_step(vid, pid="PLa"):
    return {"op": "add", "playlist_id": pid, "videoId": vid, "setVideoId": f"set-{vid}"}


def remove_step(vid, pid="PLa"):
    return {"op": "remove", "playlist_id": pid, "videoId": vid, "setVideoId": f"old-{vid}"}


def write_log(base, name, steps, ids=("PLa",)):
    (base / name).write_text(json.dumps({"playlist_ids": list(ids), "steps": steps}), encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / settings.AUTH_NAME).write_text("{}")
    fake = FakeYT()
    monkeypatch.setattr(history, "make_client", lambda a: fake)
    undo_calls = []

    def fake_undo(yt, log_path, allow_playlists, progress=print, **kw):
        undo_calls.append((log_path, list(allow_playlists)))
        return {"undone": 0}

    monkeypatch.setattr(history, "undo", fake_undo)
    return fake, undo_calls


@pytest.fixture
def logs(tmp_path):
    """Three runs: two to undo (one with a move step, two playlists), one already undone."""
    write_log(tmp_path, "undo-20260101-090000.json",
              [add_step("a"), add_step("b"), add_step("c"), {"op": "move", "playlist_id": "PLa"},
               remove_step("a"), remove_step("b"), remove_step("c")])  # fmt: skip
    write_log(tmp_path, "undo-20251231-235959.json", [add_step("x")], ids=("PLb", "PLa"))
    write_log(tmp_path, "undone-20260105-120000.json", [remove_step("y")])
    return tmp_path


def test_plain_summary_and_date():
    assert history.when_text("20260101-090000") == "1 Jan 2026, 09:00"
    assert history.summary([add_step("a")] * 3 + [remove_step("a")] * 3 + [{"op": "move"}]) == (
        "3 songs added, 3 removed"
    )
    assert history.summary([remove_step("a")]) == "0 songs added, 1 removed"
    assert history.summary([{"op": "move"}]) == "No songs added or removed"


def test_not_signed_in_shows_one_line_and_no_network(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def no_client(*a):
        raise AssertionError("made a client without being asked")

    monkeypatch.setattr(history, "make_client", no_client)

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            await user.should_see("Sign in first on the Setup screen.")
            assert "Refresh" not in button_texts(user)

    asyncio.run(run())


def test_entries_sorted_newest_first(logs):
    entries = history.read_entries(logs)
    assert [e["when"] for e in entries] == ["5 Jan 2026, 12:00", "1 Jan 2026, 09:00", "31 Dec 2025, 23:59"]
    assert [e["undone"] for e in entries] == [True, False, False]
    assert entries[1]["summary"] == "3 songs added, 3 removed"
    assert entries[2]["playlist_ids"] == ["PLb", "PLa"]


def test_lists_plain_summary_and_undone_status(env, logs):
    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            await user.should_see("3 songs added, 3 removed")
            await user.should_see("Already undone")
            await user.should_see("1 song added, 0 removed")
            await user.should_see("5 Jan 2026, 12:00")

    asyncio.run(run())


def test_undone_entries_have_no_undo_button(env, logs):
    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            await user.should_see("Already undone")
            assert button_texts(user).count("Undo") == 2
            assert "Refresh" in button_texts(user)

    asyncio.run(run())


def test_undo_calls_undo_with_log_playlists_and_renames(env, logs):
    _, undo_calls = env

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            await user.should_see("3 songs added, 3 removed")
            click(user, "Undo")  # newest first, so this is the 1 Jan run
            await user.should_see("Put back the playlists as they were before this run?")
            click(user, "Yes, undo it")
            await until(lambda: (logs / "undone-20260101-090000.json").exists())
            await user.should_see("Already undone", retries=50)
            assert button_texts(user).count("Undo") == 1

    asyncio.run(run())
    assert undo_calls == [(logs / "undo-20260101-090000.json", ["PLa"])]
    assert not (logs / "undo-20260101-090000.json").exists()


def test_undo_error_keeps_the_file_and_shows_message(env, logs, monkeypatch):
    def failing(yt, log_path, allow_playlists, progress=print, **kw):
        raise apply.ApplyError("add a: boom")

    monkeypatch.setattr(history, "undo", failing)

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            await user.should_see("3 songs added, 3 removed")
            click(user, "Undo")
            click(user, "Yes, undo it")
            await user.should_see("Couldn't undo this run: add a: boom.", retries=50)
            assert button_texts(user).count("Undo") == 2  # both still available

    asyncio.run(run())
    assert (logs / "undo-20260101-090000.json").exists()
    assert not (logs / "undone-20260101-090000.json").exists()


def test_real_undo_writes_and_renames(env, logs, monkeypatch):
    fake, _ = env
    write_log(logs, "undo-20260301-080000.json", [
        {"op": "add", "playlist_id": "PLa", "videoId": "new1", "setVideoId": "s1"},
        {"op": "remove", "playlist_id": "PLa", "videoId": "old1", "setVideoId": "t1", "new_setVideoId": "s1"},
    ])  # fmt: skip
    monkeypatch.setattr(history, "undo", lambda *a, **kw: apply.undo(*a, throttle=NoThrottle(), **kw))

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            await user.should_see("1 song added, 1 removed")
            click(user, "Undo")
            click(user, "Yes, undo it")
            await until(lambda: (logs / "undone-20260301-080000.json").exists())

    asyncio.run(run())
    assert fake.calls == [("add", "PLa", "old1"), ("move", "PLa", "newX", "s1"), ("remove", "PLa", "new1", "s1")]
