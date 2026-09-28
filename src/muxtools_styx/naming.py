"""Track-title normalization and source provenance.

This module does not implement output filename tokens.  ``muxtools.Setup`` owns
that language; these helpers only produce readable titles for retained tracks.
"""

from __future__ import annotations

import re

from muxtools import TrackInfo
from muxtools.utils.language_util import standardize_tag

from .matching import SOURCE_NAMES, source_label
from .selection import SelectedTrack


def display_language(track: TrackInfo) -> str:
    language = standardize_tag(track.sanitized_lang.to_tag(), display_language)[0]
    if language.language == "und":
        return "Unknown"
    return language.display_name()


def _track_channels(track: TrackInfo) -> str | None:
    channels = track.raw_ffprobe.channels
    if not channels:
        return None
    layout = (track.raw_ffprobe.channel_layout or "").casefold().split(" ", 1)[0]
    if match := re.match(r"\d+\.\d+(?:\.\d+)?", layout):
        return match.group(0)
    return f"{channels - 1}.1" if "lfe" in layout else f"{channels}.0"


def _suffixes_without_honorifics(title: str | None) -> list[str]:
    if not title:
        return []
    suffixes: list[str] = []
    remaining = title.rstrip()
    while True:
        match = re.search(r"(\[[^\]]*\]|\([^)]*\))\s*$", remaining)
        if match is None:
            break
        group = match.group(1)
        remaining = remaining[: match.start()].rstrip()
        if group[1:-1].strip().casefold() != "honorifics":
            suffixes.insert(0, group)
    return suffixes


def normalize_audio_title(selected: SelectedTrack) -> str:
    """Render ``language channels (source)`` for one selected audio track."""

    title = display_language(selected.track)
    channels = _track_channels(selected.track)
    if channels:
        title = f"{title} {channels}"
    source = source_label(selected.source_file)
    return f"{title} ({source})" if source else title


def normalize_subtitle_title(selected: SelectedTrack) -> str:
    """Render a subtitle title while preserving local suffix provenance."""

    track = selected.track
    original = getattr(track, "title", None)
    original = str(original) if original else ""
    suffixes = _suffixes_without_honorifics(original)
    local_provenance = " ".join(suffixes)
    base_without_groups = re.sub(r"(?:\[[^\]]*\]|\([^)]*\))\s*$", "", original).strip() if original else ""
    is_signs = (
        bool(re.search(r"\b(signs?|songs?|forced?)\b", base_without_groups, re.IGNORECASE))
        or bool(getattr(track, "is_forced", False))
        or str(getattr(track, "forced", "")).casefold() == "yes"
    )
    title = f"{display_language(track)} Signs/Songs" if is_signs else display_language(track)

    if local_provenance:
        return f"{title} {local_provenance}"
    source = source_label(selected.source_file)
    return f"{title} ({source})" if source else title


def normalized_track_title(selected: SelectedTrack) -> str:
    """Normalize according to the selected track kind for muxtools adapters."""

    kind = getattr(getattr(selected, "track", None), "type", None)
    kind_name = str(getattr(kind, "name", kind)).casefold()
    return normalize_subtitle_title(selected) if kind_name in {"sub", "subtitle", "subtitles"} else normalize_audio_title(selected)


__all__ = [
    "SOURCE_NAMES",
    "SelectedTrack",
    "display_language",
    "normalize_audio_title",
    "normalize_subtitle_title",
    "normalized_track_title",
    "source_label",
]
