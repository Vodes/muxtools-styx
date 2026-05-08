from __future__ import annotations

from .models import SourceFile, TrackInfo

def is_sign_like_subtitle(track: TrackInfo) -> bool:
    title = (track.title or "").casefold()
    contains_marker = any(token in title for token in ("sign", "song", "force"))
    return (track.is_forced and not track.is_default) or contains_marker


def choose_donor_audio_tracks(donor: SourceFile, target: SourceFile) -> list[TrackInfo]:
    target_languages = {track.language for track in target.audio_tracks}
    return [
        track
        for track in donor.audio_tracks
        if track.language is None or track.language not in target_languages
    ]


def choose_donor_sign_subtitles(donor: SourceFile, preferred_languages: set[str | None]) -> list[TrackInfo]:
    return [
        track
        for track in donor.subtitle_tracks
        if track.language in preferred_languages and is_sign_like_subtitle(track)
    ]


def choose_best_japanese_audio(*sources: SourceFile) -> tuple[SourceFile, TrackInfo] | None:
    candidates = [
        (source, track)
        for source in sources
        for track in source.audio_tracks
        if track.language == "ja"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[1].bit_rate or 0, item[1].index))
