"""The window: a header, the screen list on the left, the chosen screen on the right."""

from pathlib import Path

from nicegui import ui

from . import cleanup, history, inbox, setup, suggest
from .state import AppState

SCREENS = [  # (key, label, icon, module)
    ("setup", "Setup", "settings", setup),
    ("cleanup", "Clean up a playlist", "cleaning_services", cleanup),
    ("inbox", "Inbox", "inbox", inbox),
    ("suggest", "Get suggestions", "lightbulb", suggest),
    ("history", "History", "history", history),
]


def root() -> None:
    state = AppState.load(Path.cwd())
    ui.page_title("YouTube Music Cleanup")
    ui.dark_mode(None)  # follow the system light/dark setting
    with ui.header().classes("items-center"):
        ui.label("YouTube Music Cleanup").classes("text-lg font-medium")
    with ui.left_drawer(fixed=True).props("width=220 bordered breakpoint=0"):
        with ui.tabs().props("vertical no-caps inline-label").classes("w-full") as tabs:
            tab = {key: ui.tab(key, label=label, icon=icon) for key, label, icon, _ in SCREENS}
    first = "cleanup" if state.signed_in else "setup"
    with ui.tab_panels(tabs, value=tab[first]).classes("w-full bg-transparent"):
        for key, label, _, module in SCREENS:
            with ui.tab_panel(tab[key]):
                ui.label(label).classes("text-h5")
                module.build(state)
