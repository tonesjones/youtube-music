"""Title cleanup, candidate scoring, and the SWAP / REVIEW / NO_MATCH / KEEP decision.

Pure functions over ytmusicapi dicts: no network access here.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

OMV = "MUSIC_VIDEO_TYPE_OMV"
UGC = "MUSIC_VIDEO_TYPE_UGC"
ATV = "MUSIC_VIDEO_TYPE_ATV"
OFFICIAL_SOURCE = "MUSIC_VIDEO_TYPE_OFFICIAL_SOURCE_MUSIC"
SEARCH_TYPES = {OMV, UGC, OFFICIAL_SOURCE}

DEFAULT_THRESHOLD = 0.90
MIN_USABLE = 0.60  # best candidate below this is reported as NO_MATCH
WEIGHTS = {"title": 0.50, "artist": 0.35, "duration": 0.15}

# Song length relative to the video: videos carry intros/outros, songs don't.
MAX_LONGER_S = 5
MAX_SHORTER_S = 15

_NOISE = (
    r"official\s+(?:4k\s+|hd\s+)?(?:music\s+|lyric\s+)?video|official\s+audio"
    r"|official\s+visuali[sz]er|lyric\s+video|lyrics?|audio|visuali[sz]er"
    r"|music\s+video|video\s+oficial|4k|hd|hq"
)
_BRACKETED_NOISE = re.compile(rf"[(\[]\s*(?:{_NOISE})(?:\s*[/|,&]\s*(?:{_NOISE}))*\s*[)\]]", re.I)
_TRAILING_NOISE = re.compile(rf"\s*[-|]\s*(?:{_NOISE})\s*$", re.I)
_BARE_QUALITY = re.compile(r"\b(?:4k|hd|hq)\b", re.I)
_FEAT_BRACKETED = re.compile(r"[(\[]\s*(?:feat\.?|ft\.?|featuring)\s[^)\]]*[)\]]", re.I)
_FEAT_INLINE = re.compile(r"\s(?:feat\.?|ft\.?|featuring)\s.*?(?=\s[-|]\s|[(\[]|$)", re.I)
_EMPTY_BRACKETS = re.compile(r"[(\[]\s*[)\]]")
_DASH = re.compile(r"\s+[-–—]\s+")

VERSION_TAGS = {
    "live": r"\blive\b|\ben vivo\b|\bao vivo\b",
    "remix": r"\bremix",
    "acoustic": r"\bacoustic|\bunplugged",
    "sped_up": r"\bsped[\s-]*up|\bspeed[\s-]*up|\bnightcore",
    "slowed": r"\bslowed|\breverb\b",
    "instrumental": r"\binstrumental",
    "karaoke": r"\bkaraoke",
    "cover": r"\bcover\b",
    "remaster": r"\bremaster",
}


@dataclass
class Scored:
    candidate: dict
    score: float
    duration_delta: int | None
    explicit_match: bool
    flags: list[str] = field(default_factory=list)


@dataclass
class Decision:
    action: str  # SWAP / REVIEW / NO_MATCH / KEEP
    best: Scored | None = None
    flags: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    """Casefold, strip accents and punctuation. Keeps non-Latin letters."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = unicodedata.normalize("NFKC", text).casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def normalize_artist(name: str) -> str:
    name = re.sub(r"\s*-\s*topic$", "", name, flags=re.I)
    name = re.sub(r"vevo$", "", name, flags=re.I)
    name = normalize(name)
    name = re.sub(r"^the\s+|\s+official$", "", name)
    return name.strip()


def clean_title(title: str) -> str:
    """Drop video noise like (Official Video), [4K], HD and feat. blocks."""
    title = _FEAT_BRACKETED.sub("", title)
    title = _FEAT_INLINE.sub("", title)
    title = _BRACKETED_NOISE.sub("", title)
    title = _TRAILING_NOISE.sub("", title)
    title = _BARE_QUALITY.sub("", title)
    title = _EMPTY_BRACKETS.sub("", title)
    return " ".join(title.split()).strip(" -|")


def version_tags(title: str) -> set[str]:
    lowered = title.casefold()
    return {tag for tag, pattern in VERSION_TAGS.items() if re.search(pattern, lowered)}


def split_artist_prefix(title: str, artist_names: list[str], force: bool) -> tuple[str | None, str]:
    """Split 'Artist - Title'. Only trusted when the left side looks like a known
    artist, or `force` (user uploads, whose channel is often not the artist)."""
    parts = _DASH.split(title, maxsplit=1)
    if len(parts) != 2:
        return None, title
    left, right = parts[0].strip(), parts[1].strip()
    if force or any(
        fuzz.token_set_ratio(normalize_artist(left), normalize_artist(n)) >= 85 for n in artist_names
    ):
        return left, right
    return None, title


def seconds(item: dict) -> int | None:
    if item.get("duration_seconds") is not None:
        return int(item["duration_seconds"])
    duration = item.get("duration")
    if not duration:
        return None
    try:
        total = 0
        for part in duration.split(":"):
            total = total * 60 + int(part)
        return total
    except ValueError:
        return None


