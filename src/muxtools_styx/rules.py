from __future__ import annotations

from .models import SourceFile, track_bitrate, track_language


def is_sign_like_subtitle(track: object) -> bool:
    title = (getattr(track, "title", None) or "").casefold()
    contains_marker = any(token in title for token in ("sign", "song", "force"))
    return (getattr(track, "is_forced", False) and not getattr(track, "is_default", False)) or contains_marker


def choose_donor_audio_tracks(donor: SourceFile, target: SourceFile) -> list[object]:
    target_languages = {track_language(track) for track in target.audio_tracks}
    return [
        track
        for track in donor.audio_tracks
        if track_language(track) is None or track_language(track) not in target_languages
    ]


def choose_donor_sign_subtitles(donor: SourceFile, preferred_languages: set[str | None]) -> list[object]:
    return [
        track
        for track in donor.subtitle_tracks
        if track_language(track) in preferred_languages and is_sign_like_subtitle(track)
    ]


def choose_donor_subtitles_missing_languages(donor: SourceFile, target: SourceFile) -> list[object]:
    target_languages = {track_language(track) for track in target.subtitle_tracks}
    return [
        track
        for track in donor.subtitle_tracks
        if track_language(track) is None or track_language(track) not in target_languages
    ]


def choose_best_japanese_audio(*sources: SourceFile) -> tuple[SourceFile, object] | None:
    candidates = [
        (source, track)
        for source in sources
        for track in source.audio_tracks
        if track_language(track) == "ja"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (track_bitrate(item[1]) or 0, getattr(item[1], "index", 0)))
