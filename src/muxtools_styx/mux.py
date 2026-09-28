from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any
from warnings import warn as python_warn

from muxtools import ParsedFile, Premux, TrackType, apply_dynamic_tokens, get_setup_attr, get_setup_dir, mux

from .metadata import edit_metadata_in_place, fixed_metadata, metadata_arguments
from .selection import MuxOptions, SelectedTrack, Selection, SyncOptions, TrackOptions, TransformOptions, select_tracks
from .subtitles import transform_subtitles
from .sync import sync_arguments


def _existing_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} file does not exist: {resolved}")
    return resolved


def _group_by_source(tracks: tuple[SelectedTrack, ...]) -> dict[Path, list[SelectedTrack]]:
    grouped: dict[Path, list[SelectedTrack]] = defaultdict(list)
    for selected in tracks:
        grouped[selected.source_file].append(selected)
    return grouped


def _indices(tracks: list[SelectedTrack], kind: TrackType) -> list[int] | None:
    result = [item.track.relative_index for item in tracks if item.track.type == kind]
    return result or None


def build_mux_inputs(selection: Selection, options: MuxOptions) -> list[Any]:
    all_selected = (*selection.video, *selection.audio, *selection.subtitles)
    grouped = _group_by_source(all_selected)
    transformed_tracks: list[Any] = []
    fonts: list[Any] = []
    transformed: set[tuple[Path, int]] = set()
    fixed = fixed_metadata((*selection.audio, *selection.subtitles)) if options.transforms.fix_tags else {}

    from .naming import normalized_track_title

    if options.transforms.restyle_subs:
        transformed_title = normalized_track_title if options.transforms.normalize_track_names else lambda item: item.track.title or ""
        transformed_tracks, fonts, transformed = transform_subtitles(
            selection.subtitles,
            options.transforms.restyle_languages,
            title_for=transformed_title,
            target_source=selection.chapter_source,
            donor_delay=options.sync.sub_sync,
            fixed=fixed if options.transforms.fix_tags else None,
        )

    inputs: list[Any] = []
    for source, selected in grouped.items():
        passthrough = [item for item in selected if (item.source_file, item.track.index) not in transformed]
        if not passthrough and source != selection.chapter_source:
            continue
        arguments: list[str] = []
        if source != selection.chapter_source:
            arguments.extend(sync_arguments([item for item in passthrough if item.track.type == TrackType.AUDIO], options.sync.audio_sync))
            arguments.extend(sync_arguments([item for item in passthrough if item.track.type == TrackType.SUB], options.sync.sub_sync))
        arguments.extend(
            metadata_arguments(
                [item for item in passthrough if item.track.type in (TrackType.AUDIO, TrackType.SUB)],
                normalize_names=options.transforms.normalize_track_names,
                fix_tags=options.transforms.fix_tags,
                title_for=normalized_track_title,
                fixed=fixed,
            )
        )
        inputs.append(
            Premux(
                source,
                video=_indices(passthrough, TrackType.VIDEO),
                audio=_indices(passthrough, TrackType.AUDIO),
                subtitles=_indices(passthrough, TrackType.SUB),
                keep_attachments=any(item.track.type == TrackType.SUB for item in passthrough),
                keep_chapters=source == selection.chapter_source,
                mkvmerge_args=arguments,
            )
        )
    return [*inputs, *transformed_tracks, *fonts]


def composed_media(target: ParsedFile, selection: Selection) -> ParsedFile:
    counters: dict[TrackType, int] = defaultdict(int)
    tracks = []
    for item in (*selection.video, *selection.audio, *selection.subtitles):
        track_type = item.track.type
        tracks.append(replace(item.track, relative_index=counters[track_type]))
        counters[track_type] += 1
    return ParsedFile(target.container_info, tracks, True, target.source, target.raw_ffprobe, target.raw_mkvmerge)


