from __future__ import annotations

from pathlib import Path

from muxtools import Premux, Setup, mux

from .models import MuxPlan, TrackRef
from .postprocess import apply_metadata_postprocess
from .transforms import build_subtitle_transforms


def _relative_ids(tracks: list[TrackRef]) -> int | list[int] | None:
    if not tracks:
        return None
    relative_indices = [track.track.relative_index for track in tracks]
    return relative_indices


def _premux_for_source(plan: MuxPlan, source: Path) -> Premux | None:
    video = [track for track in plan.selection.video if track.source == source]
    audio = [track for track in plan.selection.audio if track.source == source]
    subtitles = [track for track in plan.selection.subtitles if track.source == source]

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


def _setup_for_plan(plan: MuxPlan, debug: bool = False) -> Setup:
    work_dir = plan.output.parent / "_workdir" / plan.output.stem
    setup = Setup(str(plan.output.stem), None, allow_binary_download=False, out_dir=str(plan.output.parent), work_dir=str(work_dir), debug=debug)
    setup.edit("mkv_title_naming", "")
    setup.edit("clean_work_dirs", False)
    return setup


def execute_plan(plan: MuxPlan, debug: bool = False) -> Path:
    plan.output.parent.mkdir(parents=True, exist_ok=True)
    _setup_for_plan(plan, debug=debug)

    tracks = [premux for source in plan.sources if (premux := _premux_for_source(plan, source)) is not None]
    transformed_subs, font_attachments = build_subtitle_transforms(plan.subtitle_transforms)
    tracks.extend(transformed_subs)
    tracks.extend(font_attachments)
    if not tracks:
        raise ValueError(f"No selected tracks to mux for '{plan.output.name}'.")

    output = Path(mux(*tracks, outfile=plan.output, quiet=True, print_cli=False))
    return apply_metadata_postprocess(output, mkv_title=plan.mkv_title, fix_tags=plan.fix_tags)
