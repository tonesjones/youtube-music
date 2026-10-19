"""Clean up a playlist: swap music videos for the song version, with a confirm step."""

import re
from functools import partial

from nicegui import run, ui

from ..apply import ApplyError, apply_rows
from ..client import make_client
from ..scan import save_backup, scan_playlist
from .state import AppState

MAX_OPS = 20  # same cap as the CLI default

REASONS = {
    "duration": "different length",
    "artist": "different artist",
    "version:live": "one is a live version",
    "version:remixer": "different remix",
    "clean_version": "clean version of an explicit song",
    "explicit": "explicit",
    "official_source": "may be a live set or a compilation",
    "no_setVideoId": "can't be swapped in this playlist",
    "no_duration": "length unknown",
}
PROGRESS = re.compile(r"\[(\d+)/(\d+)\]")


def plain_reasons(flags) -> list[str]:
    """Plain-words reasons for a row's flags (a list, or the CSV-style 'a;b' string)."""
    if isinstance(flags, str):
        flags = [f for f in flags.split(";") if f]
    out = []
    for flag in flags:
        if flag in REASONS:
            text = REASONS[flag]
        elif flag.startswith("version:"):
            text = f"different version: {flag.split(':', 1)[1]}"
        else:
            text = flag.replace("_", " ").replace(":", ": ")
        if text not in out:
            out.append(text)
    return out


def can_swap(row: dict) -> bool:
    return bool(row.get("candidate_videoId") and row.get("old_setVideoId"))