def resolve_output_template(template: str, parsed: ParsedFile, out_dir: Path) -> Path:
    if "$crc32$" in template.casefold():
        raise ValueError("$crc32$ output templates cannot be preflighted safely")
    filename = apply_dynamic_tokens(template, parsed, True, caller=resolve_output_template)
    if "$" in filename:
        raise ValueError(f"unresolved output token in template: {filename}")
    if not filename.casefold().endswith(".mkv"):
        filename = f"{filename}.mkv"
    relative = Path(filename)
    if relative.is_absolute() or relative.name != filename:
        raise ValueError(f"output template must resolve to a filename, not a path: {filename}")
    directory = out_dir.expanduser().resolve()
    output = (directory / relative).resolve()
    if not output.is_relative_to(directory):
        raise ValueError(f"output escapes the configured directory: {output}")
    return output


def resolve_setup_output(target: ParsedFile, selection: Selection) -> Path:
    template = _resolve_setup_tokens(str(get_setup_attr("out_name", "$show$ - $ep$ (premux)")))
    return resolve_output_template(template, composed_media(target, selection), Path(str(get_setup_attr("out_dir", "premux"))))


def _resolve_setup_tokens(template: str) -> str:
    for attribute in get_setup_dir():
        value = get_setup_attr(attribute, None)
        if isinstance(value, str):
            template = template.replace(f"${attribute}$", value)
    template = template.replace("$show$", str(get_setup_attr("show_name", "Example")))
    template = template.replace("$ep$", str(get_setup_attr("episode", "01")))
    return template


def _can_edit_in_place(options: MuxOptions, donor: Path | None, outfile: Path | None, target: Path) -> bool:
    transforms = options.transforms
    metadata_only = transforms.fix_tags or transforms.normalize_track_names
    expected_transforms = TransformOptions(fix_tags=transforms.fix_tags, normalize_track_names=transforms.normalize_track_names)
    output_is_target = outfile is None or outfile.expanduser().resolve() == target
    return (
        metadata_only
        and donor is None
        and options.tracks == TrackOptions()
        and transforms == expected_transforms
        and options.sync == SyncOptions()
        and output_is_target
    )


def process_mux(
    target: Path,
    *,
    donor: Path | None = None,
    supplemental_info: str | None = None,
    donor_supplemental_info: str | None = None,
    options: MuxOptions | None = None,
    outfile: Path | None = None,
    overwrite: bool = False,
) -> Path:
    options = options or MuxOptions()
    target = _existing_file(target, "target")
    donor = _existing_file(donor, "donor") if donor is not None else None
    if options.transforms.tpp:
        python_warn("TPP is not implemented; the option is currently a no-op.", stacklevel=2)

    target_info = ParsedFile.from_file(target, process_mux)
    donor_info = ParsedFile.from_file(donor, process_mux) if donor is not None else None
    selection = select_tracks(
        target_info,
        donor_info,
        options,
        target_supplemental_info=supplemental_info,
        donor_supplemental_info=donor_supplemental_info,
    )
    if _can_edit_in_place(options, donor, outfile, target):
        if target.suffix.casefold() != ".mkv":
            raise ValueError("in-place metadata editing requires an MKV input")
        return edit_metadata_in_place(
            target,
            (*selection.video, *selection.audio, *selection.subtitles),
            normalize_names=options.transforms.normalize_track_names,
            fix_tags=options.transforms.fix_tags,
            title=_resolve_setup_tokens(str(get_setup_attr("mkv_title_naming", ""))) if options.transforms.fix_tags else None,
        )
    if outfile is not None and outfile.expanduser().resolve() == target:
        raise ValueError("output may equal the input only when using fix_tags and/or normalize_track_names without other policies")
    outfile = outfile.expanduser().resolve() if outfile is not None else resolve_setup_output(target_info, selection)
    if outfile.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {outfile}")
    outfile.parent.mkdir(parents=True, exist_ok=True)
    mux_outfile = outfile
    replace_output = False
    if outfile.exists():
        mux_outfile = outfile.with_name(f".{outfile.stem}.muxtools-styx-tmp{outfile.suffix}")
        if mux_outfile.exists():
            raise FileExistsError(f"temporary output already exists: {mux_outfile}")
        replace_output = True

    inputs = build_mux_inputs(selection, options)
    result = Path(mux(*inputs, outfile=mux_outfile))
    if replace_output:
        assert outfile is not None
        return result.replace(outfile)
    return result
