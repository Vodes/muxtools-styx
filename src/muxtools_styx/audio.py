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


def audio_tier(selected: SelectedTrack) -> tuple[int, int]:
    """Return the deliberately narrow Japanese web-audio preference tier."""
    audio_format = selected.track.get_audio_format()
    bitrate = track_bitrate(selected.track) or 0
    if audio_format in (AudioFormat.AAC, AudioFormat.AAC_XHE):
        if bitrate > 192_000:
            return (4, bitrate)
        if bitrate >= 176_000:
            return (3, bitrate)
        return (1, bitrate)
    if audio_format in (AudioFormat.EAC3, AudioFormat.EAC3_ATMOS):
        if source_label(selected.source_file, selected.supplemental_info) == "Amazon":
            return (2, bitrate)
        return (0, 0)
    return (0, 0)


def choose_best_japanese(candidates: list[SelectedTrack]) -> SelectedTrack:
    if not candidates:
        raise ValueError("cannot choose from an empty audio candidate list")
    return max(enumerate(candidates), key=lambda item: (*audio_tier(item[1]), -item[0]))[1]
