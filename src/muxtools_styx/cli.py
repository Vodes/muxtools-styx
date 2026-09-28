from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

from cyclopts import App, Parameter
from muxtools import ParsedFile, Setup

from .batch import BatchMatch, BatchPreflight, BatchResult, process_batch
from .inspect import format_inspection, inspect_file
from .matching import parse_filename
from .mux import composed_media, process_mux, resolve_output_template
from .selection import MuxOptions, Selection, SyncOptions, TrackOptions, TransformOptions

app = App(name="muxtools-styx")
_JSON_MODE = False


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
    )


def _setup(
    target: Path,
    *,
    episode: str | None,
    show_name: str | None,
    out_dir: Path,
    out_name: str,
    mkv_title: str,
) -> Setup:
    parsed = parse_filename(target)
    inferred_episode = str(parsed.episode) if parsed.episode is not None else "01"
    return Setup(
        episode=episode or inferred_episode,
        config_file="",
        show_name=show_name or parsed.title or target.stem,
        out_dir=str(out_dir),
        out_name=out_name,
        mkv_title_naming=mkv_title,
    )


def _emit(value: dict[str, Any], human: str) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")) if _JSON_MODE else human)


@app.command
def mux(
    target: Path,
    *,
    donor: Path | None = None,
    episode: str | None = None,
    show_name: str | None = None,
    out_dir: Path = Path("premux"),
    out_name: str = "$show$ - $ep$ (premux)",
    mkv_title: str = "$show$ - $ep$",
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
) -> None:
    """Mux one target, optionally retaining selected tracks from a donor."""
    _setup(target, episode=episode, show_name=show_name, out_dir=out_dir, out_name=out_name, mkv_title=mkv_title)
    options = _options(**{key: value for key, value in locals().items() if key in _options.__annotations__})
    result = process_mux(target, donor=donor, options=options, outfile=output, overwrite=overwrite)
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
) -> Path:
    info = parse_filename(match.target)
    episode = f"{match.episode.number:02d}"
    template = out_name.replace("$show$", show_name or info.title or match.target.stem).replace("$ep$", episode)
    return resolve_output_template(template, composed_media(target_info, selection), out_dir)


@app.command
def batch(
    target_dir: Path,
    *,
    donor_dir: Path | None = None,
    episode_offset: int = 0,
    skip_unmatched: bool = False,
    dry_run: bool = False,
    episode: str | None = None,
    show_name: str | None = None,
    out_dir: Path = Path("premux"),
    out_name: str = "$show$ - $ep$ (premux)",
    mkv_title: str = "$show$ - $ep$",
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
) -> None:
    """Preflight and sequentially process an episode directory."""
    options = _options(**{key: value for key, value in locals().items() if key in _options.__annotations__})
    resolver = lambda match, target_info, selection: _resolve_batch_output(
        match,
        target_info,
        selection,
        output.parent if output else out_dir,
        output.name if output else out_name,
        show_name,
    )

    def setup_match(match: BatchMatch, outfile: Path) -> None:
        info = parse_filename(match.target)
        _setup(
            match.target,
            episode=episode or (str(info.episode) if info.episode is not None else None),
            show_name=show_name,
            out_dir=outfile.parent,
            out_name=outfile.name,
            mkv_title=mkv_title,
        )

    result = process_batch(
        target_dir,
        donor_dir=donor_dir,
        episode_offset=episode_offset,
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
    lines.extend(f"  {match.episode}: {match.target.name}" + (f" <- {match.donor.name}" if match.donor else "") for match in preflight.matches)
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
