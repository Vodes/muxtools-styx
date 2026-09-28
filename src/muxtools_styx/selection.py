from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from muxtools import ParsedFile, TrackInfo, TrackType
from muxtools.utils.language_util import standardize_tag

from .audio import choose_best_japanese

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class TrackOptions:
    keep_video: bool = False
    keep_audio: bool = False
    fill_audio: bool = False
    best_audio: bool = False
    keep_subs: bool = False
    keep_subs_missing_languages: bool = False
    keep_non_english: bool = False
    discard_new_subs: bool = False
    remove_unnecessary: bool = False
    audio_languages: tuple[str, ...] = ("ja", "en", "de")
    sub_languages: tuple[str, ...] = ("en", "de")


@dataclass(frozen=True)
class TransformOptions:
    restyle_subs: bool = False
    restyle_languages: tuple[str, ...] = ("en", "de")
    fix_tags: bool = False
    normalize_track_names: bool = False
    tpp: bool = False


@dataclass(frozen=True)
class SyncOptions:
    audio_sync: int = 0
    sub_sync: int = 0


@dataclass(frozen=True)
class MuxOptions:
    tracks: TrackOptions = field(default_factory=TrackOptions)
    transforms: TransformOptions = field(default_factory=TransformOptions)
    sync: SyncOptions = field(default_factory=SyncOptions)


@dataclass(frozen=True)
class SelectedTrack:
    track: TrackInfo
    source_file: Path


@dataclass(frozen=True)
class Selection:
    video: tuple[SelectedTrack, ...]
    audio: tuple[SelectedTrack, ...]
    subtitles: tuple[SelectedTrack, ...]
    chapter_source: Path


def canonical_language(track: TrackInfo) -> str:
    """Return muxtools' normalized language identity, retaining variants."""
    return standardize_tag(track.sanitized_lang.to_tag(), canonical_language)[1].casefold()


def canonical_language_tag(language: str) -> str:
    return standardize_tag(language, canonical_language_tag)[1].casefold()


def is_signs_or_forced(track: TrackInfo) -> bool:
    title = (track.title or "").casefold()
    return track.is_forced or any(word in title for word in ("sign", "song", "forced"))


def _select(parsed: ParsedFile, kind: TrackType) -> list[SelectedTrack]:
    return [SelectedTrack(track, parsed.source) for track in parsed.find_tracks(type=kind)]


def _dedupe(tracks: Iterable[SelectedTrack]) -> list[SelectedTrack]:
    result: list[SelectedTrack] = []
    seen: set[tuple[Path, int]] = set()
    for selected in tracks:
        key = (selected.source_file, selected.track.index)
        if key not in seen:
            seen.add(key)
            result.append(selected)
    return result


def _matches_language(track: SelectedTrack, languages: set[str]) -> bool:
    language = canonical_language(track.track)
    base = language.split("-", 1)[0]
    return language in languages or base in languages


def validate_options(options: MuxOptions, donor: Path | None) -> None:
    tracks = options.tracks
    if tracks.keep_audio and tracks.fill_audio:
        raise ValueError("keep_audio and fill_audio cannot be used together")
    donor_flags = (
        tracks.keep_video,
        tracks.keep_audio,
        tracks.fill_audio,
        tracks.keep_subs,
        tracks.keep_subs_missing_languages,
        tracks.keep_non_english,
        options.sync.audio_sync != 0,
        options.sync.sub_sync != 0,
    )
    if donor is None and any(donor_flags):
        raise ValueError("the selected policy requires a donor file")


def select_tracks(target: ParsedFile, donor: ParsedFile | None, options: MuxOptions) -> Selection:
    validate_options(options, donor.source if donor else None)
    policy = options.tracks

    target_video = _select(target, TrackType.VIDEO)
    target_audio = _select(target, TrackType.AUDIO)
    target_subs = [] if policy.discard_new_subs else _select(target, TrackType.SUB)
    if len(target_video) != 1:
        raise ValueError(f"target must contain exactly one video track: {target.source}")
    if not target_audio:
        raise ValueError(f"target has no audio track: {target.source}")

    video = target_video
    audio = target_audio
    subtitles = target_subs

    if donor is not None:
        donor_video = _select(donor, TrackType.VIDEO)
        donor_audio = _select(donor, TrackType.AUDIO)
        donor_subs = _select(donor, TrackType.SUB)

        if policy.keep_video:
            if len(donor_video) != 1:
                raise ValueError(f"donor must contain exactly one video track: {donor.source}")
            video = donor_video

        if policy.keep_audio:
            audio = _dedupe([*audio, *donor_audio])
        elif policy.fill_audio:
            present = {canonical_language(item.track) for item in audio}
            introduced = {canonical_language(item.track) for item in donor_audio} - present
            audio.extend(item for item in donor_audio if canonical_language(item.track) in introduced)
            subtitles.extend(item for item in donor_subs if canonical_language(item.track) in introduced and is_signs_or_forced(item.track))

        donor_sub_selection: list[SelectedTrack] = []
        if policy.keep_subs:
            donor_sub_selection = donor_subs
        else:
            if policy.keep_subs_missing_languages:
                present_subs = {canonical_language(item.track) for item in subtitles}
                donor_sub_selection.extend(item for item in donor_subs if canonical_language(item.track) not in present_subs)
            if policy.keep_non_english:
                donor_sub_selection.extend(item for item in donor_subs if canonical_language(item.track).split("-", 1)[0] != "en")
        subtitles = _dedupe([*subtitles, *donor_sub_selection])

    if policy.best_audio:
        japanese = [item for item in audio if canonical_language(item.track).split("-", 1)[0] == "ja"]
        if japanese:
            winner = choose_best_japanese(japanese)
            audio = [item for item in audio if item not in japanese or item == winner]

    if policy.remove_unnecessary:
        audio_languages = {canonical_language_tag(language) for language in policy.audio_languages}
        sub_languages = {canonical_language_tag(language) for language in policy.sub_languages}
        audio = [item for item in audio if _matches_language(item, audio_languages)]
        subtitles = [item for item in subtitles if _matches_language(item, sub_languages)]

    if not video:
        raise ValueError("selection removed every video track")
    if not audio:
        raise ValueError("selection removed every audio track")

    return Selection(tuple(video), tuple(audio), tuple(subtitles), target.source)
