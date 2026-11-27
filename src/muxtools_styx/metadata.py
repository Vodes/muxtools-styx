from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from muxtools import MKVPropEdit, TrackType, get_setup_attr

from .selection import (
    SelectedTrack,
    canonical_language,
    is_cc_or_sdh,
    is_dubtitle,
    is_signs_or_forced,
    languages_equivalent,
    mkvmerge_track_id,
)


class FixedTrackMetadata(NamedTuple):
    language: str
    default: bool
    forced: bool
    hearing_impaired: bool = False


FixedMetadata = dict[tuple[Path, int], FixedTrackMetadata]


def fixed_metadata(tracks: tuple[SelectedTrack, ...], *, treat_enm_as_english: bool = True) -> FixedMetadata:
    result: FixedMetadata = {}
    default_audio_seen: list[str] = []
    default_sub_seen: list[str] = []
    for selected in tracks:
        track = selected.track
        language = canonical_language(track)
        if track.type == TrackType.AUDIO:
            default = not any(languages_equivalent(language, seen, treat_enm_as_english=treat_enm_as_english) for seen in default_audio_seen)
            if default:
                default_audio_seen.append(language)
            forced = False
            hearing_impaired = False
        elif track.type == TrackType.SUB:
            forced = is_signs_or_forced(track)
            hearing_impaired = is_cc_or_sdh(track)
            default = (
                not forced
                and not hearing_impaired
                and not is_dubtitle(track)
                and not any(languages_equivalent(language, seen, treat_enm_as_english=treat_enm_as_english) for seen in default_sub_seen)
            )
            if default:
                default_sub_seen.append(language)
        else:
            continue
        result[(selected.source_file, track.index)] = FixedTrackMetadata(language, default, forced, hearing_impaired)
    return result


def metadata_arguments(
    tracks: list[SelectedTrack],
    *,
    normalize_names: bool,
    fix_tags: bool,
    title_for: Callable[[SelectedTrack], str],
    fixed: FixedMetadata,
) -> list[str]:
    args: list[str] = ["--no-track-tags"] if fix_tags else []
    for selected in tracks:
        track = selected.track
        index = mkvmerge_track_id(track)
        if normalize_names:
            args.extend(("--track-name", f"{index}:{title_for(selected)}"))
        if not fix_tags:
            continue
        language, default, forced, hearing_impaired = fixed[(selected.source_file, track.index)]
        args.extend(("--language", f"{index}:{language}"))
        args.extend(("--default-track-flag", f"{index}:{'yes' if default else 'no'}"))
        args.extend(("--forced-display-flag", f"{index}:{'yes' if forced else 'no'}"))
        if track.type == TrackType.SUB:
            args.extend(("--hearing-impaired-flag", f"{index}:{'yes' if hearing_impaired else 'no'}"))
    return args


def edit_metadata_in_place(
    target: Path,
    tracks: tuple[SelectedTrack, ...],
    *,
    normalize_names: bool,
    fix_tags: bool,
    title: str | None = None,
    muxing_application: str | None = None,
    treat_enm_as_english: bool = True,
) -> Path:
    from .naming import normalized_track_title

    type_order = {TrackType.VIDEO: 0, TrackType.AUDIO: 1, TrackType.SUB: 2}
    ordered_tracks = tuple(sorted(tracks, key=lambda item: (type_order.get(item.track.type, 3), item.track.relative_index)))
    fixed = fixed_metadata(ordered_tracks, treat_enm_as_english=treat_enm_as_english) if fix_tags else {}
    editor = MKVPropEdit(target, tags={}) if fix_tags else MKVPropEdit(target)
    if get_setup_attr("skip_mux_branding", False):
        muxing_application = None
    elif muxing_application:
        from muxtools import __version__

        if " + muxtools v" not in muxing_application:
            muxing_application += f" + muxtools v{__version__}"
    effective_title = title or None
    if effective_title is not None or muxing_application:
        editor.info(title=effective_title, muxing_application=muxing_application)
    for selected in ordered_tracks:
        track = selected.track
        if track.type == TrackType.VIDEO:
            if fix_tags:
                editor.video_track(tags={})
            continue
        name = normalized_track_title(selected, treat_enm_as_english=treat_enm_as_english) if normalize_names else None
        if fix_tags:
            language, default, forced, hearing_impaired = fixed[(selected.source_file, track.index)]
        else:
            language, default, forced, hearing_impaired = None, None, None, None
        tags: dict[str, str] | None = {} if fix_tags else None

        if track.type == TrackType.AUDIO:
            editor.audio_track(name=name, language=language, default=default, forced=forced, tags=tags)
        elif track.type == TrackType.SUB:
            if fix_tags:
                editor.sub_track(
                    name=name,
                    language=language,
                    default=default,
                    forced=forced,
                    tags=tags,
                    flag_hearing_impaired=hearing_impaired,
                )
            else:
                editor.sub_track(name=name, language=language, default=default, forced=forced, tags=tags)

    result, _ = editor.run()
    if fix_tags:
        # Run after track-tag deletions because mkvpropedit executes CLI actions in order.
        result, _ = MKVPropEdit(result, track_statistics=True).run()
    return result
