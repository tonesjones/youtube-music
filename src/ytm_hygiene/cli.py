"""ytm-hygiene command line."""

import argparse
import sys
import tomllib
from datetime import date
from pathlib import Path

from .apply import ApplyError, apply_moves, apply_rows, undo
from .client import Throttle, make_client, normalize_playlist_id
from .evaluate import evaluate
from .match import DEFAULT_THRESHOLD
from .scan import read_report, save_backup, scan_playlist, write_report
from .suggest import parse_lines, seed, suggest
from .sync import DEFAULT_EXPIRE_DAYS, sync
from .vault import load_songs, load_state, save_songs, save_state

DEFAULT_CONFIG = Path("ytm-hygiene.toml")


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


def cmd_apply(args) -> None:
    yt = make_client(args.auth)
    try:
        result = apply_rows(
            yt, read_report(args.report), normalize_playlist_id(args.allow_playlist), args.max_ops, args.dry_run
        )
    except (ValueError, ApplyError) as e:
        sys.exit(f"Stopped: {e}")
    print(f"{result['swapped']} of {result['selected']} swaps done, {result['stale']} stale rows skipped.")
    if result["log"]:
        print(f"Undo with: ytm-hygiene undo {result['log']} --allow-playlist {args.allow_playlist}")


def cmd_undo(args) -> None:
    yt = make_client(args.auth)
    try:
        result = undo(yt, args.log, [normalize_playlist_id(p) for p in args.allow_playlist], args.dry_run)
    except (ValueError, ApplyError) as e:
        sys.exit(f"Stopped: {e}")
    print(f"Undid {result['undone']} steps.")


def _apply_config(args, required: tuple[str, ...] = ("vault", "inbox", "rotation")) -> None:
    """Fill settings left off the command line from the TOML config."""
    config = {}
    if args.config.exists():
        with args.config.open("rb") as f:
            config = tomllib.load(f)
    elif args.config != DEFAULT_CONFIG:
        sys.exit(f"{args.config} not found")
    for key in ("vault", "inbox", "rotation", "expire_days"):
        if getattr(args, key, None) is None:
            setattr(args, key, config.get(key))
    missing = [key for key in required if not getattr(args, key)]
    if missing:
        sys.exit(f"Missing {', '.join(missing)}: pass --{missing[0]} or set it in {args.config}")
    args.vault = Path(args.vault)
    args.expire_days = args.expire_days or DEFAULT_EXPIRE_DAYS


def cmd_sync(args) -> None:
    _apply_config(args)
    yt = make_client(args.auth)
    throttle = Throttle()
    inbox_id, rotation_id = normalize_playlist_id(args.inbox), normalize_playlist_id(args.rotation)
    fetched = []
    for playlist_id in (inbox_id, rotation_id):
        throttle.wait()
        fetched.append(yt.get_playlist(playlist_id, limit=None).get("tracks") or [])
    throttle.wait()
    history = yt.get_history()

    existing = load_songs(args.vault)
    result = sync(
        {vid: meta for vid, (_, meta, _) in existing.items()},
        *fetched,
        history,
        load_state(args.vault),
        date.today(),
        args.expire_days,
    )
    if result.warning:
        print(f"Warning: {result.warning}")
    written = save_songs(args.vault, existing, result.notes)
    save_state(args.vault, result.state)  # after the notes, so a failed run doesn't advance the anchor
    print(f"Updated {written} song notes in {args.vault}")
    for move in result.moves:
        print(f"would {move.action}: {move.title} ({move.reason})")
    if not result.moves:
        print("No playlist moves proposed.")
    if args.apply and result.moves:
        _apply_sync_moves(args, yt, result.moves, inbox_id, rotation_id, *fetched)


def _apply_sync_moves(args, yt, moves, inbox_id, rotation_id, inbox_tracks, rotation_tracks) -> None:
    if inbox_id == rotation_id:
        sys.exit("Inbox and Rotation are the same playlist; not applying moves.")
    try:
        done = apply_moves(
            yt, moves, inbox_id, rotation_id, inbox_tracks, rotation_tracks, args.max_ops, args.dry_run
        )
    except ApplyError as e:
        print(f"Undo log: {e.log}" if e.log else "No writes were logged.")
        sys.exit(f"Stopped: {e}")
    print(f"{done['done']} of {len(moves)} moves done (max {args.max_ops}), {done['skipped']} skipped.")
    if done["log"]:
        print(f"Undo with: ytm-hygiene undo {done['log']} --allow-playlist {inbox_id} --allow-playlist {rotation_id}")


