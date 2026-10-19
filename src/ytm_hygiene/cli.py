"""ytm-hygiene command line."""

import argparse
import sys
from datetime import date
from pathlib import Path

from .client import Throttle, make_client, normalize_playlist_id
from .evaluate import evaluate
from .match import DEFAULT_THRESHOLD
from .scan import read_report, save_backup, scan_playlist, write_report
from .sync import DEFAULT_EXPIRE_DAYS, sync
from .vault import load_songs, save_songs


def _fetch(args):
    """Fetch the whole playlist once and back it up before anything else."""
    yt = make_client(args.auth)
    playlist_id = normalize_playlist_id(args.playlist)
    playlist = yt.get_playlist(playlist_id, limit=None)
    return playlist_id, playlist, save_backup(playlist, playlist_id), yt


def cmd_backup(args) -> None:
    _, playlist, path, _ = _fetch(args)
    print(f"Saved {len(playlist.get('tracks') or [])} tracks to {path}")


def cmd_scan(args) -> None:
    playlist_id, playlist, backup, yt = _fetch(args)
    print(f"Backup: {backup}")
    rows = scan_playlist(yt, playlist, playlist_id, args.threshold, args.clean)
    write_report(rows, args.out)
    counts = {a: sum(r["action"] == a for r in rows) for a in ("SWAP", "REVIEW", "NO_MATCH", "KEEP")}
    print(f"Wrote {args.out}: " + ", ".join(f"{a}={n}" for a, n in counts.items()))


def cmd_evaluate(args) -> None:
    print(evaluate(read_report(args.report)))


def cmd_sync(args) -> None:
    yt = make_client(args.auth)
    throttle = Throttle()
    fetched = []
    for playlist in (args.inbox, args.rotation):
        throttle.wait()
        fetched.append(yt.get_playlist(normalize_playlist_id(playlist), limit=None).get("tracks") or [])
    throttle.wait()
    history = yt.get_history()

    existing = load_songs(args.vault)
    notes, moves = sync(
        {vid: meta for vid, (_, meta, _) in existing.items()}, *fetched, history, date.today(), args.expire_days
    )
    written = save_songs(args.vault, existing, notes)
    print(f"Updated {written} song notes in {args.vault}")
    for move in moves:
        print(f"would {move.action}: {move.title} ({move.reason})")
    if not moves:
        print("No playlist moves proposed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ytm-hygiene", description=__doc__)
    parser.add_argument("--auth", default="browser.json", help="browser headers file (default: browser.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backup", help="save the playlist JSON to backups/")
    p.add_argument("playlist", help="playlist ID or URL")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("scan", help="read-only: classify tracks and write a report CSV")
    p.add_argument("playlist", help="playlist ID or URL")
    p.add_argument("--out", type=Path, default=Path("report.csv"))
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    p.add_argument("--clean", action="store_true", help="kid-friendly: flag explicit songs, prefer clean")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("evaluate", help="summarize the verdict column of a report")
    p.add_argument("report", type=Path)
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("sync", help="update Obsidian song notes; prints proposed playlist moves (no YouTube writes)")
    p.add_argument("--vault", type=Path, required=True, help="Obsidian vault folder")
    p.add_argument("--inbox", required=True, help="Inbox playlist ID or URL")
    p.add_argument("--rotation", required=True, help="Rotation playlist ID or URL")
    p.add_argument("--expire-days", type=int, default=DEFAULT_EXPIRE_DAYS)
    p.set_defaults(func=cmd_sync)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command != "evaluate" and not Path(args.auth).exists():
        sys.exit(f"{args.auth} not found. Create it with: ytmusicapi browser")
    args.func(args)


if __name__ == "__main__":
    main()
