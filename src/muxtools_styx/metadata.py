from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from muxtools import TrackType

from .selection import SelectedTrack, canonical_language, is_signs_or_forced

FixedMetadata = dict[tuple[Path, int], tuple[str, bool, bool]]


def fixed_metadata(tracks: tuple[SelectedTrack, ...]) -> FixedMetadata:
    result: FixedMetadata = {}
    default_audio_seen: set[str] = set()
    default_sub_seen: set[str] = set()
    for selected in tracks:
        track = selected.track
        language = canonical_language(track)
        if track.type == TrackType.AUDIO:
            default = language not in default_audio_seen
            default_audio_seen.add(language)
            forced = False
        elif track.type == TrackType.SUB:
            forced = is_signs_or_forced(track)
            default = not forced and language not in default_sub_seen
            if default:
                default_sub_seen.add(language)
        else:
            continue
        result[(selected.source_file, track.index)] = (language, default, forced)
    return result


def metadata_arguments(
    tracks: list[SelectedTrack],
    *,
    normalize_names: bool,
    fix_tags: bool,
    title_for: Callable[[SelectedTrack], str],
    fixed: FixedMetadata,
) -> list[str]:
    args: list[str] = []
    for selected in tracks:
        track = selected.track
        index = track.index
        if normalize_names:
            args.extend(("--track-name", f"{index}:{title_for(selected)}"))
        if not fix_tags:
            continue
        language, default, forced = fixed[(selected.source_file, track.index)]
        args.extend(("--language", f"{index}:{language}", "--no-track-tags"))
        args.extend(("--default-track-flag", f"{index}:{'yes' if default else 'no'}"))
        args.extend(("--forced-display-flag", f"{index}:{'yes' if forced else 'no'}"))
    return args
