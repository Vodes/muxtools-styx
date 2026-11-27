from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any
from warnings import warn as python_warn

from muxtools import ParsedFile, Premux, TrackType, apply_dynamic_tokens, get_setup_attr, get_setup_dir, mux
from muxtools.muxing.muxer import clean_name

from .metadata import edit_metadata_in_place, fixed_metadata, metadata_arguments
from .selection import (
    MuxOptions,
    SelectedTrack,
    Selection,
    mkvmerge_track_id,
    select_tracks,
)
from .subtitles import transform_subtitles
from .sync import sync_arguments

_UNRESOLVED_TOKEN_RE = re.compile(r"\$[A-Za-z0-9_]+\$")


def _existing_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} file does not exist: {resolved}")
    return resolved


def _group_by_source(tracks: tuple[SelectedTrack, ...], chapter_source: Path) -> dict[Path, list[SelectedTrack]]:
    grouped: dict[Path, list[SelectedTrack]] = defaultdict(list)
    for selected in tracks:
        grouped[selected.source_file].append(selected)
    grouped.setdefault(chapter_source, [])
    return grouped


def _track_ids(tracks: list[SelectedTrack], kind: TrackType) -> list[int] | None:
    result = [mkvmerge_track_id(item.track) for item in tracks if item.track.type == kind]
    return result or None


def _keep_attachments(tracks: list[SelectedTrack]) -> bool:
    return any(item.track.type == TrackType.SUB and item.track.codec_name.casefold() in {"ass", "ssa"} for item in tracks)


def build_mux_inputs(selection: Selection, options: MuxOptions) -> list[Any]:
    all_selected = (*selection.video, *selection.audio, *selection.subtitles)
    grouped = _group_by_source(all_selected, selection.chapter_source)
    transformed_tracks: list[Any] = []
    fonts: list[Any] = []
    transformed: set[tuple[Path, int]] = set()
    fixed = (
        fixed_metadata((*selection.audio, *selection.subtitles), treat_enm_as_english=options.treat_enm_as_english)
        if options.transforms.fix_tags
        else {}
    )

    from .naming import normalized_track_title

    normalize_title = lambda item: normalized_track_title(item, treat_enm_as_english=options.treat_enm_as_english)

    if options.transforms.restyle_subs:
        transformed_title = normalize_title if options.transforms.normalize_track_names else lambda item: item.track.title or ""
        transformed_tracks, fonts, transformed = transform_subtitles(
            selection.subtitles,
            options.transforms.restyle_languages,
            title_for=transformed_title,
            target_source=selection.chapter_source,
            donor_delay=options.sync.sub_sync,
            fixed=fixed if options.transforms.fix_tags else None,
            treat_enm_as_english=options.treat_enm_as_english,
        )

    inputs: list[Premux] = []
    source_file_ids: dict[Path, int] = {}
    for source, selected in grouped.items():
        passthrough = [item for item in selected if (item.source_file, item.track.index) not in transformed]
        if not passthrough and source != selection.chapter_source:
            continue
        arguments: list[str] = ["--no-global-tags"]
        if source != selection.chapter_source:
            arguments.extend(sync_arguments([item for item in passthrough if item.track.type == TrackType.AUDIO], options.sync.audio_sync))
            arguments.extend(sync_arguments([item for item in passthrough if item.track.type == TrackType.SUB], options.sync.sub_sync))
        arguments.extend(
            metadata_arguments(
                [item for item in passthrough if item.track.type in (TrackType.AUDIO, TrackType.SUB)],
                normalize_names=options.transforms.normalize_track_names,
                fix_tags=options.transforms.fix_tags,
                title_for=normalize_title,
                fixed=fixed,
            )
        )
        source_file_ids[source] = len(inputs)
        inputs.append(
            Premux(
                source,
                video=_track_ids(passthrough, TrackType.VIDEO),
                audio=_track_ids(passthrough, TrackType.AUDIO),
                subtitles=_track_ids(passthrough, TrackType.SUB),
                keep_attachments=_keep_attachments(passthrough),
                keep_chapters=source == selection.chapter_source,
                mkvmerge_args=arguments,
                assume_absolute=True,
            )
        )

    transformed_keys = [(item.source_file, item.track.index) for item in selection.subtitles if (item.source_file, item.track.index) in transformed]
    transformed_file_ids = {key: len(inputs) + offset for offset, key in enumerate(transformed_keys)}
    track_order: list[str] = []
    for item in all_selected:
        key = (item.source_file, item.track.index)
        if key in transformed_file_ids:
            track_order.append(f"{transformed_file_ids[key]}:0")
        elif item.source_file in source_file_ids:
            track_order.append(f"{source_file_ids[item.source_file]}:{mkvmerge_track_id(item.track)}")
    if inputs and track_order:
        inputs[0].args = ["--track-order", ",".join(track_order), *inputs[0].args]

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
    if _UNRESOLVED_TOKEN_RE.search(filename):
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


def _resolve_setup_tokens(template: str, *, show_name: str | None = None, episode: str | None = None, clean: bool = False) -> str:
    for attribute in get_setup_dir():
        if attribute in {"show_name", "episode"}:
            continue
        value = get_setup_attr(attribute, None)
        if isinstance(value, str):
            template = template.replace(f"${attribute}$", value)
    resolved_show = str(get_setup_attr("show_name", "Example")) if show_name is None else show_name
    resolved_ep = str(get_setup_attr("episode", "01")) if episode is None else episode
    if clean:
        template = template.replace("$show_name$", "$show$").replace("$episode$", "$ep$")
        template = clean_name(template)
    template = template.replace("$show_name$", resolved_show).replace("$episode$", resolved_ep)
    template = template.replace("$show$", resolved_show)
    template = template.replace("$ep$", resolved_ep)
    return template


