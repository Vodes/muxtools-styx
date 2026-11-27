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
from .selection import SelectedTrack, canonical_languages, is_cc_or_sdh, matches_any_language


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


def _disambiguate_extracted_sub(subtitle: SubFile, source: Path, track_index: int) -> None:
    sub_file = getattr(subtitle, "file", None)
    if not isinstance(sub_file, Path) or not sub_file.exists():
        return
    source_key = hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:12]
    unique = sub_file.with_name(f"{source.stem}-{source_key}_{track_index}{sub_file.suffix}")
    if unique != sub_file:
        sub_file.replace(unique)
        subtitle.file = unique


def _will_restyle(item: SelectedTrack, wanted_languages: tuple[Any, ...], *, treat_enm_as_english: bool) -> bool:
    return (
        matches_any_language(item.track, wanted_languages, treat_enm_as_english=treat_enm_as_english)
        and not is_cc_or_sdh(item.track)
        and item.track.codec_name.casefold() == "ass"
    )


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transform_subtitles(
    selected: tuple[SelectedTrack, ...],
    languages: tuple[str, ...],
    *,
    title_for: Callable[[SelectedTrack], str],
    target_source: Path,
    donor_delay: int = 0,
    fixed: FixedMetadata | None = None,
    treat_enm_as_english: bool = True,
) -> tuple[list[SubTrack], list[FontFile], set[tuple[Path, int]]]:
    tracks: list[SubTrack] = []
    fonts_by_key: dict[str, FontFile] = {}
    transformed: set[tuple[Path, int]] = set()
    attachment_fonts: dict[Path, list[PathLike]] = {}

    wanted_languages = canonical_languages(languages)
    planned_restyle = {
        (item.source_file, item.track.index) for item in selected if _will_restyle(item, wanted_languages, treat_enm_as_english=treat_enm_as_english)
    }
    kept_attachment_sources = {
        item.source_file
        for item in selected
        if (item.source_file, item.track.index) not in planned_restyle and item.track.codec_name.casefold() in {"ass", "ssa"}
    }
    kept_container_hashes: set[str] = set()
    if planned_restyle:
        for kept_source in kept_attachment_sources:
            attachment_fonts[kept_source] = _extract_font_attachments(kept_source)
            for path in attachment_fonts[kept_source]:
                if path is not None and (digest := _file_sha256(Path(path))) is not None:
                    kept_container_hashes.add(digest)

    for item in selected:
        if not matches_any_language(item.track, wanted_languages, treat_enm_as_english=treat_enm_as_english):
            continue
        track = item.track
        if is_cc_or_sdh(track):
            continue
        if track.codec_name.casefold() != "ass":
            warn(f"Restyling is unsupported for {track.codec_name}; keeping subtitle track {track.relative_index} unchanged.", transform_subtitles)
            continue

        # mkvextract writes the container timestamps into ASS events; carrying the
        # reported container delay into SubTrack would apply it a second time.
        subtitle = SubFile.from_mkv(item.source_file, track.relative_index, preserve_delay=False)
        _disambiguate_extracted_sub(subtitle, item.source_file, track.index)
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
            resolved = font.file.resolve()
            digest = _file_sha256(resolved)
            if digest is not None and digest in kept_container_hashes:
                continue
            fonts_by_key[digest or str(resolved)] = font
        language = track.sanitized_lang.to_tag() or "und"
        default = track.is_default
        forced = track.is_forced
        hearing_impaired: bool | None = None
        if fixed is not None:
            language, default, forced, hearing_impaired = fixed[(item.source_file, track.index)]
        track_args = ["--hearing-impaired-flag", f"0:{'yes' if hearing_impaired else 'no'}"] if hearing_impaired is not None else None
        output_track = subtitle.to_track(
            title_for(item),
            language,
            default,
            forced,
            args=track_args,
        )
        if item.source_file != target_source:
            output_track.delay += donor_delay
        tracks.append(output_track)
        transformed.add((item.source_file, track.index))

    return tracks, list(fonts_by_key.values()), transformed
