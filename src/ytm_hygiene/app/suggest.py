"""Get suggestions: copy a taste summary for a chat, paste Claude's reply, add the songs found to the Inbox."""

from datetime import date
from functools import partial
from pathlib import Path

from nicegui import run, ui

from ..apply import ApplyError
from ..client import make_client, normalize_playlist_id
from ..suggest import add_found, find_new, parse_lines, seed
from ..vault import load_songs, save_songs
from .state import AppState

MAX_OPS = 20  # same cap as the CLI default
MUSIC_URL = "https://music.youtube.com/watch?v={}"


def artist_title(cand: dict) -> str:
    artists = cand.get("artists") or []
    name = artists[0].get("name") if artists else None
    return f"{name or 'Unknown'} - {cand.get('title') or cand['videoId']}"


def build(state: AppState) -> None:
    if not (state.signed_in and state.settings.get("vault") and state.settings.get("inbox")):
        ui.label("Set up sign-in, your Obsidian vault and your Inbox on the Setup screen first.").classes("text-grey")
        return

    vault = Path(state.settings["vault"])
    inbox_id = normalize_playlist_id(state.settings["inbox"])
    s = {"yt": None, "found": [], "skipped": [], "not_found": [], "ticks": {}, "busy": False}

    def client():
        if s["yt"] is None:
            s["yt"] = make_client(str(state.auth_path))
        return s["yt"]

    def ticked() -> list[dict]:
        return [c for c in s["found"] if s["ticks"].get(c["videoId"])]

    def update_add_button() -> None:
        n = len(ticked())
        add_button.text = f"Add {n} to Inbox"
        add_button.set_visibility(bool(s["found"]))
        add_button.set_enabled(n > 0 and not s["busy"])

    def set_busy(busy: bool) -> None:
        s["busy"] = busy
        for b in (copy_button, find_button):
            b.set_enabled(not busy)
        update_add_button()

    def set_tick(video_id, event) -> None:
        s["ticks"][video_id] = bool(event.value)
        update_add_button()

    @ui.refreshable
    def results() -> None:
        found, skipped, not_found = s["found"], s["skipped"], s["not_found"]
        if not (found or skipped or not_found):
            return
        if found:
            n = len(found)
            ui.label(f"Found {n} new song{'' if n == 1 else 's'}. Untick any you don't want.").classes("text-h6")
            for cand in found:
                vid = cand["videoId"]
                with ui.row().classes("items-center"):
                    box = ui.checkbox(artist_title(cand), value=bool(s["ticks"].get(vid)))
                    box.mark(f"tick-{vid}")
                    box.on_value_change(partial(set_tick, vid))
                    ui.link("Open", MUSIC_URL.format(vid), new_tab=True)
        else:
            ui.label("No new songs found.")
        ui.label(f"Already in your notes: {len(skipped)}").classes("text-grey")
        if not_found:
            with ui.expansion(f"Not found: {len(not_found)}").classes("w-full"):
                for line in not_found:
                    ui.label(line)

    ui.label("Ask Claude for songs you might like. Copy your taste summary into a chat, then paste Claude's reply below.")
    copy_button = ui.button("Copy my taste summary")
    summary = ui.textarea(label="Your taste summary").props("readonly outlined").classes("w-full")
    summary.mark("summary")
    summary.set_visibility(False)
    ui.label("Paste Claude's reply here, one 'Artist - Title' per line").classes("text-caption text-grey")
    reply = ui.textarea(placeholder="Artist - Title").props("outlined").classes("w-full")
    reply.mark("reply")
    find_button = ui.button("Find songs")
    error = ui.label().classes("text-negative")
    status = ui.label()
    results()
    add_button = ui.button("Add 0 to Inbox")
    add_button.set_enabled(False)
    add_button.set_visibility(False)

    def copy_summary() -> None:
        error.text = ""
        text = seed({vid: meta for vid, (_, meta, _) in load_songs(vault).items()})  # local files only
        ui.clipboard.write(text)
        summary.value = text
        summary.set_visibility(True)
        status.text = "Copied. Paste it into your chat with Claude, then paste the reply below."

    async def find() -> None:
        error.text = ""
        lines = parse_lines(reply.value or "")
        if not lines:
            error.text = "Paste Claude's reply first."
            return
        notes = {vid: meta for vid, (_, meta, _) in load_songs(vault).items()}
        set_busy(True)
        status.text = "Searching..."
        try:
            result = await run.io_bound(
                lambda: find_new(client(), lines, notes, progress=lambda _m: None)
            )
        except Exception as e:
            status.text = ""
            error.text = f"Couldn't search: {e}. Try signing in again on the Setup screen."
            return
        finally:
            set_busy(False)
        s.update(found=result["found"], skipped=result["skipped"], not_found=result["not_found"])
        s["ticks"] = {c["videoId"]: True for c in result["found"]}
        status.text = f"Searched {len(lines)} line{'' if len(lines) == 1 else 's'}."
        results.refresh()
        update_add_button()

    def confirm_add() -> None:
        n = len(ticked())
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Add {n} song{'' if n == 1 else 's'} to your Inbox?").classes("text-h6")
            if n > MAX_OPS:
                ui.label(f"This is done {MAX_OPS} at a time. Press Add again afterwards for the rest.")
            ui.label("You can undo this from History.")
            with ui.row():
                ui.button("Yes, add them", on_click=partial(do_add, dialog))
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    async def do_add(dialog, event=None):
        dialog.close()
        todo = ticked()
        error.text = ""
        set_busy(True)
        status.text = f"Adding up to {MAX_OPS} songs..."
        new_notes, log, problem = {}, None, None
        try:
            result = await run.io_bound(
                lambda: add_found(
                    client(), todo, inbox_id, date.today(),
                    max_ops=MAX_OPS, log_dir=state.base, progress=lambda _m: None,
                )
            )
            new_notes, log = result["new_notes"], result["log"]
        except ApplyError as e:
            new_notes, log, problem = e.new_notes, e.log, f"Stopped: {e}."
        except Exception as e:
            problem = f"Couldn't add the songs: {e}."
        finally:
            set_busy(False)
        if new_notes:
            save_songs(vault, load_songs(vault), new_notes)
        added = set(new_notes)
        s["found"] = [c for c in s["found"] if c["videoId"] not in added]
        for vid in added:
            s["ticks"].pop(vid, None)
        status.text = ""
        if problem:
            error.text = problem
            if log:
                error.text += " Some songs may have been added. Your undo log is saved, so History can undo them."
        else:
            status.text = f"Added {len(added)} song{'' if len(added) == 1 else 's'} to your Inbox."
            if log:
                status.text += " You can undo this from History."
        left = len(ticked())
        if left:
            status.text += f" {left} more {'is' if left == 1 else 'are'} still ticked: press Add again for the next batch."
        results.refresh()
        update_add_button()

    copy_button.on_click(copy_summary)
    find_button.on_click(find)
    add_button.on_click(confirm_add)