@dataclass
class Original:
    """What we know about the playlist entry, parsed once."""

    track: dict
    artist_names: list[str]  # credited artists plus any parsed from the title
    title: str  # title with any 'Artist - ' prefix removed
    clean: str
    tags: set[str]

    @property
    def query(self) -> str:
        primary = self.artist_names[0] if self.artist_names else ""
        return f"{primary} {self.clean}".strip()


def parse_original(track: dict) -> Original:
    credited = [a["name"] for a in track.get("artists") or [] if a.get("name")]
    parsed_artist, title = split_artist_prefix(
        track.get("title") or "", credited, force=track.get("videoType") == UGC
    )
    names = ([parsed_artist] if parsed_artist else []) + credited
    return Original(track, names, title, clean_title(title), version_tags(title))


def title_score(a: str, b: str) -> float:
    # token_set alone scores "Love" vs "Love Story" as 100; averaging with
    # token_sort penalizes the extra words.
    a, b = normalize(a), normalize(b)
    return (fuzz.token_set_ratio(a, b) + fuzz.token_sort_ratio(a, b)) / 200


def artist_score(orig: Original, cand_artists: list[dict]) -> float:
    orig_ids = {a.get("id") for a in orig.track.get("artists") or []} - {None}
    cand_ids = {a.get("id") for a in cand_artists} - {None}
    if orig_ids & cand_ids:
        return 1.0
    ours = [n for n in map(normalize_artist, orig.artist_names) if n]
    theirs = [n for n in (normalize_artist(a.get("name") or "") for a in cand_artists) if n]
    return max((fuzz.token_set_ratio(a, b) for a in ours for b in theirs), default=0) / 100


def duration_score(video_s: int | None, song_s: int | None) -> tuple[float, int | None]:
    if video_s is None or song_s is None:
        return 0.5, None
    delta = song_s - video_s
    if -MAX_SHORTER_S <= delta <= MAX_LONGER_S:
        return 1.0, delta
    excess = delta - MAX_LONGER_S if delta > 0 else -MAX_SHORTER_S - delta
    return max(0.0, 1 - excess / 30), delta


def score_candidate(orig: Original, cand: dict, clean: bool = False) -> Scored:
    flags = []
    t = title_score(orig.clean, clean_title(cand.get("title") or ""))
    a = artist_score(orig, cand.get("artists") or [])
    d, delta = duration_score(seconds(orig.track), seconds(cand))
    if delta is None:
        flags.append("no_duration")
    elif d < 1.0:
        flags.append("duration")

    mismatched = orig.tags ^ version_tags(cand.get("title") or "")
    flags += [f"version:{tag}" for tag in sorted(mismatched)]

    orig_explicit = bool(orig.track.get("isExplicit"))
    cand_explicit = bool(cand.get("isExplicit"))
    if clean and cand_explicit:
        flags.append("explicit")
    elif not clean and orig_explicit and not cand_explicit:
        flags.append("clean_version")

    score = WEIGHTS["title"] * t + WEIGHTS["artist"] * a + WEIGHTS["duration"] * d
    return Scored(cand, round(score, 3), delta, orig_explicit == cand_explicit, flags)


def is_usable(track: dict, cand: dict) -> bool:
    return (
        cand.get("videoType") == ATV
        and cand.get("isAvailable") is True
        and bool(cand.get("videoId"))
        and cand.get("videoId") != track.get("videoId")
    )


def needs_search(track: dict) -> bool:
    return track.get("videoType") in SEARCH_TYPES


def decide(
    track: dict,
    candidates: list[dict],
    threshold: float = DEFAULT_THRESHOLD,
    clean: bool = False,
) -> Decision:
    vtype = track.get("videoType")
    if vtype == ATV:
        return Decision("KEEP")
    if vtype not in SEARCH_TYPES:
        return Decision("KEEP", flags=["unknown_type"])

    track_flags = []
    if vtype == OFFICIAL_SOURCE:
        track_flags.append("official_source")
    if not track.get("setVideoId"):
        track_flags.append("no_setVideoId")

    orig = parse_original(track)
    scored = [score_candidate(orig, c, clean) for c in candidates if is_usable(track, c)]
    if not scored:
        return Decision("NO_MATCH", flags=track_flags)

    # Highest score wins; on a tie prefer an unflagged candidate, then the
    # preferred explicit/clean variant.
    def rank(s: Scored):
        preferred = not s.candidate.get("isExplicit") if clean else bool(s.candidate.get("isExplicit"))
        return (s.score, not s.flags, preferred)

    best = max(scored, key=rank)
    flags = track_flags + best.flags
    if best.score < MIN_USABLE:
        return Decision("NO_MATCH", best, flags)
    action = "SWAP" if best.score >= threshold and not flags else "REVIEW"
    return Decision(action, best, flags)
