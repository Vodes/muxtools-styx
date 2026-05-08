from __future__ import annotations

from pathlib import Path

from muxtools import MKVPropEdit, ParsedFile, TrackType


def is_sign_like_subtitle(track) -> bool:
    title = (track.title or "").casefold()
    return (track.is_forced and not track.is_default) or any(token in title for token in ("sign", "song", "force"))


def is_likely_full_subtitle(track) -> bool:
    language = _normalized_language(track)
    title = (track.title or "").casefold()
    contains_sign_marker = any(token in title for token in ("sign", "song", "force"))
    return language in {"en", "ja", None} and ((not track.is_forced) or track.is_default) and not contains_sign_marker


def apply_metadata_postprocess(path: Path, mkv_title: str | None = None, fix_tags: bool = False) -> Path:
    if not mkv_title and not fix_tags:
        return path

    parsed = ParsedFile.from_file(path, caller=apply_metadata_postprocess)
    editor = MKVPropEdit(path)

    if mkv_title:
        editor.info(title=mkv_title)

    if fix_tags:
        _apply_track_tag_fixes(editor, parsed)

    output, _ = editor.run()
    return output


def _apply_track_tag_fixes(editor: MKVPropEdit, parsed: ParsedFile) -> None:
    audio_tracks = parsed.find_tracks(type=TrackType.AUDIO)
    subtitle_tracks = parsed.find_tracks(type=TrackType.SUB)

    preferred_full_subs = [track for track in subtitle_tracks if _normalized_language(track) == "en" and is_likely_full_subtitle(track)]
    if not preferred_full_subs:
        preferred_full_subs = [track for track in subtitle_tracks if _normalized_language(track) in {"ja", None} and is_likely_full_subtitle(track)]

    preferred_full_ids = {track.relative_index for track in preferred_full_subs}
    sign_ids = {
        track.relative_index
        for track in subtitle_tracks
        if _normalized_language(track) != "ja" and is_sign_like_subtitle(track)
    }

    other_full_non_ja_ids = {
        track.relative_index
        for track in subtitle_tracks
        if _normalized_language(track) not in {"ja", "en"}
        and track.relative_index not in sign_ids
    }

    preferred_default_id = preferred_full_subs[0].relative_index if preferred_full_subs else None

    for _ in audio_tracks:
        editor.audio_track(default=True, forced=False)

    for track in subtitle_tracks:
        if track.relative_index in preferred_full_ids:
            editor.sub_track(language="en", default=track.relative_index == preferred_default_id, forced=False)
            continue
        if track.relative_index in sign_ids:
            editor.sub_track(default=False, forced=True)
            continue
        if track.relative_index in other_full_non_ja_ids:
            editor.sub_track(default=True, forced=False)
            continue
        editor.sub_track()


def _normalized_language(track) -> str | None:
    tag = track.sanitized_lang.to_tag()
    return None if tag == "und" else tag
