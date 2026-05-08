from __future__ import annotations

from pathlib import Path

from muxtools import ParsedFile, TrackType

from .models import EpisodeKey, SourceFile, TrackInfo

TRACK_KIND_MAP = {
    TrackType.VIDEO: "video",
    TrackType.AUDIO: "audio",
    TrackType.SUB: "subtitle",
    TrackType.ATTACHMENT: "attachment",
    TrackType.CHAPTERS: "chapters",
    TrackType.MKV: "mkv",
}


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def inspect_source(path: Path, episode: EpisodeKey | None = None) -> SourceFile:
    parsed = ParsedFile.from_file(path, caller=inspect_source, allow_mkvmerge_warning=False)
    container_title = parsed.container_info.tags.get("title")
    tracks = [
        TrackInfo(
            index=track.index,
            relative_index=track.relative_index,
            kind=TRACK_KIND_MAP.get(track.type, "unknown"),
            codec_name=track.codec_name,
            codec_long_name=track.codec_long_name,
            bit_rate=_coerce_int(track.raw_ffprobe.bit_rate),
            language=None if track.sanitized_lang.to_tag() == "und" else track.sanitized_lang.to_tag(),
            title=track.title,
            is_default=track.is_default,
            is_forced=track.is_forced,
            container_delay=track.container_delay,
        )
        for track in parsed.tracks
    ]
    return SourceFile(
        path=path.resolve(),
        tracks=tracks,
        episode=episode,
        container_format=parsed.container_info.format_name,
        container_title=container_title,
        is_video_file=parsed.is_video_file,
    )