def build(state: AppState) -> None:
    s = {"yt": None, "playlists": {}, "rows": [], "ticks": {}, "verdicts": {}, "name": "", "playlist_id": None, "busy": False}
    progress = {"done": 0, "total": 0}

    def client():
        if s["yt"] is None:
            s["yt"] = make_client(str(state.auth_path))
        return s["yt"]

    if not state.signed_in:
        ui.label("Sign in first on the Setup screen.").classes("text-grey")
        return

    ui.label("Swap music videos in a playlist for the song version. Nothing changes until you confirm.")
    with ui.row().classes("items-center w-full"):
        choose_button = ui.button("Choose a playlist")
        picker = ui.select({}, label="Playlist", value=None).classes("min-w-[320px]")
        picker.set_visibility(False)
        check_button = ui.button("Check this playlist")
        check_button.set_visibility(False)
    bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
    bar.set_visibility(False)
    status = ui.label()
    error = ui.label().classes("text-negative")
    buttons = [choose_button, check_button]

    def set_busy(busy: bool) -> None:
        s["busy"] = busy
        for b in buttons:
            b.set_enabled(not busy)
        update_swap_button()

    def ticked() -> list[dict]:
        return [r for r in s["rows"] if s["ticks"].get(r["position"]) and can_swap(r)]

    def update_swap_button() -> None:
        n = len(ticked())
        swap_button.text = f"Swap {n} song{'' if n == 1 else 's'}"
        swap_button.set_enabled(n > 0 and not s["busy"])

    def set_tick(position, event) -> None:
        s["ticks"][position] = bool(event.value)
        update_swap_button()

    def set_verdict(position, event) -> None:
        s["verdicts"][position] = event.value
        s["ticks"][position] = event.value == "right"
        update_swap_button()
        results.refresh()

    def song_line(title, artist) -> str:
        return f"{title} - {artist}" if artist else title

    def show_row(row: dict, review: bool = False) -> None:
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center w-full no-wrap"):
                if row["action"] != "NO_MATCH":
                    box = ui.checkbox(value=bool(s["ticks"].get(row["position"])))
                    box.on_value_change(partial(set_tick, row["position"]))
                    box.set_enabled(can_swap(row))
                with ui.column().classes("gap-0"):
                    with ui.row().classes("items-center"):
                        ui.label(f"Your video: {song_line(row['title'], row['artist'])}")
                        if row["old_url"]:
                            ui.link("Open", row["old_url"], new_tab=True)
                    if row["candidate_title"]:
                        with ui.row().classes("items-center"):
                            ui.label(f"Song found: {song_line(row['candidate_title'], row['candidate_artist'])}")
                            ui.link("Open", row["candidate_url"], new_tab=True)
                    default = {"SWAP": "same song, same artist"}.get(row["action"], "not a close match")
                    ui.label(", ".join(plain_reasons(row["flags"])) or default).classes("text-caption text-grey")
                if review:
                    toggle = ui.toggle({"right": "Looks right", "wrong": "Wrong"}, value=s["verdicts"].get(row["position"]))
                    toggle.on_value_change(partial(set_verdict, row["position"]))
                    toggle.set_enabled(can_swap(row))

    @ui.refreshable
    def results() -> None:
        if not s["rows"]:
            return
        groups = {a: [r for r in s["rows"] if r["action"] == a] for a in ("SWAP", "REVIEW", "NO_MATCH", "KEEP")}
        if groups["KEEP"]:
            n = len(groups["KEEP"])
            ui.label("1 track is already a song." if n == 1 else f"{n} tracks are already songs.")
        for action, title, review in (("SWAP", "Ready to swap", False), ("REVIEW", "Please check these", True)):
            if groups[action]:
                ui.label(f"{title} ({len(groups[action])})").classes("text-h6")
                for row in groups[action]:
                    show_row(row, review)
        if groups["NO_MATCH"]:
            with ui.expansion(f"No song version found ({len(groups['NO_MATCH'])})").classes("w-full"):
                for row in groups["NO_MATCH"]:
                    show_row(row)

    results()
    swap_button = ui.button("Swap 0 songs")
    swap_button.set_enabled(False)
    swap_button.set_visibility(False)

    async def load_playlists():
        error.text = ""
        set_busy(True)
        try:
            found = await run.io_bound(lambda: client().get_library_playlists(limit=None))
        except Exception as e:
            error.text = f"Couldn't load your playlists: {e}. Try signing in again on the Setup screen."
            return
        finally:
            set_busy(False)
        s["playlists"] = {p["playlistId"]: p.get("title") or p["playlistId"] for p in found}
        picker.set_options(s["playlists"], value=None)
        picker.set_visibility(True)
        check_button.set_visibility(True)
        choose_button.set_visibility(False)

    def work_check(playlist_id: str):
        """Runs off the UI thread: touches only `progress`, never UI elements."""

        def on_progress(message):
            m = PROGRESS.search(str(message))
            if m:
                progress["done"] = int(m.group(1))

        playlist = client().get_playlist(playlist_id, limit=None)
        save_backup(playlist, playlist_id, state.base / "backups")
        progress.update(done=0, total=len(playlist.get("tracks") or []))
        return scan_playlist(client(), playlist, playlist_id, progress=on_progress)

    def show_progress() -> None:
        total = progress["total"]
        bar.value = progress["done"] / total if total else 0
        status.text = f"Checking {progress['done']} of {total}" if total else "Fetching the playlist..."

    timer = ui.timer(0.3, show_progress, active=False)  # local only, no network

    async def check():
        playlist_id = picker.value
        if not playlist_id:
            error.text = "Choose a playlist first."
            return
        error.text = ""
        s["rows"], s["ticks"], s["verdicts"] = [], {}, {}
        s["name"], s["playlist_id"] = s["playlists"].get(playlist_id, playlist_id), playlist_id
        results.refresh()
        swap_button.set_visibility(False)
        progress.update(done=0, total=0)
        bar.value = 0
        bar.set_visibility(True)
        set_busy(True)
        timer.activate()
        try:
            rows = await run.io_bound(work_check, playlist_id)
        except Exception as e:
            status.text = ""
            error.text = f"Couldn't check this playlist: {e}"
            return
        finally:
            timer.deactivate()
            bar.set_visibility(False)
            set_busy(False)
        s["rows"] = rows
        s["ticks"] = {r["position"]: r["action"] == "SWAP" and can_swap(r) for r in rows}
        status.text = f"Checked {len(rows)} tracks."
        results.refresh()
        swap_button.set_visibility(True)
        update_swap_button()

    def confirm_swap() -> None:
        todo = ticked()
        n = len(todo)
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Swap {n} song{'' if n == 1 else 's'} in \"{s['name']}\"?").classes("text-h6")
            if n > MAX_OPS:
                ui.label(f"This is done {MAX_OPS} at a time. Press Swap again afterwards for the rest.")
            ui.label("You can undo this from History.")
            with ui.row():
                ui.button("Yes, swap them", on_click=partial(do_swap, dialog))
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    async def do_swap(dialog, event=None):
        dialog.close()
        playlist_id = s["playlist_id"]  # the playlist that was checked, even if the picker changed since
        rows = [dict(r, verdict="correct") for r in ticked()]
        error.text = ""
        before = set(state.base.glob("undo-*.json"))
        set_busy(True)
        status.text = f"Swapping up to {MAX_OPS} songs..."
        try:
            result = await run.io_bound(
                partial(
                    apply_rows,
                    client(),
                    rows,
                    playlist_id,
                    max_ops=MAX_OPS,
                    log_dir=state.base,
                    backup_dir=state.base / "backups",
                    progress=lambda message: None,
                )
            )
        except (ApplyError, ValueError) as e:
            status.text = ""
            error.text = f"Stopped: {e}."
            if set(state.base.glob("undo-*.json")) - before:
                error.text += (
                    " Some swaps may have gone through. Your undo log is saved, so History can undo them."
                    " Check the playlist again to see where it stands."
                )
            return
        finally:
            set_busy(False)
        done = set(result["positions"])
        s["rows"] = [r for r in s["rows"] if r["position"] not in done]
        for position in done:
            s["ticks"].pop(position, None)
        n = result["swapped"]
        status.text = f"Swapped {n} song{'' if n == 1 else 's'}."
        if result["stale"]:
            status.text += f" {result['stale']} had already changed in the playlist and were skipped."
        if result["log"]:
            status.text += " You can undo this from History."
        left = len(ticked())
        if left:
            status.text += f" {left} more {'is' if left == 1 else 'are'} still ticked: press Swap again for the next batch."
        results.refresh()
        update_swap_button()

    choose_button.on_click(load_playlists)
    check_button.on_click(check)
    swap_button.on_click(confirm_swap)
