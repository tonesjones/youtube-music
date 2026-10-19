"""Song notes in an Obsidian vault: one Markdown file per song with YAML frontmatter.

Only the frontmatter is managed; anything you write in the note body is kept.
"""

import re
from pathlib import Path

import yaml

SONGS_DIR = Path("Music/Songs")
DASHBOARD = Path("Music/Music Dashboard.md")

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)
_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')

DASHBOARD_TEXT = """\
# Music Dashboard

Needs the Dataview community plugin. Change a song's `status` in its note
(keeper / rejected / inbox) and the next sync proposes the playlist move.

## Inbox
```dataview
TABLE artists, added, length(heard_days) AS days_heard, like
FROM "Music/Songs" WHERE status = "inbox" SORT added ASC
```

## Keepers
```dataview
TABLE artists, playlist, last_heard
FROM "Music/Songs" WHERE status = "keeper" SORT last_heard DESC
```

## Rejected or expired
```dataview
TABLE artists, status, source, added
FROM "Music/Songs" WHERE status = "rejected" OR status = "expired" SORT added DESC
```

## Suggestion hit rate by source
```dataview
TABLE length(filter(rows.status, (s) => s = "keeper")) AS kept, length(rows) AS total
FROM "Music/Songs" GROUP BY source
```
"""


class _NoAliasDumper(yaml.SafeDumper):
    """Obsidian properties don't understand YAML anchors like &id001."""

    def ignore_aliases(self, data):
        return True


def read_note(path: Path) -> tuple[dict, str]:
    m = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if not m:
        return {}, path.read_text(encoding="utf-8")
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def write_note(path: Path, meta: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    front = yaml.dump(meta, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{front}---\n{body}", encoding="utf-8")


def note_filename(meta: dict) -> str:
    artist = (meta.get("artists") or ["Unknown"])[0]
    name = _UNSAFE.sub("", f"{artist} - {meta.get('title') or meta['videoId']}").strip()
    return f"{name[:120]}.md"


def load_songs(vault: Path) -> dict[str, tuple[Path, dict, str]]:
    """videoId -> (path, frontmatter, body) for every song note."""
    songs = {}
    for path in sorted((vault / SONGS_DIR).glob("*.md")):
        meta, body = read_note(path)
        if meta.get("videoId"):
            songs[meta["videoId"]] = (path, meta, body)
    return songs


def save_songs(vault: Path, existing: dict, updated: dict[str, dict]) -> int:
    """Write changed or new notes. Returns how many files were written."""
    written = 0
    for video_id, meta in updated.items():
        if video_id in existing:
            path, old_meta, body = existing[video_id]
            if old_meta == meta:
                continue
        else:
            path, body = vault / SONGS_DIR / note_filename(meta), "\n## Notes\n"
            if path.exists():  # same artist and title, different videoId
                path = path.with_name(f"{path.stem} ({video_id}).md")
        write_note(path, meta, body)
        written += 1
    dashboard = vault / DASHBOARD
    if not dashboard.exists():
        dashboard.parent.mkdir(parents=True, exist_ok=True)
        dashboard.write_text(DASHBOARD_TEXT, encoding="utf-8")
    return written
