import asyncio
from datetime import date

import pytest
from fakes import FakeYT

from ytm_hygiene import settings
from ytm_hygiene.sync import new_note
from ytm_hygiene.vault import load_songs, save_songs

pytest.importorskip("nicegui")
from nicegui import ui  # noqa: E402
from nicegui.testing.user_simulation import user_simulation  # noqa: E402

from ytm_hygiene.app import suggest as suggest_screen  # noqa: E402
from ytm_hygiene.app.shell import root  # noqa: E402

INBOX = "PLinbox"
TODAY = date(2026, 10, 19)
SETUP_LINE = "Set up sign-in, your Obsidian vault and your Inbox on the Setup screen first."


def song(vid, title, artist):
    return {
        "videoId": vid,
        "title": title,
        "artists": [{"name": artist, "id": f"id-{artist}"}],
        "album": {"name": "Album"},
        "videoType": "MUSIC_VIDEO_TYPE_ATV",
        "isAvailable": True,
        "resultType": "song",
    }


def results(*pairs):
    """Search results keyed by the query find_song builds: '<artist> <title>'."""
    return {f"{artist} {title}": [song(vid, title, artist)] for vid, artist, title in pairs}


def note(vid, artist, title, status):
    return new_note(song(vid, title, artist), "sync", status, TODAY)


def click(user, label):
    user.find(kind=ui.button, content=label).click()


def el(user, marker):
    return next(iter(user.find(marker=marker).elements))


def label_texts(user):
    return [e.text for e in user.client.elements.values() if isinstance(e, ui.label)]


async def until(condition):
    for _ in range(100):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


FOUND = results(("v1", "Adele", "Hello"), ("v3", "Abba", "Waterloo"), ("v2", "Queen", "Radio Ga Ga"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("time.sleep", lambda s: None)  # search and write pacing
    (tmp_path / settings.AUTH_NAME).write_text("{}")
    vault = tmp_path / "vault"
    settings.save(tmp_path / settings.CONFIG_NAME, {"vault": str(vault), "inbox": INBOX})
    save_songs(vault, {}, {"k": note("k", "Queen", "Radio Ga Ga", "keeper")})
    fake = FakeYT(search_results=FOUND)
    monkeypatch.setattr(suggest_screen, "make_client", lambda a: fake)
    monkeypatch.setattr(ui.clipboard, "write", lambda text: None)
    return fake, vault


def test_missing_setup_shows_one_line(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            await user.should_see(SETUP_LINE)
            assert not [e for e in user.client.elements.values() if isinstance(e, ui.button) and e.text == "Find songs"]

    asyncio.run(run())


def test_copy_puts_seed_on_clipboard_and_in_box(env, monkeypatch):
    fake, vault = env
    copied = []
    monkeypatch.setattr(ui.clipboard, "write", copied.append)

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            click(user, "Copy my taste summary")
            await until(lambda: copied)
            await until(lambda: "Queen - Radio Ga Ga" in el(user, "summary").value)

    asyncio.run(run())
    assert "Songs I keep:\nQueen - Radio Ga Ga" in copied[0]
    assert fake.calls == []  # no network


def test_find_shows_found_skipped_and_not_found(env):
    fake, _ = env

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            user.find(marker="reply").type("Adele - Hello\nQueen - Radio Ga Ga\nNobody - Nothing")
            click(user, "Find songs")
            await user.should_see("Found 1 new song", retries=50)
            await user.should_see("Already in your notes: 1")
            await user.should_see("Not found: 1")
            await user.should_see("Add 1 to Inbox")

    asyncio.run(run())
    assert fake.writes() == []


def test_unticking_leaves_song_out_of_the_add(env):
    fake, vault = env

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            user.find(marker="reply").type("Adele - Hello\nAbba - Waterloo")
            click(user, "Find songs")
            await user.should_see("Add 2 to Inbox", retries=50)
            el(user, "tick-v1").set_value(False)
            await user.should_see("Add 1 to Inbox")
            click(user, "Add 1 to Inbox")
            await user.should_see("Add 1 song to your Inbox?")
            click(user, "Yes, add them")
            await until(lambda: "v3" in load_songs(vault))
            await user.should_see("Added 1 song to your Inbox.")

    asyncio.run(run())
    assert fake.writes() == [("add", INBOX, "v3")]
    assert "v1" not in load_songs(vault)


def test_confirm_adds_and_writes_notes_with_source_claude(env):
    fake, vault = env

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            user.find(marker="reply").type("Adele - Hello\nAbba - Waterloo")
            click(user, "Find songs")
            await user.should_see("Add 2 to Inbox", retries=50)
            click(user, "Add 2 to Inbox")
            await user.should_see("Add 2 songs to your Inbox?")
            await user.should_see("You can undo this from History.")
            assert fake.writes() == []  # nothing before confirming
            click(user, "Yes, add them")
            await until(lambda: {"v1", "v3"} <= set(load_songs(vault)))
            await user.should_see("Added 2 songs to your Inbox.")

    asyncio.run(run())
    assert fake.writes() == [("add", INBOX, "v1"), ("add", INBOX, "v3")]
    meta = load_songs(vault)["v1"][1]
    assert meta["source"] == "claude" and meta["status"] == "inbox" and meta["playlist"] == "inbox"


def test_apply_error_shows_plain_message_and_keeps_notes_for_added(env):
    fake, vault = env
    fake.fail_on = 2  # the second add fails

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            user.find(marker="reply").type("Adele - Hello\nAbba - Waterloo")
            click(user, "Find songs")
            await user.should_see("Add 2 to Inbox", retries=50)
            click(user, "Add 2 to Inbox")
            click(user, "Yes, add them")
            await user.should_see("Stopped:", retries=50)
            await user.should_see("History can undo them")

    asyncio.run(run())
    assert set(load_songs(vault)) == {"k", "v1"}
