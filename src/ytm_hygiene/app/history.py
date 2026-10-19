"""History: the saved undo logs, newest first. Undo puts a run's playlists back as they were."""

import json
import re
from datetime import datetime
from functools import partial
from pathlib import Path

from nicegui import run, ui

from ..apply import ApplyError, undo
from ..client import make_client
from .state import AppState

LOG_NAME = re.compile(r"(undo|undone)-(\d{8}-\d{6})\.json")


def when_text(stamp: str) -> str:
    """'20260101-090000' -> '1 Jan 2026, 09:00'."""
    dt = datetime.strptime(stamp, "%Y%m%d-%H%M%S")
    return f"{dt.day} {dt:%b %Y, %H:%M}"


def summary(steps: list) -> str:
    """Plain summary of a log's steps. Moves are not counted."""
    added = sum(1 for s in steps if s.get("op") == "add")
    removed = sum(1 for s in steps if s.get("op") == "remove")
    if not added and not removed:
        return "No songs added or removed"
    return f"{added} song{'' if added == 1 else 's'} added, {removed} removed"


def read_entries(base: Path) -> list[dict]:
    """Files only, no network. Newest first. Logs that can't be read are listed, without Undo."""
    entries = []
    for pattern in ("undo-*.json", "undone-*.json"):
        for path in base.glob(pattern):
            m = LOG_NAME.fullmatch(path.name)
            if not m or not path.is_file():
                continue
            try:
                when = when_text(m.group(2))
            except ValueError:
                continue
            try:
                log = json.loads(path.read_text(encoding="utf-8"))
                text, ids = summary(log["steps"]), list(log["playlist_ids"])
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                text, ids = "Can't read this log", None
            entries.append({
                "key": m.group(2), "path": path, "when": when, "summary": text,
                "playlist_ids": ids, "undone": m.group(1) == "undone",
            })  # fmt: skip
    return sorted(entries, key=lambda e: e["key"], reverse=True)


def build(state: AppState):
    s = {"yt": None, "busy": False}

    def client():
        if s["yt"] is None:
            s["yt"] = make_client(str(state.auth_path))
        return s["yt"]

    if not state.signed_in:
        ui.label("Sign in first on the Setup screen.").classes("text-grey")
        return

    ui.label("Put your playlists back the way they were before a clean-up, Inbox or suggestions run. Nothing is read until you press Undo.")

    def set_busy(busy: bool) -> None:
        s["busy"] = busy
        refresh_button.set_enabled(not busy)
        results.refresh()

    refresh_button = ui.button("Refresh", on_click=lambda: results.refresh())
    error = ui.label().classes("text-negative")

    async def do_undo(dialog, entry, event=None):
        dialog.close()
        error.text = ""
        set_busy(True)
        try:
            await run.io_bound(
                partial(undo, client(), entry["path"], entry["playlist_ids"], progress=lambda message: None)
            )
            # Renamed only after a clean undo, so a log can't be undone twice.
            entry["path"].rename(entry["path"].with_name("undone-" + entry["path"].name.removeprefix("undo-")))
        except (ApplyError, ValueError) as e:
            error.text = f"Couldn't undo this run: {e}. The log is kept, so you can try again."
        finally:
            set_busy(False)

    def confirm_undo(entry, event=None) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label("Put back the playlists as they were before this run?").classes("text-h6")
            ui.label(f"{entry['when']}: {entry['summary']}")
            with ui.row():
                ui.button("Yes, undo it", on_click=partial(do_undo, dialog, entry))
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    @ui.refreshable
    def results() -> None:
        entries = read_entries(state.base)
        if not entries:
            ui.label("No runs to undo yet.").classes("text-grey")
            return
        for entry in entries:
            style = "text-grey" if entry["undone"] else ""
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center w-full no-wrap"):
                    with ui.column().classes("gap-0 grow"):
                        ui.label(entry["when"]).classes(style)
                        ui.label(entry["summary"]).classes(f"text-caption {style or 'text-grey'}")
                    if entry["undone"]:
                        ui.label("Already undone").classes("text-grey")
                    elif entry["playlist_ids"] is not None:
                        ui.button("Undo", on_click=partial(confirm_undo, entry)).set_enabled(not s["busy"])

    results()
    return results.refresh  # the shell calls this whenever History is opened
