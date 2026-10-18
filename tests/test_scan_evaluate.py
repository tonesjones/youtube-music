import pytest

from ytm_hygiene import scan
from ytm_hygiene.client import Throttle
from ytm_hygiene.evaluate import evaluate, suggest_threshold, threshold_sweep


class FakeClient:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search(self, query, filter=None):
        self.calls.append((query, filter))
        return self.results.get((query, filter), [])


def song(vid, title, artist, secs, rtype="song"):
    return {"resultType": rtype, "videoId": vid, "title": title, "artists": [{"name": artist, "id": None}],
            "duration_seconds": secs, "isExplicit": False, "isAvailable": True,
            "videoType": "MUSIC_VIDEO_TYPE_ATV"}


@pytest.fixture
def results(cases):
    return {
        ("The Weeknd Blinding Lights", "songs"): cases["exact_topic"]["candidates"][1:],
        ("Nobody Obscure Thing", "songs"): [],
        ("Nobody Obscure Thing", None): [
            song("art1", "Obscure Thing", "Nobody", 200, rtype="artist"),
            song("vid1", "Obscure Thing", "Nobody", 200, rtype="video"),
        ],
        ("Adele Hello", "songs"): cases["ugc_lyrics"]["candidates"],
    }


@pytest.fixture
def scanned(playlist, results):
    yt = FakeClient(results)
    rows = scan.scan_playlist(yt, playlist, "PLtest", throttle=Throttle(0), progress=lambda *_: None)
    return yt, rows


def test_atv_no_search(scanned):
    yt, rows = scanned
    assert rows[0]["action"] == "KEEP"
    assert all("Kept Song" not in q for q, _ in yt.calls)
    assert len(yt.calls) == 4  # weeknd, nobody x2, adele


def test_row_columns(scanned):
    _, rows = scanned
    assert len(rows) == 4
    for r in rows:
        assert list(r.keys()) == scan.COLUMNS
        assert set(r) == set(scan.COLUMNS)


def test_swap_row_url(scanned):
    _, rows = scanned
    r = rows[1]
    assert r["action"] == "SWAP"
    assert r["candidate_url"] == f"https://music.youtube.com/watch?v={r['candidate_videoId']}"
    assert r["candidate_videoId"] == "atv1"


def test_unfiltered_fallback_drops_non_songs(scanned):
    yt, rows = scanned
    nobody = [c for c in yt.calls if c[0] == "Nobody Obscure Thing"]
    assert nobody == [("Nobody Obscure Thing", "songs"), ("Nobody Obscure Thing", None)]
    assert rows[2]["action"] == "NO_MATCH"
    assert rows[2]["candidate_videoId"] == ""


def test_report_roundtrip(tmp_path, scanned):
    _, rows = scanned
    rows[1]["title"] = "米津玄師 - Lemon (Official Video)"
    path = tmp_path / "report.csv"
    scan.write_report(rows, path)
    back = scan.read_report(path)
    assert back[1]["title"] == "米津玄師 - Lemon (Official Video)"
    assert len(back) == len(rows)
    assert list(back[0].keys()) == scan.COLUMNS


def row(action, score="", flags="", verdict="", position=1, title="T", artist="A"):
    return {"action": action, "score": score, "flags": flags, "verdict": verdict,
            "position": position, "title": title, "artist": artist}


def test_evaluate_lines():
    rows = [
        row("SWAP", "0.95", verdict="correct", position=1),
        row("SWAP", "0.92", verdict="correct", position=2),
        row("SWAP", "0.91", verdict="wrong", position=3),
        row("REVIEW", "0.80", "duration", "correct", 4),
        row("REVIEW", "0.70", "version:live", "wrong", 5),
        row("NO_MATCH", "", "", "missed", 6, "Lost", "Artist"),
        row("NO_MATCH", "", "", "correct", 7),
    ]
    out = evaluate(rows)
    assert "SWAP precision: 2/3 (67%)" in out
    assert "REVIEW actually correct: 1/2 (50%)" in out
    assert "NO_MATCH: 2, missed (a song exists): 1" in out
    assert "#6 [NO_MATCH] Artist - Lost" in out


def test_suggest_threshold():
    rows = [row("REVIEW", "0.85", verdict="wrong")] * 2 + [
        row("SWAP", s, verdict="correct") for s in ("0.90", "0.93", "0.97")
    ]
    sweep = threshold_sweep(rows)
    assert suggest_threshold(sweep) == 0.86


def test_suggest_threshold_none():
    assert suggest_threshold(threshold_sweep([row("SWAP", "0.99", verdict="wrong")])) is None
