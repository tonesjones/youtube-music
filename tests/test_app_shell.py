import asyncio

import pytest

from ytm_hygiene import settings

pytest.importorskip("nicegui")
from nicegui.testing.user_simulation import user_simulation  # noqa: E402

from ytm_hygiene.app.shell import root  # noqa: E402


def test_settings_round_trip(tmp_path):
    path = tmp_path / settings.CONFIG_NAME
    assert settings.load(path) == {}
    values = {"vault": r"C:\Users\me\Vault", "inbox": "PLa", "rotation": "PLb", "expire_days": 30, "x": 1}
    settings.save(path, values)
    assert settings.load(path) == {k: values[k] for k in settings.KEYS}


def test_app_dir_prefers_current_folder_with_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    assert settings.app_dir() == tmp_path / "appdata" / "ytm-hygiene"
    (tmp_path / settings.AUTH_NAME).write_text("{}")
    assert settings.app_dir() == tmp_path


def _open(*texts):
    async def run():
        async with user_simulation(root) as user:
            await user.open("/")
            for text in texts:
                await user.should_see(text)
    asyncio.run(run())


def test_new_user_lands_on_setup_with_nothing_done(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _open("Clean up a playlist", "Inbox", "Get suggestions", "History", "How to copy the headers")


def test_ready_user_sees_all_screens(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / settings.AUTH_NAME).write_text("{}")
    settings.save(tmp_path / settings.CONFIG_NAME, {"vault": "v", "inbox": "a", "rotation": "b"})
    _open("Coming soon.")
