from __future__ import annotations

from typing import TYPE_CHECKING

from muxtools import AudioFormat

from .matching import source_label

if TYPE_CHECKING:
    from muxtools import TrackInfo

    from .selection import SelectedTrack


def track_bitrate(track: TrackInfo) -> int | None:
    raw = track.raw_ffprobe
    value = getattr(raw, "bit_rate", None)
    if not value:
        tags = track.other_tags
        value = tags.get("BPS") or tags.get("BPS-eng")
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def audio_tier(selected: SelectedTrack) -> tuple[int, int] | None:
    """Return the Japanese audio preference tier, or None for unclassified codecs."""
    audio_format = selected.track.get_audio_format()
    bitrate = track_bitrate(selected.track)
    if audio_format is None:
        return None
    if not audio_format.is_lossy:
        return (5, 0)
    if audio_format in (AudioFormat.AAC, AudioFormat.AAC_XHE):
        if bitrate is None:
            return None
        if bitrate > 192_000:
            return (4, bitrate)
        if bitrate >= 176_000:
            return (3, bitrate)
        return (1, bitrate)
    if audio_format in (AudioFormat.EAC3, AudioFormat.EAC3_ATMOS):
        if source_label(selected.source_file, selected.supplemental_info) == "Amazon":
            return (2, bitrate or 0)
        return None
    return None


def choose_best_japanese(candidates: list[SelectedTrack]) -> SelectedTrack:
    if not candidates:
        raise ValueError("cannot choose from an empty audio candidate list")
    tiered = [(index, candidate, audio_tier(candidate)) for index, candidate in enumerate(candidates)]
    lossless = [(index, candidate, tier) for index, candidate, tier in tiered if tier is not None and tier[0] >= 5]
    if lossless:
        return max(lossless, key=lambda item: (*item[2], -item[0]))[1]
    if tiered[0][2] is None:
        return candidates[0]
    classified = [(index, candidate, tier) for index, candidate, tier in tiered if tier is not None]
    return max(classified, key=lambda item: (*item[2], -item[0]))[1]
