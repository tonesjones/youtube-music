"""Sign-in from pasted request headers: clean them, check them with one read,
and only then write browser.json. Browser headers only, never OAuth."""

import json
import re
from pathlib import Path

from ytmusicapi import setup as parse_headers
from ytmusicapi.exceptions import YTMusicError

from .client import make_client

_HEADER_NAME = re.compile(r"^[a-z0-9-]+$")  # drops request lines like "post /youtubei/..."
# Firefox copies these. With them the reply comes back compressed and ytmusicapi can't read it.
BROKEN = {"content-encoding", "accept-encoding"}

WRONG_PASTE = (
    "These don't look like the right headers. Copy them from a request named "
    '"browse" on music.youtube.com while you are signed in.'
)
REJECTED = "YouTube Music didn't accept these headers. Sign in again in your browser and copy fresh ones."


class SignInError(Exception):
    pass


def clean_headers(raw: str) -> dict:
    try:
        headers = json.loads(parse_headers(headers_raw=raw.replace("\r", "")))
    except YTMusicError as e:
        raise SignInError(WRONG_PASTE) from e
    return {k: v for k, v in headers.items() if _HEADER_NAME.match(k) and k not in BROKEN}


def sign_in(raw: str, auth_path: Path):
    """Returns (client, your playlists). Writes auth_path only if the read works."""
    headers = clean_headers(raw)
    yt = make_client(json.dumps(headers))
    try:
        playlists = yt.get_library_playlists(limit=None)
    except Exception as e:
        raise SignInError(REJECTED) from e
    auth_path.write_text(json.dumps(headers, indent=4, sort_keys=True), encoding="utf-8")
    return yt, playlists
