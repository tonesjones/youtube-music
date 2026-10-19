"""First-run setup. U1 shows what is set; the wizard comes in U2."""

from nicegui import ui

from .state import AppState


def build(state: AppState) -> None:
    checks = [
        ("Signed in to YouTube Music", state.signed_in),
        ("Obsidian vault chosen", bool(state.settings.get("vault"))),
        ("Inbox playlist chosen", bool(state.settings.get("inbox"))),
        ("Rotation playlist chosen", bool(state.settings.get("rotation"))),
    ]
    for text, done in checks:
        with ui.row().classes("items-center"):
            ui.icon("check_circle" if done else "radio_button_unchecked", color="positive" if done else "grey")
            ui.label(text)
    ui.label(f"Files are kept in {state.base}").classes("text-caption text-grey")
