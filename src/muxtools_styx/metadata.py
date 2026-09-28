from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from muxtools import MKVPropEdit, TrackType

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


def edit_metadata_in_place(
    target: Path,
    tracks: tuple[SelectedTrack, ...],
    *,
    normalize_names: bool,
    fix_tags: bool,
    title: str | None = None,
) -> Path:
    from .naming import normalized_track_title

    fixed = fixed_metadata(tracks) if fix_tags else {}
    editor = MKVPropEdit(target)
    if title is not None:
        editor.info(title=title)
    type_order = {TrackType.VIDEO: 0, TrackType.AUDIO: 1, TrackType.SUB: 2}
    ordered_tracks = sorted(tracks, key=lambda item: (type_order.get(item.track.type, 3), item.track.relative_index))
    for selected in ordered_tracks:
        track = selected.track
        if track.type == TrackType.VIDEO:
            if fix_tags:
                editor.video_track(tags={})
            continue
        name = normalized_track_title(selected) if normalize_names else None
        if fix_tags:
            language, default, forced = fixed[(selected.source_file, track.index)]
        else:
            language, default, forced = None, None, None
        tags: dict[str, str] | None = {} if fix_tags else None

        if track.type == TrackType.AUDIO:
            editor.audio_track(name=name, language=language, default=default, forced=forced, tags=tags)
        elif track.type == TrackType.SUB:
            editor.sub_track(name=name, language=language, default=default, forced=forced, tags=tags)

    result, _ = editor.run()
    return result
