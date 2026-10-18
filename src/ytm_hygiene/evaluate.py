"""Summarize hand-filled verdicts in a scan report and suggest a threshold.

Verdicts: correct (the proposed song is right), wrong (it isn't),
missed (a song version exists but the tool didn't propose it).
"""

from collections import Counter

VERDICTS = {"correct", "wrong", "missed"}


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "n/a"


def threshold_sweep(rows: list[dict]) -> list[tuple[float, int, int]]:
    """For each threshold: (t, rows that would SWAP, how many of those are correct).
    Only unflagged rows count, since any flag forces REVIEW regardless of score."""
    judged = [
        (float(r["score"]), r["verdict"] == "correct")
        for r in rows
        if r["action"] in ("SWAP", "REVIEW") and not r["flags"] and r["score"] and r["verdict"]
    ]
    sweep = []
    for step in range(70, 100):
        t = step / 100
        picked = [ok for score, ok in judged if score >= t]
        sweep.append((t, len(picked), sum(picked)))
    return sweep


def suggest_threshold(sweep: list[tuple[float, int, int]]) -> float | None:
    """Lowest threshold whose would-be SWAPs were all correct."""
    for t, n, correct in sweep:
        if n and correct == n:
            return t
    return None


def evaluate(rows: list[dict]) -> str:
    for r in rows:
        r["verdict"] = (r.get("verdict") or "").strip().lower()
    unknown = sorted({r["verdict"] for r in rows} - VERDICTS - {""})
    by_action: dict[str, Counter] = {}
    for r in rows:
        by_action.setdefault(r["action"], Counter())[r["verdict"]] += 1

    swap, review, nomatch = (by_action.get(a, Counter()) for a in ("SWAP", "REVIEW", "NO_MATCH"))
    lines = [
        f"Rows: {len(rows)}  " + "  ".join(f"{a}={sum(c.values())}" for a, c in sorted(by_action.items())),
        f"SWAP precision: {_pct(swap['correct'], swap['correct'] + swap['wrong'] + swap['missed'])}"
        f"  (unjudged: {swap['']})",
        f"REVIEW actually correct: {_pct(review['correct'], review['correct'] + review['wrong'] + review['missed'])}"
        f"  (unjudged: {review['']})",
        f"NO_MATCH: {sum(nomatch.values())}, missed (a song exists): {nomatch['missed']}",
    ]
    if unknown:
        lines.append(f"Ignored unknown verdicts: {', '.join(unknown)}")

    misses = [r for r in rows if r["verdict"] == "missed"]
    if misses:
        lines.append("Misses:")
        lines += [f"  #{r['position']} [{r['action']}] {r['artist']} - {r['title']}" for r in misses]

    flag_stats: dict[str, Counter] = {}
    for r in rows:
        if r["action"] == "REVIEW" and r["verdict"]:
            for flag in filter(None, r["flags"].split(";")):
                flag_stats.setdefault(flag, Counter())[r["verdict"]] += 1
    if flag_stats:
        lines.append("REVIEW flags (correct / wrong / missed):")
        lines += [
            f"  {flag}: {c['correct']} / {c['wrong']} / {c['missed']}" for flag, c in sorted(flag_stats.items())
        ]

    sweep = threshold_sweep(rows)
    lines.append("Threshold sweep, unflagged rows (threshold: would SWAP, correct):")
    lines += [f"  {t:.2f}: {n}, {correct}" for t, n, correct in sweep if t in (0.70, 0.75, 0.80, 0.85, 0.88, 0.90, 0.92, 0.95)]
    suggested = suggest_threshold(sweep)
    lines.append(
        f"Suggested --min-score: {suggested:.2f} (lowest with no wrong SWAPs in this sample)"
        if suggested is not None
        else "Suggested --min-score: none; no threshold gave error-free SWAPs on this sample"
    )
    return "\n".join(lines)
