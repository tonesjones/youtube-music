import pytest

from ytm_hygiene.match import (
    clean_title, decide, normalize, parse_original, remixer, seconds, split_artist_prefix,
)


def run(cases, name, **kw):
    c = cases[name]
    return decide(c["track"], c["candidates"], **kw)


def test_exact_topic_swap(cases):
    d = run(cases, "exact_topic")
    assert d.action == "SWAP"
    assert d.best.candidate["videoId"] == "atv1"  # string-only duration candidate wins
    assert d.flags == []


def test_live_vs_studio_review(cases):
    d = run(cases, "live_vs_studio")
    assert d.action == "REVIEW"
    assert "version:live" in d.flags


def test_live_vs_live_no_flag(cases):
    d = run(cases, "live_vs_live")
    assert not any(f.startswith("version:") for f in d.flags)


def test_remix_review(cases):
    d = run(cases, "remix_only")
    assert d.action == "REVIEW"
    assert "version:remix" in d.flags


@pytest.mark.parametrize("name", ["unrelated", "only_omv_or_unavailable"])
def test_no_match(cases, name):
    assert run(cases, name).action == "NO_MATCH"


def test_empty_candidates(cases):
    d = run(cases, "empty")
    assert d.action == "NO_MATCH" and d.best is None


def test_featured_artists_swap(cases):
    assert run(cases, "featured").action == "SWAP"


def test_explicit_original_clean_only(cases):
    d = run(cases, "explicit_only_clean")
    assert d.action == "REVIEW"
    assert "clean_version" in d.flags


def test_explicit_prefers_explicit(cases):
    d = run(cases, "explicit_and_clean")
    assert d.best.candidate["videoId"] == "e6"
    assert d.action == "SWAP"


def test_clean_mode_picks_clean(cases):
    d = run(cases, "explicit_and_clean", clean=True)
    assert d.best.candidate["videoId"] == "c6"


def test_clean_mode_explicit_only_flags(cases):
    d = run(cases, "explicit_only_explicit", clean=True)
    assert "explicit" in d.flags


def test_clean_original_explicit_candidate_swap(cases):
    assert run(cases, "clean_orig_explicit_cand").action == "SWAP"


def test_long_intro_duration(cases):
    d = run(cases, "long_intro")
    assert d.action == "REVIEW"
    assert "duration" in d.flags
    assert d.best.duration_delta == -45


def test_duration_minus10_swap(cases):
    d = run(cases, "minus10")
    assert d.best.duration_delta == -10
    assert d.action == "SWAP"


def test_duration_plus6_omv_swap(cases):
    d = run(cases, "plus6")
    assert d.best.duration_delta == 6
    assert d.action == "SWAP"


def test_duration_plus6_ugc_flag(cases):
    assert "duration" in run(cases, "ugc_plus6").flags


def test_omv_song_longer_swap(cases):
    d = run(cases, "omv_song_longer")
    assert d.best.duration_delta == 69
    assert d.action == "SWAP"


def test_wrong_artist_flag(cases):
    d = run(cases, "wrong_artist_cover")
    assert d.action == "REVIEW"
    assert "artist" in d.flags


@pytest.mark.parametrize("name", ["remixer_mismatch", "remixer_unnamed"])
def test_remixer_mismatch_flag(cases, name):
    d = run(cases, name)
    assert d.action == "REVIEW"
    assert "version:remixer" in d.flags


def test_remixer_same_swap(cases):
    assert run(cases, "remixer_same").action == "SWAP"


def test_ugc_lyrics_parse_and_swap(cases):
    c = cases["ugc_lyrics"]
    assert parse_original(c["track"]).query == "Adele Hello"
    assert decide(c["track"], c["candidates"]).action == "SWAP"


def test_official_source_review(cases):
    d = run(cases, "official_source")
    assert d.action == "REVIEW"
    assert "official_source" in d.flags


def test_atv_keep(cases):
    assert run(cases, "atv_keep").action == "KEEP"


def test_missing_setvideoid(cases):
    d = run(cases, "no_setVideoId")
    assert d.action == "REVIEW"
    assert "no_setVideoId" in d.flags


def test_short_title_trap(cases):
    assert run(cases, "short_title_trap").action != "SWAP"


def test_japanese_swap(cases):
    assert run(cases, "japanese").action == "SWAP"
    assert run(cases, "japanese_title").action == "SWAP"


def test_korean_swap(cases):
    assert run(cases, "korean_title").action == "SWAP"


# ---- unit tests ----

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Song (Official Video)", "Song"),
        ("Song (Official Music Video)", "Song"),
        ("Song [4K]", "Song"),
        ("Song HD", "Song"),
        ("Song (Lyrics)", "Song"),
        ("Song (Audio)", "Song"),
        ("Song (Visualizer)", "Song"),
        ("Song | Official Audio", "Song"),
        ("Song (feat. Someone)", "Song"),
        ("Song ft. Someone", "Song"),
        ("Song (Remix)", "Song (Remix)"),
        ("Sweeterman (lyrics on screen)", "Sweeterman"),
        ("Sweeterman (CDQ/Explicit Version)", "Sweeterman"),
        ("Coffee Break [HD]", "Coffee Break"),
    ],
)
def test_clean_title(raw, expected):
    assert clean_title(raw) == expected


@pytest.mark.parametrize("text", ["米津玄師 Lemon", "방탄소년단 봄날", "打上花火"])
def test_normalize_keeps_non_latin(text):
    assert normalize(text) != ""
    assert normalize(clean_title(text)) == normalize(clean_title(text))
    assert normalize(text) == text.casefold()


def test_split_artist_prefix_not_forced():
    assert split_artist_prefix("Song - Live", ["Someone Else"], force=False) == (None, "Song - Live")


def test_split_artist_prefix_forced():
    assert split_artist_prefix("Adele - Hello", ["X"], force=True) == ("Adele", "Hello")


def test_seconds():
    assert seconds({"duration": "1:02:03"}) == 3723
    assert seconds({"duration": "3:45"}) == 225
    assert seconds({"duration_seconds": 10, "duration": "9:99"}) == 10
    assert seconds({}) is None


def test_remixer():
    assert remixer("Shiver (DEVANK REMIX)") == "devank"
    assert remixer("Waves (:DARREN Remix)") == "darren"
    assert remixer("Waves ( Remix)") == ""
    assert remixer("Stoner Remix!!!") == ""
