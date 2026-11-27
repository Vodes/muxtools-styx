from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from langcodes import Language
from muxtools import ParsedFile, TrackInfo, TrackType, warn
from muxtools.utils.language_util import standardize_tag

from .audio import choose_best_japanese

if TYPE_CHECKING:
    from collections.abc import Iterable

_SIGNS_FORCED_RE = re.compile(r"\b(?:signs?|songs?|forced?)\b", re.IGNORECASE)
_SDH_TITLE_RE = re.compile(r"(?<![a-z0-9])sdh(?![a-z0-9])", re.IGNORECASE)
_CC_TITLE_RE = re.compile(r"(?<![a-z0-9])(?:cc|closed[\s-]?captions?)(?![a-z0-9])", re.IGNORECASE)
_HI_TITLE_RE = re.compile(
    r"(?<![a-z0-9])(?:hearing[\s-]?impaired|hard[\s-]?of[\s-]?hearing|hoh)(?![a-z0-9])",
    re.IGNORECASE,
)
_DUBTITLE_TITLE_RE = re.compile(r"(?<![a-z0-9])(?:dubtitles?|dub)(?![a-z0-9])", re.IGNORECASE)


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
    treat_enm_as_english: bool = True


@dataclass(frozen=True)
class SelectedTrack:
    track: TrackInfo
    source_file: Path
    supplemental_info: str | None = None


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
    title = str(getattr(track, "title", None) or "")
    return bool(getattr(track, "is_forced", False)) or str(getattr(track, "forced", "")).casefold() == "yes" or bool(_SIGNS_FORCED_RE.search(title))


def mkvmerge_track_id(track: TrackInfo) -> int:
    raw_id = getattr(getattr(track, "raw_mkvmerge", None), "id", None)
    return int(raw_id) if raw_id is not None else track.index


def _disposition_flag(track: TrackInfo, name: str) -> bool:
    raw_ffprobe = getattr(track, "raw_ffprobe", None)
    disposition = getattr(raw_ffprobe, "disposition", None)
    if disposition is None:
        return False
    if isinstance(disposition, Mapping):
        return bool(disposition.get(name, 0))
    return bool(getattr(disposition, name, 0))


def _is_attached_pic(track: TrackInfo) -> bool:
    return _disposition_flag(track, "attached_pic")


def has_hearing_impaired_flag(track: TrackInfo) -> bool:
    raw_mkvmerge = getattr(track, "raw_mkvmerge", None)
    properties = getattr(raw_mkvmerge, "properties", None)
    if getattr(properties, "flag_hearing_impaired", None) is True:
        return True
    if _disposition_flag(track, "hearing_impaired"):
        return True
    return bool(getattr(track, "is_hearing_impaired", False))


def _has_captions_disposition(track: TrackInfo) -> bool:
    return _disposition_flag(track, "captions")


def cc_or_sdh_label(track: TrackInfo) -> Literal["CC", "SDH"] | None:
    title = str(getattr(track, "title", None) or "")
    if _SDH_TITLE_RE.search(title):
        return "SDH"
    if _CC_TITLE_RE.search(title) or _has_captions_disposition(track):
        return "CC"
    if _HI_TITLE_RE.search(title) or has_hearing_impaired_flag(track):
        return "SDH"
    return None


def is_cc_or_sdh(track: TrackInfo) -> bool:
    return cc_or_sdh_label(track) is not None


def is_dubtitle(track: TrackInfo) -> bool:
    if is_signs_or_forced(track) or is_cc_or_sdh(track):
        return False
    title = str(getattr(track, "title", None) or "")
    return bool(_DUBTITLE_TITLE_RE.search(title))


def is_audio_companion_subtitle(track: TrackInfo) -> bool:
    return is_signs_or_forced(track) or is_cc_or_sdh(track) or is_dubtitle(track)


def _effective_language(language: Language, *, treat_enm_as_english: bool = True) -> Language:
    if treat_enm_as_english and language.language == "enm":
        return Language.get("en")
    return language


def languages_match(query: Language, candidate: Language, *, allow_broader: bool = False, treat_enm_as_english: bool = True) -> bool:
    query = _effective_language(query, treat_enm_as_english=treat_enm_as_english)
    candidate = _effective_language(candidate, treat_enm_as_english=treat_enm_as_english)
    if query == candidate:
        return True
    if not query.language or query.language != candidate.language:
        return False
    query_tag = query.to_tag()
    candidate_tag = candidate.to_tag()
    if query_tag in candidate.broader_tags():
        return True
    if candidate_tag in query.broader_tags():
        return allow_broader
    return query.distance(candidate) == 0


