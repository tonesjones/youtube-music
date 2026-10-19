"""Inbox: check what you've listened to, then move or remove songs, with a confirm step."""

from datetime import date
from functools import partial
from pathlib import Path

from nicegui import run, ui

from ..apply import ApplyError, apply_moves
from ..client import Throttle, make_client, normalize_playlist_id
from ..sync import DEFAULT_EXPIRE_DAYS, sync
from ..vault import load_songs, load_state, save_songs, save_state
from .state import AppState

MAX_OPS = 20  # same cap as the CLI default

GROUPS = (
    ("promote", "Move to Rotation"),
    ("remove_inbox", "Remove from Inbox"),
    ("remove_rotation", "Remove from Rotation"),
)


def plain_reason(reason: str) -> str:
    return reason.replace("syncs", "checks")


def build(state: AppState) -> None:
    cfg = state.settings
    if not (cfg.get("vault") and cfg.get("inbox") and cfg.get("rotation") and state.signed_in):
        ui.label("Finish the Setup screen first: sign in and choose your vault, Inbox and Rotation.").classes("text-grey")
        return

    s = {"yt": None, "moves": [], "ticks": {}, "trial": [], "tracks": ([], []), "checked": False, "busy": False}

    def client():
        if s["yt"] is None:
            s["yt"] = make_client(str(state.auth_path))
        return s["yt"]

    ui.label("Check which Inbox songs you've played, then choose what to move or remove. Nothing changes until you confirm.")
    check_button = ui.button("Check what I've listened to")
    ui.label(
        "Each check counts toward the keep/expire rules, so check every few days, not every few minutes."
    ).classes("text-caption text-grey")
    status = ui.label()
    error = ui.label().classes("text-negative")

    def ticked() -> list:
        return [m for m in s["moves"] if s["ticks"].get(m.video_id)]

    def update_apply_button() -> None:
        n = len(ticked())
        apply_button.text = f"Apply {n} change{'' if n == 1 else 's'}"
        apply_button.set_enabled(n > 0 and not s["busy"])

    def set_busy(busy: bool) -> None:
        s["busy"] = busy
        check_button.set_enabled(not busy)
        update_apply_button()

    def set_tick(video_id, event) -> None:
        s["ticks"][video_id] = bool(event.value)
        update_apply_button()

    @ui.refreshable
    def results() -> None:
        if not s["checked"]:
            return
        if not s["moves"]:
            ui.label("Nothing to move or remove right now.")
        for action, title in GROUPS:
            group = [m for m in s["moves"] if m.action == action]
            if not group:
                continue
            ui.label(f"{title} ({len(group)})").classes("text-h6")
            for m in group:
                with ui.row().classes("items-center no-wrap"):
                    box = ui.checkbox(value=bool(s["ticks"].get(m.video_id)))
                    box.on_value_change(partial(set_tick, m.video_id))
                    with ui.column().classes("gap-0"):
                        ui.label(m.title)
                        ui.label(plain_reason(m.reason)).classes("text-caption text-grey")
        if s["trial"]:
            with ui.expansion(f"Still on trial ({len(s['trial'])})").classes("w-full"):
                for title, heard in s["trial"]:
                    ui.label(f"{title}: heard in {heard} check{'' if heard == 1 else 's'}")

    results()
    apply_button = ui.button("Apply 0 changes")
    apply_button.set_enabled(False)
    apply_button.set_visibility(False)

    def work_check():
        """Runs off the UI thread, same steps and order as `sync` on the CLI."""
        vault = Path(cfg["vault"])
        yt, throttle = client(), Throttle()
        fetched = []
        for playlist_id in (normalize_playlist_id(cfg["inbox"]), normalize_playlist_id(cfg["rotation"])):
            throttle.wait()
            fetched.append(yt.get_playlist(playlist_id, limit=None).get("tracks") or [])
        throttle.wait()
        history = yt.get_history()
        existing = load_songs(vault)
        result = sync(
            {vid: meta for vid, (_, meta, _) in existing.items()},
            *fetched,
            history,
            load_state(vault),
            date.today(),
            cfg.get("expire_days") or DEFAULT_EXPIRE_DAYS,
        )
        save_songs(vault, existing, result.notes)
        save_state(vault, result.state)  # after the notes, so a failed run doesn't advance the anchor
        return result, fetched

    async def check():
        error.text = status.text = ""
        set_busy(True)
        status.text = "Checking..."
        try:
            result, fetched = await run.io_bound(work_check)
        except Exception as e:
            status.text = ""
            error.text = f"Couldn't check: {e}. If you're signed out, sign in again on the Setup screen."
            return
        finally:
            set_busy(False)
        s["moves"], s["tracks"], s["checked"] = list(result.moves), tuple(fetched), True
        s["ticks"] = {m.video_id: True for m in result.moves}
        s["trial"] = [
            (f"{', '.join(m.get('artists') or [])} - {m.get('title')}", len(m.get("heard_syncs") or []))
            for m in result.notes.values()
            if m.get("playlist") == "inbox" and m.get("status") == "inbox"
        ]
        status.text = "Checked."
        if result.warning:
            status.text += (
                " This was the first check, or you've played a lot since the last one,"
                " so everything in your recent history counts as heard."
            )
        results.refresh()
        apply_button.set_visibility(True)
        update_apply_button()

    def confirm_apply() -> None:
        if normalize_playlist_id(cfg["inbox"]) == normalize_playlist_id(cfg["rotation"]):
            error.text = "Your Inbox and Rotation are the same playlist, so nothing can be moved. Change one on the Setup screen."
            return
        error.text = ""
        n = len(ticked())
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Apply {n} change{'' if n == 1 else 's'}?").classes("text-h6")
            if n > MAX_OPS:
                ui.label(f"This is done {MAX_OPS} at a time. Press Apply again afterwards for the rest.")
            ui.label("You can undo this from History.")
            with ui.row():
                ui.button("Yes, apply them", on_click=partial(do_apply, dialog))
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    async def do_apply(dialog, event=None):
        dialog.close()
        todo = ticked()
        inbox_tracks, rotation_tracks = s["tracks"]
        error.text = ""
        before = set(state.base.glob("undo-*.json"))
        set_busy(True)
        status.text = f"Applying up to {MAX_OPS} changes..."
        try:
            result = await run.io_bound(
                partial(
                    apply_moves,
                    client(),
                    todo,
                    normalize_playlist_id(cfg["inbox"]),
                    normalize_playlist_id(cfg["rotation"]),
                    inbox_tracks,
                    rotation_tracks,
                    max_ops=MAX_OPS,
                    log_dir=state.base,
                    progress=lambda message: None,
                )
            )
        except ApplyError as e:
            status.text = ""
            error.text = f"Stopped: {e}."
            if e.log or set(state.base.glob("undo-*.json")) - before:
                error.text += (
                    " Some changes may have gone through. Your undo log is saved, so History can undo them."
                    " Check again to see where things stand."
                )
            return
        finally:
            set_busy(False)
        handled = {m.video_id for m in todo[:MAX_OPS]}
        s["moves"] = [m for m in s["moves"] if m.video_id not in handled]
        for video_id in handled:
            s["ticks"].pop(video_id, None)
        n = result["done"]
        status.text = f"Done: {n} change{'' if n == 1 else 's'}."
        if result["skipped"]:
            status.text += f" {result['skipped']} had already changed in the playlist and were skipped."
        if result["log"]:
            status.text += " You can undo this from History."
        left = len(ticked())
        if left:
            status.text += f" {left} more {'is' if left == 1 else 'are'} still ticked: press Apply again for the next batch."
        results.refresh()
        update_apply_button()

    check_button.on_click(check)
    apply_button.on_click(confirm_apply)