def cmd_suggest(args) -> None:
    if args.seed == bool(args.file):
        sys.exit("Give either --seed or a songs file.")
    _apply_config(args, required=("vault",) if args.seed else ("vault", "inbox"))
    existing = load_songs(args.vault)
    if args.seed:
        print(seed({vid: meta for vid, (_, meta, _) in existing.items()}))
        return
    lines = parse_lines(args.file.read_text(encoding="utf-8"))
    inbox_id = normalize_playlist_id(args.inbox)
    yt = make_client(args.auth)
    notes = {vid: meta for vid, (_, meta, _) in existing.items()}
    try:
        result = suggest(yt, lines, notes, inbox_id, date.today(), args.max_ops, args.dry_run)
    except ApplyError as e:
        save_songs(args.vault, existing, e.new_notes)
        print(f"Undo log: {e.log}" if e.log else "No writes were logged.")
        sys.exit(f"Stopped: {e}")
    save_songs(args.vault, existing, result["new_notes"])
    print(
        f"{len(result['found'])} found, {len(result['skipped'])} already known, "
        f"{len(result['not_found'])} not found; {len(result['new_notes'])} added to the Inbox."
    )
    if result["log"]:
        print(f"Undo with: ytm-hygiene undo {result['log']} --allow-playlist {inbox_id}")


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
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"settings file (default: {DEFAULT_CONFIG})")
    p.add_argument("--vault", help="Obsidian vault folder")
    p.add_argument("--inbox", help="Inbox playlist ID or URL")
    p.add_argument("--rotation", help="Rotation playlist ID or URL")
    p.add_argument("--expire-days", type=int, help=f"default {DEFAULT_EXPIRE_DAYS}")
    p.add_argument("--apply", action="store_true", help="carry out the proposed moves on the Inbox and Rotation")
    p.add_argument("--dry-run", action="store_true", help="with --apply: print the writes, make none")
    p.add_argument("--max-ops", type=int, default=20, help="with --apply: max moves this run (default 20)")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("suggest", help="print a taste summary (--seed), or add 'Artist - Title' lines to the Inbox")
    p.add_argument("file", type=Path, nargs="?", help="text file of 'Artist - Title' lines")
    p.add_argument("--seed", action="store_true", help="print keepers and rejected songs; no network")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"settings file (default: {DEFAULT_CONFIG})")
    p.add_argument("--vault", help="Obsidian vault folder")
    p.add_argument("--inbox", help="Inbox playlist ID or URL")
    p.add_argument("--dry-run", action="store_true", help="search and print; add nothing, write no notes")
    p.add_argument("--max-ops", type=int, default=20, help="max songs added this run (default 20)")
    p.set_defaults(func=cmd_suggest)

    p = sub.add_parser("apply", help="swap tracks in place from a report (SWAP rows and verdict=correct rows)")
    p.add_argument("report", type=Path)
    p.add_argument("--allow-playlist", required=True, help="must match the report's playlist")
    p.add_argument("--max-ops", type=int, default=20, help="max swaps this run (default 20)")
    p.add_argument("--dry-run", action="store_true", help="print the writes, make none")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("undo", help="reverse an apply run from its undo log")
    p.add_argument("log", type=Path, help="undo-<timestamp>.json")
    p.add_argument(
        "--allow-playlist", required=True, action="append", help="a playlist in the log; repeat for each one"
    )
    p.add_argument("--dry-run", action="store_true", help="print the writes, make none")
    p.set_defaults(func=cmd_undo)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    offline = args.command == "evaluate" or getattr(args, "seed", False)
    if not offline and not Path(args.auth).exists():
        sys.exit(f"{args.auth} not found. Create it with: ytmusicapi browser")
    args.func(args)


if __name__ == "__main__":
    main()
