"""Track-title normalization and source provenance.

This module does not implement output filename tokens.  ``muxtools.Setup`` owns
that language; these helpers only produce readable titles for retained tracks.
"""

from __future__ import annotations

import re

from muxtools import TrackInfo
from muxtools.utils.language_util import standardize_tag

from .matching import SOURCE_NAMES, source_label
from .selection import SelectedTrack, cc_or_sdh_label, is_dubtitle, is_signs_or_forced

_IGNORED_SUBTITLE_SUFFIX_RE = re.compile(
    r"^(?:"
    r"honorifics"
    r"|(?:dub[\s-]+)?(?:sdh|cc|closed[\s-]?captions?)"
    r"|hearing[\s-]?impaired|hard[\s-]?of[\s-]?hearing|hoh"
    r"|dubtitles?|dub"
    r"|forced?|signs?(?:\s*(?:&|/|and)\s*songs?)?|songs?"
    r"|full(?:\s+subtitles?)?|dialogue"
    r")$",
    re.IGNORECASE,
)
_HONORIFICS_RE = re.compile(r"\bhonorifics\b", re.IGNORECASE)
_NO_HONORIFICS_RE = re.compile(r"\bno[\s-]+honorifics\b", re.IGNORECASE)
_TECHNICAL_NOTE_RE = re.compile(r"^ccc[\s-]+converted$", re.IGNORECASE)
_REGION_QUALIFIER_RE = re.compile(
    r"^(?:latin[\s-]?americ(?:a|an)|spain|european|brazil(?:ian)?|germany|simplified|traditional|us|uk)$",
    re.IGNORECASE,
)
_CANONICAL_SOURCES: dict[str, str] = {
    **{key.casefold(): value for key, value in SOURCE_NAMES.items()},
    **{value.casefold(): value for value in SOURCE_NAMES.values()},
}


def display_language(track: TrackInfo, *, treat_enm_as_english: bool = True) -> str:
    language = standardize_tag(track.sanitized_lang.to_tag(), display_language)[0]
    if language.language == "und":
        return "Unknown"
    if treat_enm_as_english and language.language == "enm":
        return "English"
    return language.display_name()


def _track_channels(track: TrackInfo) -> str | None:
    channels = track.raw_ffprobe.channels
    if not channels:
        return None
    layout = (track.raw_ffprobe.channel_layout or "").casefold().split(" ", 1)[0]
    if match := re.match(r"\d+\.\d+(?:\.\d+)?", layout):
        return match.group(0)
    return f"{channels - 1}.1" if "lfe" in layout else f"{channels}.0"


def _trailing_groups(title: str) -> list[str]:
    groups: list[str] = []
    remaining = title.rstrip()
    while True:
        match = re.search(r"(\[[^\]]*\]|\([^)]*\))\s*$", remaining)
        if match is None:
            break
        groups.insert(0, match.group(1))
        remaining = remaining[: match.start()].rstrip()
    return groups


def _subtitle_suffixes(title: str, display_lang: str) -> tuple[list[str], bool]:
    qualifier_match = re.search(r"\(([^)]+)\)\s*$", display_lang)
    lang_qualifier = qualifier_match.group(1).strip().casefold() if qualifier_match else None
    kept: list[str] = []
    has_provenance = False
    for group in _trailing_groups(title):
        inner = group[1:-1].strip()
        if not inner or _IGNORED_SUBTITLE_SUFFIX_RE.fullmatch(inner):
            continue
        if lang_qualifier is not None and (inner.casefold() == lang_qualifier or _REGION_QUALIFIER_RE.fullmatch(inner)):
            continue
        if canonical := _CANONICAL_SOURCES.get(inner.casefold()):
            has_provenance = True
            formatted = f"({canonical})"
            if formatted not in kept:
                kept.append(formatted)
            continue
        if _TECHNICAL_NOTE_RE.fullmatch(inner):
            kept.append(group)
            continue
        has_provenance = True
        kept.append(group)
    return kept, has_provenance


def normalize_audio_title(selected: SelectedTrack, *, treat_enm_as_english: bool = True) -> str:
    """Render ``language channels (source)`` for one selected audio track."""

    title = display_language(selected.track, treat_enm_as_english=treat_enm_as_english)
    channels = _track_channels(selected.track)
    if channels:
        title = f"{title} {channels}"
    source = source_label(selected.source_file, selected.supplemental_info)
    return f"{title} ({source})" if source else title


def normalize_subtitle_title(selected: SelectedTrack, *, treat_enm_as_english: bool = True) -> str:
    """Render a subtitle title while preserving local suffix provenance."""

    track = selected.track
    original = str(getattr(track, "title", None) or "")
    language_tag = standardize_tag(track.sanitized_lang.to_tag(), normalize_subtitle_title)[0]
    language_name = display_language(track, treat_enm_as_english=treat_enm_as_english)
    suffixes, has_provenance = _subtitle_suffixes(original, language_name)
    has_honorifics = (treat_enm_as_english and language_tag.language == "enm") or (
        bool(_HONORIFICS_RE.search(original)) and not _NO_HONORIFICS_RE.search(original)
    )

    role: str | None
    if is_signs_or_forced(track):
        role = "Signs/Songs"
    elif (accessibility := cc_or_sdh_label(track)) is not None:
        role = accessibility
    elif is_dubtitle(track):
        role = "Dubtitles"
    else:
        role = None

    title = f"{language_name} {role}" if role else language_name
    if has_honorifics:
        title = f"{title} (Honorifics)"
    if not has_provenance and (source := source_label(selected.source_file, selected.supplemental_info)):
        suffixes.append(f"({source})")
    if suffixes:
        title = f"{title} {' '.join(suffixes)}"
    return title


def normalized_track_title(selected: SelectedTrack, *, treat_enm_as_english: bool = True) -> str:
    """Normalize according to the selected track kind for muxtools adapters."""

    kind = getattr(getattr(selected, "track", None), "type", None)
    kind_name = str(getattr(kind, "name", kind)).casefold()
    if kind_name in {"sub", "subtitle", "subtitles"}:
        return normalize_subtitle_title(selected, treat_enm_as_english=treat_enm_as_english)
    return normalize_audio_title(selected, treat_enm_as_english=treat_enm_as_english)


__all__ = [
    "SOURCE_NAMES",
    "SelectedTrack",
    "display_language",
    "normalize_audio_title",
    "normalize_subtitle_title",
    "normalized_track_title",
    "source_label",
]
