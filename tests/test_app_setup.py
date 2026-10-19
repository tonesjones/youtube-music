import asyncio
import json

import pytest

from ytm_hygiene import auth, settings

pytest.importorskip("nicegui")
from nicegui import ui  # noqa: E402
from nicegui.testing.user_simulation import user_simulation  # noqa: E402

from ytm_hygiene.app import setup as setup_screen  # noqa: E402
from ytm_hygiene.app.shell import root  # noqa: E402

# Fake values in the shape Firefox copies: request line, CRLF endings, compression headers.
FIREFOX_PASTE = "\r\n".join([
    "POST /youtubei/v1/browse?prettyPrint=false HTTP/2",
    "Host: music.youtube.com",
    "Accept-Encoding: gzip, deflate, br, zstd",
    "Content-Encoding: gzip",
    "X-Goog-AuthUser: 0",
    "Authorization: SAPISIDHASH 123_fake",
    "Cookie: SAPISID=fake; __Secure-3PAPISID=fake",
])  # fmt: skip


def click(user, label):
    user.find(kind=ui.button, content=label).click()


async def until(condition):
    """Handlers run off the UI thread; hidden stepper steps still count as visible."""
    for _ in range(50):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


class FakeYT:
    def __init__(self, fail=False):
        self.fail = fail
        self.created = []

    def get_library_playlists(self, limit=None):
        if self.fail:
            raise Exception("401")
        return [{"playlistId": "PLa", "title": "Road trip"}, {"playlistId": "PLb", "title": "Gym"}]

    def create_playlist(self, title, description, privacy_status="PRIVATE"):
        self.created.append(title)
        return f"PLnew{title}"


def test_clean_headers_drops_firefox_extras():
    headers = auth.clean_headers(FIREFOX_PASTE)
    assert headers["cookie"] == "SAPISID=fake; __Secure-3PAPISID=fake"
    assert not {"content-encoding", "accept-encoding", "host"} & headers.keys()
    assert all(" " not in k and not v.endswith("\r") for k, v in headers.items())


def test_wrong_paste_gives_plain_error():
    with pytest.raises(auth.SignInError, match="right headers"):
        auth.clean_headers("just some text")


def test_sign_in_writes_file_only_when_the_read_works(tmp_path, monkeypatch):
    path = tmp_path / "browser.json"
    monkeypatch.setattr(auth, "make_client", lambda a: FakeYT(fail=True))
    with pytest.raises(auth.SignInError, match="didn't accept"):
        auth.sign_in(FIREFOX_PASTE, path)
    assert not path.exists()

    monkeypatch.setattr(auth, "make_client", lambda a: FakeYT())
    _, playlists = auth.sign_in(FIREFOX_PASTE, path)
    assert [p["playlistId"] for p in playlists] == ["PLa", "PLb"]
    assert "cookie" in json.loads(path.read_text())


def test_wizard_signs_in_creates_inbox_and_saves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = FakeYT()
    monkeypatch.setattr(auth, "make_client", lambda a: fake)
    monkeypatch.setattr(setup_screen, "make_client", lambda a: fake)

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            await user.should_see("How to copy the headers")
            user.find(ui.textarea).type(FIREFOX_PASTE)
            click(user, "Sign in")
            await until((tmp_path / settings.AUTH_NAME).exists)
            click(user, "Next")
            click(user, "Create Inbox for me")
            await until(lambda: fake.created)
            await asyncio.sleep(0.05)  # let the handler select the new playlist
            click(user, "Finish")

    asyncio.run(run())
    assert (tmp_path / settings.AUTH_NAME).exists()
    assert fake.created == ["Inbox"]
    assert settings.load(tmp_path / settings.CONFIG_NAME) == {"inbox": "PLnewInbox"}


def test_wizard_shows_plain_error_for_a_bad_paste(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            user.find(ui.textarea).type("not headers")
            click(user, "Sign in")
            await user.should_see("These don't look like the right headers", retries=20)

    asyncio.run(run())
    assert not (tmp_path / settings.AUTH_NAME).exists()
