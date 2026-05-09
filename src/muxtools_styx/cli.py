from __future__ import annotations

import json
from pathlib import Path

import click

from . import __version__
from .executor import execute_plan, plan_can_skip_mux
from .models import BatchPlan, MuxPlan
from .planner import default_output_path, inspect_path, plan_batch, plan_pair, plan_single


def render_json(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def execute_or_die(plan: MuxPlan, debug: bool) -> Path:
    try:
        return execute_plan(plan, debug=debug)
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


def execute_batch_or_die(batch_plan: BatchPlan, debug: bool) -> list[str]:
    results = list[str]()
    for plan in batch_plan.matches:
        try:
            results.append(str(execute_plan(plan, debug=debug)))
        except Exception as exc:
            raise click.ClickException(f"Failed executing '{plan.output.name}': {exc}") from exc
    return results


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="muxtools-styx")
@click.option("--debug/--no-debug", default=False, show_default=True)
@click.pass_context
def app(ctx: click.Context, debug: bool) -> None:
    """Rewrite-in-progress CLI for planning Styx mux operations."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug


@app.command("inspect")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def inspect_command(input_path: Path) -> None:
    source = inspect_path(input_path)
    click.echo(render_json(source.to_dict()))


@app.command("pair")
@click.argument("donor", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("target", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--keep-video/--use-target-video", default=False, show_default=True)
@click.option("--keep-audio/--no-keep-audio", default=False, show_default=True)
@click.option("--best-audio/--no-best-audio", default=False, show_default=True)
@click.option("--audio-sync", type=int)
@click.option("--sub-sync", type=int)
@click.option("--discard-new-subs/--keep-new-subs", default=False, show_default=True)
@click.option("--keep-subs/--no-keep-subs", default=False, show_default=True)
@click.option("--keep-subs-missing-languages/--no-keep-subs-missing-languages", default=False, show_default=True)
@click.option("--keep-non-english/--no-keep-non-english", default=False, show_default=True)
@click.option("--mkv-title", type=str)
@click.option("--fix-tags/--no-fix-tags", default=False, show_default=True)
@click.option("--remove-unnecessary/--keep-all-tracks", default=False, show_default=True)
@click.option("--audio-language", "audio_languages", multiple=True)
@click.option("--sub-language", "sub_languages", multiple=True)
@click.option("--restyle-subs/--no-restyle-subs", default=False, show_default=True)
@click.option("--restyle-language", "restyle_languages", multiple=True)
@click.option("--dry-run/--execute", default=False, show_default=True)
@click.pass_context
def pair_command(
    ctx: click.Context,
    donor: Path,
    target: Path,
    output: Path | None,
    keep_video: bool,
    keep_audio: bool,
    best_audio: bool,
    audio_sync: int | None,
    sub_sync: int | None,
    discard_new_subs: bool,
    keep_subs: bool,
    keep_subs_missing_languages: bool,
    keep_non_english: bool,
    mkv_title: str | None,
    fix_tags: bool,
    remove_unnecessary: bool,
    audio_languages: tuple[str, ...],
    sub_languages: tuple[str, ...],
    restyle_subs: bool,
    restyle_languages: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Use TARGET as the base file and copy selected tracks from DONOR."""
    donor_source = inspect_path(donor)
    target_source = inspect_path(target)
    plan = plan_pair(
        donor_source,
        target_source,
        default_output_path(target, output),
        keep_video=keep_video,
        keep_audio=keep_audio,
        best_audio=best_audio,
        audio_sync=audio_sync,
        sub_sync=sub_sync,
        discard_new_subs=discard_new_subs,
        keep_subs=keep_subs,
        keep_subs_missing_languages=keep_subs_missing_languages,
        keep_non_english=keep_non_english,
        mkv_title=mkv_title,
        fix_tags=fix_tags,
        remove_unnecessary=remove_unnecessary,
        audio_languages=list(audio_languages) or None,
        sub_languages=list(sub_languages) or None,
        restyle_subs=restyle_subs,
        restyle_languages=list(restyle_languages) or None,
    )
    click.echo(render_json(plan.to_dict()))
    if not dry_run:
        result = execute_or_die(plan, debug=bool(ctx.obj and ctx.obj.get("debug")))
        click.echo(render_json({"executed": str(result)}))


