from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from muxtools import Premux, Setup, mux

from .models import MuxPlan, TrackRef
from .postprocess import apply_metadata_postprocess
from .transforms import build_subtitle_tracks

FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}
TEXT_SUBTITLE_CODECS = {"ass", "subrip"}


def _relative_ids(tracks: list[TrackRef]) -> int | list[int] | None:
    if not tracks:
        return None
    relative_indices = [track.track.relative_index for track in tracks]
    return relative_indices


def _premux_for_source(plan: MuxPlan, source: Path, rebuilt_text_subtitles: set[tuple[Path, int]]) -> Premux | None:
    video = [track for track in plan.selection.video if track.source == source]
    audio = [track for track in plan.selection.audio if track.source == source]
    subtitles = [
        track
        for track in plan.selection.subtitles
        if track.source == source
        if (track.source, track.track.relative_index) not in rebuilt_text_subtitles
    ]

    if not any((video, audio, subtitles)):
        return None

    keep_attachments = source in plan.selection.attachments_from
    source_args = plan.source_args.get(str(source), [])
    return Premux(
        source,
        video=_relative_ids(video),
        audio=_relative_ids(audio),
        subtitles=_relative_ids(subtitles),
        keep_attachments=keep_attachments,
        mkvmerge_args=["--no-global-tags", *source_args],
    )


def _work_dir_for_plan(plan: MuxPlan) -> Path:
    return plan.output.parent / "_workdir" / plan.output.stem


def _setup_for_plan(plan: MuxPlan, debug: bool = False) -> Setup:
    work_dir = _work_dir_for_plan(plan)
    setup = Setup(str(plan.output.stem), None, allow_binary_download=False, out_dir=str(plan.output.parent), work_dir=str(work_dir), debug=debug)
    setup.edit("mkv_title_naming", "")
    setup.edit("clean_work_dirs", False)
    return setup


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font_attachment_specs(source: Path) -> list[tuple[int, str]]:
    result = subprocess.run(["mkvmerge", "-J", str(source)], check=True, capture_output=True, text=True)
    metadata = json.loads(result.stdout)
    attachments = metadata.get("attachments", [])
    specs = list[tuple[int, str]]()
    for attachment in attachments:
        attachment_id = attachment.get("id")
        filename = attachment.get("file_name")
        if not isinstance(attachment_id, int) or not isinstance(filename, str):
            continue
        if Path(filename).suffix.lower() not in FONT_EXTENSIONS:
            continue
        specs.append((attachment_id, filename))
    return specs


def _extract_attachment_fonts(sources: list[Path], work_dir: Path) -> tuple[list[Path], dict[Path, set[str]]]:
    extract_root = work_dir / "embedded-fonts"
    extracted_dirs = list[Path]()
    extracted_hashes_by_source = dict[Path, set[str]]()

    for index, source in enumerate(sources):
        specs = _font_attachment_specs(source)
        if not specs:
            continue

        output_dir = extract_root / f"{index:02d}-{source.stem}"
        output_dir.mkdir(parents=True, exist_ok=True)

        command = ["mkvextract", "attachments", str(source)]
        used_names = set[str]()
        for attachment_id, filename in specs:
            target_name = filename
            if target_name.casefold() in used_names:
                path = Path(filename)
                target_name = f"{path.stem}-{attachment_id}{path.suffix}"
            used_names.add(target_name.casefold())
            command.append(f"{attachment_id}:{output_dir / target_name}")

        subprocess.run(command, check=True, capture_output=True, text=True)
        extracted_dirs.append(output_dir)
        extracted_hashes_by_source[source] = {_file_hash(path) for path in output_dir.iterdir() if path.is_file()}

    return extracted_dirs, extracted_hashes_by_source


def plan_can_skip_mux(plan: MuxPlan) -> bool:
    return plan.direct_postprocess_source is not None and not plan.subtitle_transforms and not plan.source_args


def _execute_postprocess_only(plan: MuxPlan) -> Path:
    if plan.direct_postprocess_source is None:
        raise ValueError("Direct postprocess execution requires a source path.")

    source = plan.direct_postprocess_source
    destination = plan.output
    if source.resolve() != destination.resolve():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    return apply_metadata_postprocess(destination, mkv_title=plan.mkv_title, fix_tags=plan.fix_tags)


def _execute_with_post_mux_single(plan: MuxPlan, debug: bool = False) -> Path:
    if plan.post_mux_single is None:
        raise ValueError("Post-mux single execution requires transform options.")

    work_dir = _work_dir_for_plan(plan)
    work_dir.mkdir(parents=True, exist_ok=True)
    intermediate = work_dir / f"{plan.output.stem}.merged{plan.output.suffix or '.mkv'}"
    first_pass_plan = replace(
        plan,
        output=intermediate,
        mkv_title=None,
        fix_tags=False,
        post_mux_single=None,
    )
    merged = execute_plan(first_pass_plan, debug=debug)

    from .muxtools_adapter import inspect_source
    from .planner import plan_single

    merged_source = inspect_source(merged)
    options = plan.post_mux_single
    final_plan = plan_single(
        merged_source,
        plan.output,
        mkv_title=plan.mkv_title,
        fix_tags=plan.fix_tags,
        restyle_subs=options.restyle_subs,
        restyle_languages=options.restyle_languages,
    )
    return execute_plan(final_plan, debug=debug)


def execute_plan(plan: MuxPlan, debug: bool = False) -> Path:
    if plan.post_mux_single is not None:
        return _execute_with_post_mux_single(plan, debug=debug)
    if plan_can_skip_mux(plan):
        return _execute_postprocess_only(plan)

    plan.output.parent.mkdir(parents=True, exist_ok=True)
    _setup_for_plan(plan, debug=debug)
    work_dir = _work_dir_for_plan(plan)

    font_sources = list(dict.fromkeys([*plan.selection.attachments_from, *(transform.source for transform in plan.subtitle_transforms)]))
    embedded_font_dirs, embedded_font_hashes_by_source = _extract_attachment_fonts(font_sources, work_dir) if plan.subtitle_transforms else ([], {})
    passthrough_embedded_font_hashes = set[str]()
    for source in plan.selection.attachments_from:
        passthrough_embedded_font_hashes.update(embedded_font_hashes_by_source.get(source, set()))
    passthrough_text_subtitles = [
        track
        for track in plan.selection.subtitles
        if track.source in {transform.source for transform in plan.subtitle_transforms}
        if getattr(track.track, "codec_name", "").casefold() in TEXT_SUBTITLE_CODECS
    ]
    rebuilt_text_subtitles = {
        (track.source, track.track.relative_index)
        for track in passthrough_text_subtitles
    }
    tracks = [premux for source in plan.sources if (premux := _premux_for_source(plan, source, rebuilt_text_subtitles)) is not None]

    transformed_subs, font_attachments = build_subtitle_tracks(
        plan.subtitle_transforms,
        passthrough_text_subtitles,
        additional_fonts=embedded_font_dirs,
        embedded_font_hashes=passthrough_embedded_font_hashes,
    )
    tracks.extend(transformed_subs)
    tracks.extend(font_attachments)
    if not tracks:
        raise ValueError(f"No selected tracks to mux for '{plan.output.name}'.")

    output = Path(mux(*tracks, outfile=plan.output, quiet=True, print_cli=False))
    return apply_metadata_postprocess(output, mkv_title=plan.mkv_title, fix_tags=plan.fix_tags)