def _resolve_explicit_output(outfile: Path, target: ParsedFile, selection: Selection) -> Path:
    resolved = outfile.expanduser().resolve()
    name = resolved.name
    if "$crc32$" in name.casefold():
        raise ValueError("$crc32$ output templates cannot be preflighted safely")
    if "$" not in name:
        return resolved
    expanded = apply_dynamic_tokens(name, composed_media(target, selection), True, caller=_resolve_explicit_output)
    if _UNRESOLVED_TOKEN_RE.search(expanded):
        raise ValueError(f"unresolved output token in path: {expanded}")
    return resolved.with_name(expanded)


def can_edit_in_place(
    options: MuxOptions,
    donor: Path | None,
    outfile: Path | None,
    target: Path,
    *,
    allow_implicit_in_place: bool = True,
) -> bool:
    tracks = options.tracks
    transforms = options.transforms
    metadata_only = transforms.fix_tags or transforms.normalize_track_names
    has_track_policy = any(
        (
            tracks.keep_video,
            tracks.keep_audio,
            tracks.fill_audio,
            tracks.best_audio,
            tracks.keep_subs,
            tracks.keep_subs_missing_languages,
            tracks.keep_non_english,
            tracks.discard_new_subs,
            tracks.remove_unnecessary,
        )
    )
    has_sync = options.sync.audio_sync != 0 or options.sync.sub_sync != 0
    resolved_target = target.expanduser().resolve()
    output_is_target = (outfile is None and allow_implicit_in_place) or (outfile is not None and outfile.expanduser().resolve() == resolved_target)
    return metadata_only and donor is None and not has_track_policy and not transforms.restyle_subs and not has_sync and output_is_target


def process_mux(
    target: Path,
    *,
    donor: Path | None = None,
    supplemental_info: str | None = None,
    donor_supplemental_info: str | None = None,
    options: MuxOptions | None = None,
    outfile: Path | None = None,
    overwrite: bool = False,
    allow_implicit_in_place: bool = True,
    explicit_mkv_title: str | None = None,
    _target_info: ParsedFile | None = None,
    _donor_info: ParsedFile | None = None,
    _selection: Selection | None = None,
    _warn_options: bool = True,
) -> Path:
    options = options or MuxOptions()
    target = _existing_file(target, "target")
    donor = _existing_file(donor, "donor") if donor is not None else None
    if options.transforms.tpp:
        python_warn("TPP is not implemented; the option is currently a no-op.", stacklevel=2)

    target_info = _target_info if _target_info is not None else ParsedFile.from_file(target, process_mux)
    donor_info = _donor_info if _donor_info is not None else (ParsedFile.from_file(donor, process_mux) if donor is not None else None)
    selection = (
        _selection
        if _selection is not None
        else select_tracks(
            target_info,
            donor_info,
            options,
            target_supplemental_info=supplemental_info,
            donor_supplemental_info=donor_supplemental_info,
            warn_unused=_warn_options,
        )
    )
    if can_edit_in_place(options, donor, outfile, target, allow_implicit_in_place=allow_implicit_in_place):
        if target.suffix.casefold() != ".mkv":
            raise ValueError("in-place metadata editing requires an MKV input")
        container = target_info.container_info.raw_mkvmerge
        muxing_application = container.properties.muxing_application if container and container.properties else None
        if explicit_mkv_title is not None:
            resolved_title = explicit_mkv_title or None
        elif options.transforms.fix_tags:
            setup_title = str(get_setup_attr("mkv_title_naming", ""))
            resolved_title = _resolve_setup_tokens(setup_title, clean=True) if setup_title else None
        else:
            resolved_title = None
        return edit_metadata_in_place(
            target,
            (*selection.video, *selection.audio, *selection.subtitles),
            normalize_names=options.transforms.normalize_track_names,
            fix_tags=options.transforms.fix_tags,
            title=resolved_title,
            muxing_application=muxing_application,
            treat_enm_as_english=options.treat_enm_as_english,
        )

    resolved_outfile = (
        _resolve_explicit_output(outfile, target_info, selection) if outfile is not None else resolve_setup_output(target_info, selection)
    )
    if resolved_outfile == target:
        if can_edit_in_place(options, donor, target, target, allow_implicit_in_place=False):
            raise ValueError("output resolves to the input file; omit --out-dir/--out-name or pass -o matching the input to edit in place")
        raise ValueError("output may equal the input only when using fix_tags and/or normalize_track_names without other policies")
    if donor is not None and resolved_outfile == donor:
        raise ValueError("output cannot overwrite the donor file")
    if resolved_outfile.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {resolved_outfile}")
    resolved_outfile.parent.mkdir(parents=True, exist_ok=True)
    mux_outfile = resolved_outfile
    replace_output = False
    if resolved_outfile.exists():
        mux_outfile = resolved_outfile.with_name(f".{resolved_outfile.stem}.muxtools-styx-tmp{resolved_outfile.suffix}")
        if mux_outfile.exists():
            raise FileExistsError(f"temporary output already exists: {mux_outfile}")
        replace_output = True

    inputs = build_mux_inputs(selection, options)
    result = Path(mux(*inputs, outfile=mux_outfile))
    if replace_output:
        return result.replace(resolved_outfile)
    return result
