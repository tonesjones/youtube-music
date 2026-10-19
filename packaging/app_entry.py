"""PyInstaller entry point for the desktop app."""

import multiprocessing

from ytm_hygiene.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # the native window runs in a child process
    main()
