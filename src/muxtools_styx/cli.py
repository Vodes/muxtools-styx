from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Any

from cyclopts import App, Parameter
from muxtools import ParsedFile, Setup

from .batch import BatchMatch, BatchPreflight, BatchResult, process_batch
from .inspect import format_inspection, inspect_file
from .matching import format_episode, parse_filename
from .mux import (
    _resolve_setup_tokens,
    can_edit_in_place,
    composed_media,
    process_mux,
    resolve_output_template,
)
from .selection import MuxOptions, Selection, SyncOptions, TrackOptions, TransformOptions, validate_options

app = App(name="muxtools-styx")
_JSON_MODE = False
_DEFAULT_OUT_DIR = Path("premux")
_DEFAULT_OUT_NAME = "$show$ - $ep$ (premux)"
_DEFAULT_MKV_TITLE = "$show$ - $ep$"


def _configure_json_logging() -> None:
    from muxtools.utils.log import logger as muxtools_logger

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s | %(message)s"))
    muxtools_logger.handlers = [handler]
    muxtools_logger.setLevel(logging.INFO)
    muxtools_logger.propagate = False


def _options(
    *,
    keep_video: bool,
    keep_audio: bool,
    fill_audio: bool,
    best_audio: bool,
    keep_subs: bool,
    keep_subs_missing_languages: bool,
    keep_non_english: bool,
    discard_new_subs: bool,
    remove_unnecessary: bool,
    audio_language: tuple[str, ...],
    sub_language: tuple[str, ...],
    restyle_subs: bool,
    restyle_language: tuple[str, ...],
    fix_tags: bool,
    normalize_track_names: bool,
    tpp: bool,
    audio_sync: int,
    sub_sync: int,
    treat_enm_as_english: bool = True,
) -> MuxOptions:
    return MuxOptions(
        tracks=TrackOptions(
            keep_video=keep_video,
            keep_audio=keep_audio,
            fill_audio=fill_audio,
            best_audio=best_audio,
            keep_subs=keep_subs,
            keep_subs_missing_languages=keep_subs_missing_languages,
            keep_non_english=keep_non_english,
            discard_new_subs=discard_new_subs,
            remove_unnecessary=remove_unnecessary,
            audio_languages=audio_language or ("ja", "en", "de"),
            sub_languages=sub_language or ("en", "de"),
        ),
        transforms=TransformOptions(
            restyle_subs=restyle_subs,
            restyle_languages=restyle_language or ("en", "de"),
            fix_tags=fix_tags,
            normalize_track_names=normalize_track_names,
            tpp=tpp,
        ),
        sync=SyncOptions(audio_sync, sub_sync),
        treat_enm_as_english=treat_enm_as_english,
    )


def _infer_episode_and_show(target: Path, episode: str | None, show_name: str | None, episode_padding: int) -> tuple[str, str]:
    parsed = parse_filename(target)
    inferred_episode = str(parsed.episode) if parsed.episode is not None else (parsed.raw_episode or "01")
    return format_episode(episode or inferred_episode, episode_padding), show_name or parsed.title or target.stem


def _setup(
    target: Path,
    *,
    episode: str | None,
    show_name: str | None,
    out_dir: Path,
    out_name: str,
    mkv_title: str,
    clean_work_dirs: bool,
    episode_padding: int = 2,
    work_dir: Path | None = None,
) -> Setup:
    formatted_episode, resolved_show = _infer_episode_and_show(target, episode, show_name, episode_padding)
    kwargs: dict[str, Any] = {
        "episode": formatted_episode,
        "show_name": resolved_show,
        "out_dir": str(out_dir),
        "out_name": out_name,
        "mkv_title_naming": mkv_title,
        "clean_work_dirs": clean_work_dirs,
    }
    if work_dir is not None:
        kwargs["work_dir"] = str(work_dir)
    return Setup(**kwargs)


def _emit(value: dict[str, Any], human: str) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")) if _JSON_MODE else human)


