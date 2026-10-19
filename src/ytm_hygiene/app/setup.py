"""First-run setup: sign in, pick the Obsidian vault, pick the Inbox and Rotation."""

from functools import partial
from pathlib import Path

from nicegui import app, run, ui

from .. import auth
from ..client import make_client
from .state import AppState

HOW_TO_COPY = [
    "1. Open music.youtube.com in Chrome, Edge or Firefox and sign in.",
    "2. Press F12 and open the Network tab. If the list is empty, press F5 to reload the page.",
    '3. Type "browse" in the filter box, then click the first request named browse.',
    "4. Chrome or Edge: right-click it, then Copy > Copy request headers.",
    "    Firefox: right-click it, then Copy Value > Copy Request Headers.",
    "5. Paste below and press Sign in.",
]


def build(state: AppState) -> None:
    session = {"yt": None, "playlists": []}

    def client():
        if session["yt"] is None:
            session["yt"] = make_client(str(state.auth_path))
        return session["yt"]

    with ui.stepper().props("vertical").classes("w-full") as stepper:
        with ui.step("Sign in to YouTube Music"):
            if state.signed_in:
                ui.label("You're signed in. Sign in again only if the app says your sign-in stopped working.")
            with ui.expansion("How to copy the headers", value=not state.signed_in).classes("w-full"):
                for text in HOW_TO_COPY:
                    ui.label(text)
            paste = ui.textarea(placeholder="Paste the request headers here").props("outlined").classes("w-full")
            ui.label("These headers let this app act as you on YouTube Music. They stay on this computer.").classes(
                "text-caption text-grey"
            )
            error = ui.label().classes("text-negative")

            async def sign_in():
                error.text = ""
                sign_in_button.disable()  # one request per click
                try:
                    session["yt"], session["playlists"] = await run.io_bound(
                        auth.sign_in, paste.value or "", state.auth_path
                    )
                except auth.SignInError as e:
                    error.text = str(e)
                    return
                finally:
                    sign_in_button.enable()
                paste.value = ""
                ui.notify("Signed in.", type="positive")
                stepper.next()

            with ui.stepper_navigation():
                sign_in_button = ui.button("Sign in", on_click=sign_in)
                if state.signed_in:
                    ui.button("Keep my sign-in", on_click=stepper.next).props("flat")

        with ui.step("Choose your Obsidian vault"):
            ui.label("Only needed for the Inbox and suggestions. Skip it if you don't use Obsidian.")
            vault = ui.input("Vault folder", value=state.settings.get("vault") or "").classes("w-full")
            vault_error = ui.label().classes("text-negative")

            async def browse():
                import webview

                picked = await app.native.main_window.create_file_dialog(webview.FileDialog.FOLDER)
                if picked:
                    vault.value = picked[0]

            async def vault_next():
                if vault.value and not Path(vault.value).is_dir():
                    vault_error.text = "That folder doesn't exist."
                    return
                vault_error.text = ""
                state.settings["vault"] = vault.value or None
                await load_playlists()
                stepper.next()

            with ui.stepper_navigation():
                ui.button("Next", on_click=vault_next)
                if app.native.main_window:
                    ui.button("Browse…", on_click=browse).props("flat")
                ui.button("Back", on_click=stepper.previous).props("flat")

        with ui.step("Choose your Inbox and Rotation playlists"):
            ui.label("Inbox holds new songs on trial. Rotation holds the keepers you download to your phone.")
            ui.label("Only needed for the Inbox screen.").classes("text-caption text-grey")
            picks = {}

            async def create(key, name, about):
                playlist_id = await run.io_bound(client().create_playlist, name, about, "PRIVATE")
                if not isinstance(playlist_id, str):
                    ui.notify(f"Couldn't create {name}.", type="negative")
                    return
                session["playlists"].append({"playlistId": playlist_id, "title": name})
                show_playlists()
                picks[key].value = playlist_id

            for key, name, about in (
                ("inbox", "Inbox", "New songs on trial"),
                ("rotation", "Rotation", "Keepers to download"),
            ):
                with ui.row().classes("items-center w-full"):
                    picks[key] = ui.select({}, label=name, value=None, clearable=True).classes("min-w-[320px]")
                    ui.button(f"Create {name} for me", on_click=partial(create, key, name, about)).props("flat")
            pick_error = ui.label().classes("text-negative")

            def show_playlists():
                options = {p["playlistId"]: p.get("title") or p["playlistId"] for p in session["playlists"]}
                for key, select in picks.items():
                    current = select.value or state.settings.get(key)
                    select.set_options(options, value=current if current in options else None)

            async def load_playlists():
                if not session["playlists"] and state.signed_in:
                    session["playlists"] = await run.io_bound(lambda: client().get_library_playlists(limit=None))
                show_playlists()

            def finish():
                inbox, rotation = picks["inbox"].value, picks["rotation"].value
                if inbox and inbox == rotation:
                    pick_error.text = "Inbox and Rotation must be different playlists."
                    return
                state.settings.update(inbox=inbox, rotation=rotation)
                state.save()
                ui.notify("All set.", type="positive")
                ui.navigate.reload()

            with ui.stepper_navigation():
                ui.button("Finish", on_click=finish)
                ui.button("Back", on_click=stepper.previous).props("flat")