def languages_equivalent(first: str, second: str, *, treat_enm_as_english: bool = True) -> bool:
    return languages_match(Language.get(first), Language.get(second), allow_broader=True, treat_enm_as_english=treat_enm_as_english)


def canonical_languages(languages: Iterable[str]) -> tuple[Language, ...]:
    return tuple(Language.get(canonical_language_tag(language)) for language in languages)


def matches_any_language(track: TrackInfo, languages: Iterable[Language], *, allow_broader: bool = False, treat_enm_as_english: bool = True) -> bool:
    candidate = Language.get(canonical_language(track))
    return any(languages_match(query, candidate, allow_broader=allow_broader, treat_enm_as_english=treat_enm_as_english) for query in languages)


def _language_matches_audio(track_language: str, audio_languages: set[str], *, treat_enm_as_english: bool = True) -> bool:
    if track_language in audio_languages:
        return True
    track_lang = Language.get(track_language)
    return any(
        languages_match(Language.get(audio_language), track_lang, allow_broader=True, treat_enm_as_english=treat_enm_as_english)
        for audio_language in audio_languages
    )


def _is_english(track: TrackInfo, *, treat_enm_as_english: bool = True) -> bool:
    base = canonical_language(track).split("-", 1)[0]
    return base == "en" or (treat_enm_as_english and base == "enm")


def _select(parsed: ParsedFile, kind: TrackType, supplemental_info: str | None) -> list[SelectedTrack]:
    return [
        SelectedTrack(track, parsed.source, supplemental_info)
        for track in parsed.find_tracks(type=kind)
        if kind != TrackType.VIDEO or not _is_attached_pic(track)
    ]


def _dedupe(tracks: Iterable[SelectedTrack]) -> list[SelectedTrack]:
    result: list[SelectedTrack] = []
    seen: set[tuple[Path, int]] = set()
    for selected in tracks:
        key = (selected.source_file, selected.track.index)
        if key not in seen:
            seen.add(key)
            result.append(selected)
    return result


def validate_options(
    options: MuxOptions,
    donor: Path | None,
    *,
    target: Path | None = None,
    donor_supplemental_info: str | None = None,
    warn_unused: bool = True,
) -> None:
    tracks = options.tracks
    if tracks.keep_audio and tracks.fill_audio:
        raise ValueError("keep_audio and fill_audio cannot be used together")
    donor_required_flags = (
        tracks.keep_video,
        tracks.keep_audio,
        tracks.fill_audio,
        tracks.keep_subs,
        tracks.keep_subs_missing_languages,
        tracks.keep_non_english,
        options.sync.audio_sync != 0,
        options.sync.sub_sync != 0,
    )
    if donor is None and any(donor_required_flags):
        raise ValueError("the selected policy requires a donor file")
    if donor is not None and target is not None and donor.expanduser().resolve() == target.expanduser().resolve():
        raise ValueError("donor file cannot be the same as target file")
    if warn_unused and donor is None and donor_supplemental_info:
        warn("donor_supplemental_info is ignored without a donor file.", validate_options)
    if warn_unused and donor is not None and not (any(donor_required_flags) or tracks.best_audio):
        warn("A donor file was provided, but no donor-using policy is active; donor will be ignored.", validate_options)