@app.command
def mux(
    target: Path,
    *,
    donor: Path | None = None,
    supplemental_info: str | None = None,
    donor_supplemental_info: str | None = None,
    episode: str | None = None,
    episode_padding: Annotated[int, Parameter(help="Minimum digits for numeric episode identifiers (at least 2).")] = 2,
    show_name: str | None = None,
    out_dir: Annotated[Path | None, Parameter(help="Output directory (defaults to 'premux').")] = None,
    out_name: Annotated[str | None, Parameter(help="Output filename template (defaults to '$show$ - $ep$ (premux)').")] = None,
    mkv_title: Annotated[str | None, Parameter(help="MKV container title template (defaults to '$show$ - $ep$').")] = None,
    clean_work_dirs: bool = True,
    output: Annotated[Path | None, Parameter(name=["--output", "-o"])] = None,
    overwrite: bool = False,
    keep_video: bool = False,
    keep_audio: bool = False,
    fill_audio: bool = False,
    best_audio: bool = False,
    keep_subs: bool = False,
    keep_subs_missing_languages: bool = False,
    keep_non_english: bool = False,
    discard_new_subs: bool = False,
    remove_unnecessary: bool = False,
    audio_language: tuple[str, ...] = (),
    sub_language: tuple[str, ...] = (),
    restyle_subs: bool = False,
    restyle_language: tuple[str, ...] = (),
    fix_tags: bool = False,
    normalize_track_names: bool = False,
    tpp: bool = False,
    audio_sync: int = 0,
    sub_sync: int = 0,
    treat_enm_as_english: Annotated[bool, Parameter(help="Treat enm (Honorifics) tracks as English for selection and restyling.")] = True,
) -> None:
    """Mux one target, optionally retaining selected tracks from a donor."""
    formatted_episode, resolved_show = _infer_episode_and_show(target, episode, show_name, episode_padding)
    options = _options(**{key: value for key, value in locals().items() if key in _options.__annotations__})
    validate_options(options, donor, target=target, donor_supplemental_info=donor_supplemental_info)

    allow_implicit_in_place = out_dir is None and out_name is None
    in_place = can_edit_in_place(options, donor, output, target, allow_implicit_in_place=allow_implicit_in_place)
    explicit_title: str | None = None
    created_workdir: Path | None = None
    created_workdir_root = False
    if in_place:
        if mkv_title is not None or options.transforms.fix_tags:
            title_template = _DEFAULT_MKV_TITLE if mkv_title is None else mkv_title
            explicit_title = (
                _resolve_setup_tokens(title_template, show_name=resolved_show, episode=formatted_episode, clean=True) if title_template else ""
            )
    else:
        workdir_root = Path.cwd() / "_workdir"
        candidate_workdir = workdir_root / formatted_episode
        created_workdir_root = not workdir_root.exists()
        existed_before = candidate_workdir.exists()
        setup = _setup(
            target,
            episode=episode,
            episode_padding=episode_padding,
            show_name=show_name,
            out_dir=_DEFAULT_OUT_DIR if out_dir is None else out_dir,
            out_name=_DEFAULT_OUT_NAME if out_name is None else out_name,
            mkv_title=_DEFAULT_MKV_TITLE if mkv_title is None else mkv_title,
            clean_work_dirs=clean_work_dirs,
        )
        if not existed_before and setup.work_dir:
            created_workdir = Path(setup.work_dir)

    try:
        result = process_mux(
            target,
            donor=donor,
            supplemental_info=supplemental_info,
            donor_supplemental_info=donor_supplemental_info,
            options=options,
            outfile=output,
            overwrite=overwrite,
            allow_implicit_in_place=allow_implicit_in_place,
            explicit_mkv_title=explicit_title,
            _warn_options=False,
        )
    except Exception:
        if created_workdir is not None and created_workdir.is_dir() and not any(created_workdir.iterdir()):
            created_workdir.rmdir()
            if created_workdir_root and created_workdir.parent.is_dir() and not any(created_workdir.parent.iterdir()):
                created_workdir.parent.rmdir()
        raise
    _emit({"output": str(result.resolve())}, f"Output: {result.resolve()}")


@app.command
def inspect(file: Path) -> None:
    """Inspect filename elements and local media tracks."""
    result = inspect_file(file)
    _emit(result, format_inspection(result))


def _resolve_batch_output(
    match: BatchMatch,
    target_info: ParsedFile,
    selection: Selection,
    out_dir: Path,
    out_name: str,
    show_name: str | None,
    episode_padding: int = 2,
) -> Path:
    info = parse_filename(match.target)
    formatted_episode = format_episode(match.episode.number, episode_padding)
    resolved_show = show_name or info.title or match.target.stem
    template = _resolve_setup_tokens(out_name, show_name=resolved_show, episode=formatted_episode)
    return resolve_output_template(template, composed_media(target_info, selection), out_dir)


