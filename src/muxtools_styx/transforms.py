from __future__ import annotations

import hashlib
from pathlib import Path

from muxtools import GJM_GANDHI_PRESET, FontFile, SubFile, edit_style, gandhi_default, warn

from .models import SubtitleTransform, TrackRef, track_language


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_fonts_for_subtitle(
    sub: SubFile,
    additional_fonts: list[Path] | None = None,
    embedded_font_hashes: set[str] | None = None,
) -> list[FontFile]:
    embedded_font_hashes = embedded_font_hashes or set()
    additional_fonts = additional_fonts or []
    font_attachments = list[FontFile]()
    seen_font_hashes = set[str]()

    try:
        collected = sub.collect_fonts(search_current_dir=False, additional_fonts=additional_fonts)
    except Exception as exc:
        raise RuntimeError(f"Failed to collect fonts for subtitle '{sub.file.name}'.") from exc

    for font in collected:
        font_hash = _file_hash(font.file.resolve())
        if font_hash in embedded_font_hashes:
            continue
        if font_hash in seen_font_hashes:
            continue
        seen_font_hashes.add(font_hash)
        font_attachments.append(font)

    return font_attachments


def _dedupe_font_attachments(font_attachments: list[FontFile]) -> list[FontFile]:
    unique = list[FontFile]()
    seen_font_hashes = set[str]()

    for font in font_attachments:
        font_hash = _file_hash(font.file.resolve())
        if font_hash in seen_font_hashes:
            continue
        seen_font_hashes.add(font_hash)
        unique.append(font)

    return unique


def build_subtitle_tracks(
    transforms: list[SubtitleTransform],
    passthrough_text_subtitles: list[TrackRef],
    additional_fonts: list[Path] | None = None,
    embedded_font_hashes: set[str] | None = None,
) -> tuple[list[object], list[FontFile]]:
    rebuilt_tracks = list[object]()
    font_attachments = list[FontFile]()
    embedded_font_hashes = embedded_font_hashes or set()
    additional_fonts = additional_fonts or []

    for transform in transforms:
        if transform.kind != "restyle":
            continue

        # mkvextract already yields subtitle files with effective timestamps applied,
        # so preserving the original container delay here would shift the track twice on remux.
        sub = SubFile.from_mkv(transform.source, transform.relative_index, preserve_delay=False)
        preset = GJM_GANDHI_PRESET.copy()
        preset.append(edit_style(gandhi_default, "Sign"))
        preset.append(edit_style(gandhi_default, "Subtitle"))
        preset.append(edit_style(gandhi_default, "Subtitle-3", fontsize=66))
        sub = sub.unfuck_cr(
            alt_styles=["overlap", "subtitle-2"],
            dialogue_styles=["main", "default", "narrator", "narration", "subtitle", "bd dx"],
        ).purge_macrons().restyle(preset)
        font_attachments.extend(_collect_fonts_for_subtitle(sub, additional_fonts, embedded_font_hashes))
        rebuilt_tracks.append(
            sub.to_track(
                transform.title or "",
                transform.language or "en",
                transform.is_default,
                transform.is_forced,
            )
        )

    for subtitle in passthrough_text_subtitles:
        sub = SubFile.from_mkv(subtitle.source, subtitle.track.relative_index, preserve_delay=False)
        try:
            font_attachments.extend(_collect_fonts_for_subtitle(sub, additional_fonts, embedded_font_hashes))
        except RuntimeError as exc:
            warn(f"{exc} Font collection was skipped for this unchanged subtitle track.", build_subtitle_tracks, 1)
        rebuilt_tracks.append(
            sub.to_track(
                getattr(subtitle.track, "title", None) or "",
                track_language(subtitle.track) or "en",
                getattr(subtitle.track, "is_default", False),
                getattr(subtitle.track, "is_forced", False),
            )
        )

    return rebuilt_tracks, _dedupe_font_attachments(font_attachments)