def select_tracks(
    target: ParsedFile,
    donor: ParsedFile | None,
    options: MuxOptions,
    *,
    target_supplemental_info: str | None = None,
    donor_supplemental_info: str | None = None,
    warn_unused: bool = True,
) -> Selection:
    validate_options(
        options,
        donor.source if donor else None,
        target=target.source,
        donor_supplemental_info=donor_supplemental_info,
        warn_unused=warn_unused,
    )
    policy = options.tracks
    enm = options.treat_enm_as_english

    target_video = _select(target, TrackType.VIDEO, target_supplemental_info)
    target_audio = _select(target, TrackType.AUDIO, target_supplemental_info)
    target_subs = [] if policy.discard_new_subs else _select(target, TrackType.SUB, target_supplemental_info)
    if not policy.keep_video and len(target_video) != 1:
        raise ValueError(f"target must contain exactly one video track: {target.source}")
    donor_can_supply_audio = donor is not None and (policy.keep_audio or policy.fill_audio or policy.best_audio)
    if not target_audio and not donor_can_supply_audio:
        raise ValueError(f"target has no audio track: {target.source}")

    video = target_video
    audio = target_audio
    subtitles = target_subs
    donor_audio: list[SelectedTrack] = []
    fill_companion_keys: set[tuple[Path, int]] = set()

    if donor is not None:
        donor_video = _select(donor, TrackType.VIDEO, donor_supplemental_info)
        donor_audio = _select(donor, TrackType.AUDIO, donor_supplemental_info)
        donor_subs = _select(donor, TrackType.SUB, donor_supplemental_info)

        if policy.keep_video:
            if len(donor_video) != 1:
                raise ValueError(f"donor must contain exactly one video track: {donor.source}")
            video = donor_video

        introduced_langs: set[str] = set()
        if policy.keep_audio:
            audio = _dedupe([*audio, *donor_audio])
        elif policy.fill_audio:
            present_audio = [canonical_language(item.track) for item in audio]
            introduced_audio = [
                item
                for item in donor_audio
                if not any(languages_equivalent(canonical_language(item.track), existing, treat_enm_as_english=enm) for existing in present_audio)
            ]
            introduced_langs = {canonical_language(item.track) for item in introduced_audio}
            audio.extend(introduced_audio)

        if policy.keep_subs:
            donor_sub_selection = list(donor_subs)
        else:
            present_any_subs = [canonical_language(item.track) for item in subtitles]
            present_full_subs = [canonical_language(item.track) for item in subtitles if not is_audio_companion_subtitle(item.track)]
            donor_sub_selection = []
            for item in donor_subs:
                lang = canonical_language(item.track)
                is_companion = is_audio_companion_subtitle(item.track)
                take_for_fill = policy.fill_audio and is_companion and _language_matches_audio(lang, introduced_langs, treat_enm_as_english=enm)
                existing_for_missing = present_any_subs if is_companion else present_full_subs
                take_for_missing = policy.keep_subs_missing_languages and not any(
                    languages_equivalent(lang, existing, treat_enm_as_english=enm) for existing in existing_for_missing
                )
                take_for_non_en = policy.keep_non_english and not _is_english(item.track, treat_enm_as_english=enm)
                if take_for_fill:
                    fill_companion_keys.add((item.source_file, item.track.index))
                if take_for_fill or take_for_missing or take_for_non_en:
                    donor_sub_selection.append(item)
        subtitles = _dedupe([*subtitles, *donor_sub_selection])

    if policy.best_audio:
        japanese = [item for item in audio if canonical_language(item.track).split("-", 1)[0] == "ja"]
        if donor is not None:
            donor_japanese = [item for item in donor_audio if canonical_language(item.track).split("-", 1)[0] == "ja"]
            japanese = _dedupe([*japanese, *donor_japanese])
        if japanese:
            winner = choose_best_japanese(japanese)
            existing_ja = [item for item in audio if canonical_language(item.track).split("-", 1)[0] == "ja"]
            if existing_ja:
                first_index = audio.index(existing_ja[0])
                audio = [item for item in audio if item not in existing_ja]
                audio.insert(first_index, winner)
            else:
                audio.append(winner)

    if policy.remove_unnecessary:
        audio_languages = canonical_languages(policy.audio_languages)
        sub_languages = canonical_languages(policy.sub_languages)
        audio = [item for item in audio if matches_any_language(item.track, audio_languages, treat_enm_as_english=enm)]
        kept_audio_languages = {canonical_language(item.track) for item in audio}
        subtitles = [
            item
            for item in subtitles
            if (
                _language_matches_audio(canonical_language(item.track), kept_audio_languages, treat_enm_as_english=enm)
                if is_audio_companion_subtitle(item.track)
                else matches_any_language(item.track, sub_languages, treat_enm_as_english=enm)
            )
        ]

    if not video:
        raise ValueError("selection removed every video track")
    if not audio:
        raise ValueError("selection removed every audio track")

    if donor is not None:
        if options.sync.audio_sync != 0 and not any(item.source_file == donor.source for item in audio):
            warn("audio_sync was set, but no donor audio track was selected.", select_tracks)
        if options.sync.sub_sync != 0 and not any(item.source_file == donor.source for item in subtitles):
            warn("sub_sync was set, but no donor subtitle track was selected.", select_tracks)
        if (
            options.sync.audio_sync != 0
            and options.sync.sub_sync == 0
            and any((item.source_file, item.track.index) in fill_companion_keys for item in subtitles)
        ):
            warn("fill_audio imported donor companion subtitles while audio_sync is non-zero and sub_sync is 0.", select_tracks)

    return Selection(tuple(video), tuple(audio), tuple(subtitles), target.source)
