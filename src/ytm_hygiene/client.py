"""YouTube Music client setup and request pacing."""

import re
import time

from ytmusicapi import YTMusic

READ_DELAY_S = 1.0


def make_client(auth_path: str) -> YTMusic:
    """Browser-header auth only. English + US keeps filtered search reliable."""
    return YTMusic(auth_path, language="en", location="US")


def normalize_playlist_id(value: str) -> str:
    """Accept a bare ID or a playlist URL; drop the 'VL' browse prefix."""
    m = re.search(r"[?&]list=([\w-]+)", value)
    pid = m.group(1) if m else value.strip()
    return pid[2:] if pid.startswith("VL") else pid


class Throttle:
    """Ensures at least `interval` seconds between calls to wait()."""

    def __init__(self, interval: float = READ_DELAY_S):
        self.interval = interval
        self._last = 0.0

    def wait(self) -> None:
        delay = self._last + self.interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()
