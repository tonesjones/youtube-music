"""Desktop app: a window over the same functions the CLI uses."""

import os
import sys
import traceback
from pathlib import Path

from nicegui import ui

from ..settings import app_dir
from .shell import root

TITLE = "YouTube Music Cleanup"


def check() -> int:
    """Import what the app needs and build a client; no window, no network.

    A windowed exe has no console, so a failure is written to check-error.txt.
    """
    try:
        import webview  # noqa: F401
        from ytmusicapi import YTMusic

        from . import cleanup, history, inbox, setup, suggest  # noqa: F401

        YTMusic()
    except Exception:
        Path("check-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return 1
    return 0


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if "--check" in args:
        sys.exit(check())
    base = app_dir()
    base.mkdir(parents=True, exist_ok=True)
    os.chdir(base)  # backups/ and undo logs land here, as with the CLI
    ui.run(root, native=True, title=TITLE, window_size=(1100, 760), reload=False)