@app.command
def batch(
    target_dir: Path,
    *,
    donor_dir: Path | None = None,
    donor_season: Annotated[int | None, Parameter(help="Override the season for every donor file when matching (0 allows specials).")] = None,
    supplemental_info: str | None = None,
    donor_supplemental_info: str | None = None,
    episode_offset: int = 0,
    skip_unmatched: bool = False,
    dry_run: bool = False,
    episode_padding: Annotated[int, Parameter(help="Minimum digits for numeric episode identifiers (at least 2).")] = 2,
    show_name: str | None = None,
    out_dir: Path = _DEFAULT_OUT_DIR,
    out_name: str = _DEFAULT_OUT_NAME,
    mkv_title: str = _DEFAULT_MKV_TITLE,
    clean_work_dirs: bool = True,
    overwrite: bool = False,
    keep_video: bool = False,
    keep_audio: bool = False,
    fill_audio: bool = False,
    best_audio: bool = False,
    keep_subs: bool = False,
    keep_subs_missing_languages: bool = False,
    keep_non_english: bool = False,
    discard_new_subs: bool = False,
    remove_unnecessary: bool = False,
    audio_language: tuple[str, ...] = (),
    sub_language: tuple[str, ...] = (),
    restyle_subs: bool = False,
    restyle_language: tuple[str, ...] = (),
    fix_tags: bool = False,
    normalize_track_names: bool = False,
    tpp: bool = False,
    audio_sync: int = 0,
    sub_sync: int = 0,
    treat_enm_as_english: Annotated[bool, Parameter(help="Treat enm (Honorifics) tracks as English for selection and restyling.")] = True,
) -> None:
    """Preflight and sequentially process an episode directory."""
    options = _options(**{key: value for key, value in locals().items() if key in _options.__annotations__})
    resolver = lambda match, target_info, selection: _resolve_batch_output(
        match,
        target_info,
        selection,
        out_dir,
        out_name,
        show_name,
        episode_padding,
    )

    def setup_match(match: BatchMatch, outfile: Path) -> None:
        ep_str = format_episode(match.episode.number, episode_padding)
        workdir_name = match.episode.label() if match.episode.season is not None else ep_str
        _setup(
            match.target,
            episode=str(match.episode.number),
            episode_padding=episode_padding,
            show_name=show_name,
            out_dir=outfile.parent,
            out_name=outfile.name,
            mkv_title=mkv_title,
            clean_work_dirs=clean_work_dirs,
            work_dir=Path.cwd() / "_workdir" / workdir_name,
        )

    result = process_batch(
        target_dir,
        donor_dir=donor_dir,
        donor_season=donor_season,
        supplemental_info=supplemental_info,
        donor_supplemental_info=donor_supplemental_info,
        episode_offset=episode_offset,
        episode_padding=episode_padding,
        skip_unmatched=skip_unmatched,
        dry_run=dry_run,
        output_resolver=resolver,
        overwrite=overwrite,
        options=options,
        setup_factory=setup_match,
    )
    if isinstance(result, BatchPreflight):
        _emit(result.to_dict(), _format_preflight(result))
        return
    assert isinstance(result, BatchResult)
    _emit(result.to_dict(), "\n".join(f"Output: {path.resolve()}" for path in result.outputs))


def _format_preflight(preflight: BatchPreflight) -> str:
    lines = [f"Matches: {len(preflight.matches)}"]
    for idx, match in enumerate(preflight.matches):
        donor = f" <- {match.donor.name}" if match.donor else ""
        output = f" -> {preflight.outputs[idx]}" if idx < len(preflight.outputs) else ""
        lines.append(f"  {match.episode}: {match.target.name}{donor}{output}")
    if preflight.skipped:
        lines.append("Skipped: " + ", ".join(path.name for path in preflight.skipped))
    if preflight.unused_donors:
        lines.append("Unused donors: " + ", ".join(path.name for path in preflight.unused_donors))
    return "\n".join(lines)


def main() -> None:
    global _JSON_MODE
    arguments = sys.argv[1:]
    _JSON_MODE = "--json" in arguments
    arguments = [argument for argument in arguments if argument != "--json"]
    if _JSON_MODE:
        _configure_json_logging()
    try:
        app(arguments)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as error:  # noqa: BLE001 - the CLI boundary emits stable errors.
        if _JSON_MODE:
            print(json.dumps({"error": {"code": error.__class__.__name__, "message": str(error)}}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
