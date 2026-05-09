from __future__ import annotations

from pathlib import Path

from muxtools import ParsedFile

from .models import EpisodeKey, SourceFile


def inspect_source(path: Path, episode: EpisodeKey | None = None) -> SourceFile:
    parsed = ParsedFile.from_file(path, caller=inspect_source, allow_mkvmerge_warning=False)
    container_title = parsed.container_info.tags.get("title")
    return SourceFile(
        path=path.resolve(),
        tracks=parsed.tracks,
        episode=episode,
        container_format=parsed.container_info.format_name,
        container_title=container_title,
        is_video_file=parsed.is_video_file,
    )