@app.command("single")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--mkv-title", type=str)
@click.option("--fix-tags/--no-fix-tags", default=False, show_default=True)
@click.option("--remove-unnecessary/--keep-all-tracks", default=False, show_default=True)
@click.option("--audio-language", "audio_languages", multiple=True)
@click.option("--sub-language", "sub_languages", multiple=True)
@click.option("--restyle-subs/--no-restyle-subs", default=False, show_default=True)
@click.option("--restyle-language", "restyle_languages", multiple=True)
@click.option("--dry-run/--execute", default=False, show_default=True)
@click.pass_context
def single_command(
    ctx: click.Context,
    input_path: Path,
    output: Path | None,
    mkv_title: str | None,
    fix_tags: bool,
    remove_unnecessary: bool,
    audio_languages: tuple[str, ...],
    sub_languages: tuple[str, ...],
    restyle_subs: bool,
    restyle_languages: tuple[str, ...],
    dry_run: bool,
) -> None:
    source = inspect_path(input_path)
    plan = plan_single(
        source,
        default_output_path(input_path, output),
        mkv_title=mkv_title,
        fix_tags=fix_tags,
        remove_unnecessary=remove_unnecessary,
        audio_languages=list(audio_languages) or None,
        sub_languages=list(sub_languages) or None,
        restyle_subs=restyle_subs,
        restyle_languages=list(restyle_languages) or None,
    )
    if output is None and plan_can_skip_mux(plan):
        plan.output = input_path.resolve()
    click.echo(render_json(plan.to_dict()))
    if not dry_run:
        result = execute_or_die(plan, debug=bool(ctx.obj and ctx.obj.get("debug")))
        click.echo(render_json({"executed": str(result)}))


@app.command("batch")
@click.argument("donor_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("target_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--episode-offset", default=0, show_default=True, type=int)
@click.option("--fix-tags/--no-fix-tags", default=False, show_default=True)
@click.option("--remove-unnecessary/--keep-all-tracks", default=False, show_default=True)
@click.option("--audio-language", "audio_languages", multiple=True)
@click.option("--sub-language", "sub_languages", multiple=True)
@click.option("--restyle-subs/--no-restyle-subs", default=False, show_default=True)
@click.option("--restyle-language", "restyle_languages", multiple=True)
@click.option("--dry-run/--execute", default=False, show_default=True)
@click.pass_context
def batch_command(
    ctx: click.Context,
    donor_dir: Path,
    target_dir: Path,
    output_dir: Path,
    episode_offset: int,
    fix_tags: bool,
    remove_unnecessary: bool,
    audio_languages: tuple[str, ...],
    sub_languages: tuple[str, ...],
    restyle_subs: bool,
    restyle_languages: tuple[str, ...],
    dry_run: bool,
) -> None:
    batch_plan = plan_batch(
        donor_dir,
        target_dir,
        output_dir,
        episode_offset=episode_offset,
        fix_tags=fix_tags,
        remove_unnecessary=remove_unnecessary,
        audio_languages=list(audio_languages) or None,
        sub_languages=list(sub_languages) or None,
        restyle_subs=restyle_subs,
        restyle_languages=list(restyle_languages) or None,
    )
    click.echo(render_json(batch_plan.to_dict()))
    if not dry_run:
        debug = bool(ctx.obj and ctx.obj.get("debug"))
        results = execute_batch_or_die(batch_plan, debug=debug)
        click.echo(render_json({"executed": results}))


def main() -> None:
    app.main(prog_name="muxtools-styx")
