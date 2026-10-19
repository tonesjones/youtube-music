"""Desktop app: a window over the same functions the CLI uses."""

import os

from nicegui import ui

from ..settings import app_dir
from .shell import root

TITLE = "YouTube Music Cleanup"


def main() -> None:
    base = app_dir()
    base.mkdir(parents=True, exist_ok=True)
    os.chdir(base)  # backups/ and undo logs land here, as with the CLI
    ui.run(root, native=True, title=TITLE, window_size=(1100, 760), reload=False)
