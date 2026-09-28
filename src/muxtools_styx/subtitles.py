from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from muxtools import (
    GJM_GANDHI_PRESET,
    ASSHeader,
    FontFile,
    ParsedFile,
    PathLike,
    SubFile,
    SubTrack,
    edit_style,
    gandhi_default,
    get_executable,
    get_workdir,
    run_commandline,
    warn,
)

from .metadata import FixedMetadata
from .selection import SelectedTrack, canonical_language, canonical_language_tag


def _replace_unknown_styles(subtitle: SubFile) -> None:
    document = subtitle._read_doc()
    known = {str(style.name) for style in document.styles}
    for line in document.events:
        if line.TYPE == "Dialogue" and str(line.style) not in known:
            line.style = "Default"
    subtitle._update_doc(document)


def _repair_layout_resolution(subtitle: SubFile) -> None:
    document = subtitle._read_doc()
    section: dict[str, Any] = document.sections["Script Info"]
    missing_x = not section.get(ASSHeader.LayoutResX.name)
    missing_y = not section.get(ASSHeader.LayoutResY.name)
    if not missing_x and not missing_y:
        return
    play_x = section.get(ASSHeader.PlayResX.name)
    play_y = section.get(ASSHeader.PlayResY.name)
    if (missing_x and not play_x) or (missing_y and not play_y):
        warn("Cannot repair LayoutRes because PlayRes is missing.", _repair_layout_resolution)
        return
    headers: list[tuple[ASSHeader, int]] = []
    if missing_x:
        assert play_x is not None
        headers.append((ASSHeader.LayoutResX, int(play_x)))
    if missing_y:
        assert play_y is not None
        headers.append((ASSHeader.LayoutResY, int(play_y)))
    subtitle.set_headers(*headers)


def _language_selected(selected: SelectedTrack, languages: tuple[str, ...]) -> bool:
    language = canonical_language(selected.track)
    wanted = {canonical_language_tag(item) for item in languages}
    return language in wanted or language.split("-", 1)[0] in wanted


def _extract_font_attachments(source: Path) -> list[PathLike]:
    parsed = ParsedFile.from_file(source, _extract_font_attachments)
    source_key = hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:12]
    destination = Path(get_workdir(), "styx-fonts", f"{source.stem}-{source_key}")
    fonts: list[PathLike] = []
    arguments = [get_executable("mkvextract"), str(source), "attachments"]
    attachments = parsed.raw_mkvmerge.attachments if parsed.raw_mkvmerge else []
    for attachment in attachments:
        filename = attachment.file_name
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".ttf", ".otf", ".ttc", ".otc"}:
            continue
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / f"{attachment.id}_{Path(filename).name}"
        arguments.append(f"{attachment.id}:{output}")
        fonts.append(output)
    if fonts and run_commandline(arguments, quiet=True):
        raise RuntimeError(f"failed to extract font attachments from {source}")
    return fonts


def transform_subtitles(
    selected: tuple[SelectedTrack, ...],
    languages: tuple[str, ...],
    *,
    title_for: Callable[[SelectedTrack], str],
    target_source: Path,
    donor_delay: int = 0,
    fixed: FixedMetadata | None = None,
) -> tuple[list[SubTrack], list[FontFile], set[tuple[Path, int]]]:
    tracks: list[SubTrack] = []
    fonts_by_path: dict[Path, FontFile] = {}
    transformed: set[tuple[Path, int]] = set()
    attachment_fonts: dict[Path, list[PathLike]] = {}

    for item in selected:
        if not _language_selected(item, languages):
            continue
        track = item.track
        if track.codec_name.casefold() != "ass":
            warn(f"Restyling is unsupported for {track.codec_name}; keeping subtitle track {track.relative_index} unchanged.", transform_subtitles)
            continue

        subtitle = SubFile.from_mkv(item.source_file, track.relative_index, preserve_delay=True)
        subtitle.unfuck_cr(
            alt_styles=["overlap", "subtitle-2"],
            dialogue_styles=["main", "default", "narrator", "narration", "subtitle", "bd dx"],
        ).purge_macrons()
        preset = [*GJM_GANDHI_PRESET, edit_style(gandhi_default, "Sign"), edit_style(gandhi_default, "Subtitle")]
        subtitle.restyle(preset, clean_after=False)
        _replace_unknown_styles(subtitle)
        subtitle.clean_styles()
        _repair_layout_resolution(subtitle)
        if item.source_file not in attachment_fonts:
            attachment_fonts[item.source_file] = _extract_font_attachments(item.source_file)
        source_fonts = attachment_fonts[item.source_file]
        for font in subtitle.collect_fonts(search_current_dir=False, additional_fonts=source_fonts):
            fonts_by_path[font.file.resolve()] = font
        language = track.language or "und"
        default = track.is_default
        forced = track.is_forced
        if fixed is not None:
            language, default, forced = fixed[(item.source_file, track.index)]
        output_track = subtitle.to_track(
            title_for(item),
            language,
            default,
            forced,
        )
        if item.source_file != target_source:
            output_track.delay += donor_delay
        tracks.append(output_track)
        transformed.add((item.source_file, track.index))

    return tracks, list(fonts_by_path.values()), transformed
