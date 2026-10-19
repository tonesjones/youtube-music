"""Placeholder until U4 builds this screen."""

from nicegui import ui

from .state import AppState


def build(state: AppState) -> None:
    ui.label("Coming soon.").classes("text-grey")
