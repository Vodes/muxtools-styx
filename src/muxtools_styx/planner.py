from __future__ import annotations

from pathlib import Path

from .matching import match_episode_paths, parse_episode_key, scan_media_files
from .models import BatchPlan, MuxPlan, SelectionPlan, SourceFile, SubtitleTransform, TrackRef
from .muxtools_adapter import inspect_source
from .rules import choose_best_japanese_audio, choose_donor_audio_tracks, choose_donor_sign_subtitles


def default_output_path(target: Path, output: Path | None = None) -> Path:
    if output is not None:
        return output.resolve()
    suffix = target.suffix or ".mkv"
    return target.with_name(f"{target.stem}.styx{suffix}").resolve()


def plan_pair(
    donor: SourceFile,
    target: SourceFile,
    output: Path,
    *,
    keep_video: bool = False,
    keep_audio: bool = False,
    best_audio: bool = False,
    audio_sync: int | None = None,
    sub_sync: int | None = None,
    discard_new_subs: bool = False,
    keep_subs: bool = False,
    keep_non_english: bool = False,
    mkv_title: str | None = None,
    fix_tags: bool = False,
) -> MuxPlan:
    selected_video_source = donor if keep_video else target

    donor_audio_tracks = choose_donor_audio_tracks(donor, target) if keep_audio else []
    target_audio_tracks = target.audio_tracks.copy()
    if best_audio:
        target_audio_tracks = [track for track in target_audio_tracks if track.language != "ja"]
        donor_audio_tracks = [track for track in donor_audio_tracks if track.language != "ja"]
        if best_japanese_audio := choose_best_japanese_audio(donor, target):
            best_source, best_track = best_japanese_audio
            if best_source.path == donor.path:
                donor_audio_tracks.append(best_track)
            else:
                target_audio_tracks.append(best_track)

    donor_languages = {track.language for track in donor_audio_tracks}
    donor_sign_tracks = choose_donor_sign_subtitles(donor, donor_languages)
    donor_subtitle_tracks = donor_sign_tracks
    if keep_subs:
        donor_subtitle_tracks = donor.subtitle_tracks.copy()
    elif keep_non_english:
        donor_subtitle_tracks = [track for track in donor.subtitle_tracks if track.language != "en"]

    target_subtitle_tracks = [] if discard_new_subs else target.subtitle_tracks.copy()
    source_args = dict[str, list[str]]()
    if audio_sync and donor_audio_tracks:
        source_args.setdefault(str(donor.path), []).extend(_build_sync_args(donor_audio_tracks, audio_sync))
    if sub_sync and donor_subtitle_tracks:
        source_args.setdefault(str(donor.path), []).extend(_build_sync_args(donor_subtitle_tracks, sub_sync))

    selection = SelectionPlan(
        video=[TrackRef(selected_video_source.path, track, "Keep selected video track.") for track in selected_video_source.video_tracks],
        audio=[TrackRef(target.path, track, "Keep target audio track.") for track in target_audio_tracks]
        + [TrackRef(donor.path, track, "Add donor audio because the target lacks this language.") for track in donor_audio_tracks],
        subtitles=[TrackRef(target.path, track, "Keep target subtitle track.") for track in target_subtitle_tracks]
        + [TrackRef(donor.path, track, "Keep donor subtitle track.") for track in donor_subtitle_tracks],
        attachments_from=[
            path
            for path in (
                None if discard_new_subs else target.path,
                donor.path if donor_subtitle_tracks else None,
            )
            if path is not None
        ],
        notes=[
            "Pair planning keeps the target as the default base and layers donor tracks according to the chosen options.",
        ],
    )
    notes = [
        f"Donor source: {donor.path.name}",
        f"Target source: {target.path.name}",
    ]
    if donor.episode and target.episode:
        notes.append(f"Matched episode {target.episode.label()}.")

    return MuxPlan(
        mode="pair",
        output=output,
        sources=[selected_video_source.path, donor.path if selected_video_source.path != donor.path else target.path],
        selection=selection,
        subtitle_transforms=[],
        source_args=source_args,
        mkv_title=mkv_title,
        fix_tags=fix_tags,
        notes=notes,
    )


def plan_single(
    source: SourceFile,
    output: Path,
    *,
    mkv_title: str | None = None,
    fix_tags: bool = False,
    remove_unnecessary: bool = False,
    audio_languages: list[str] | None = None,
    sub_languages: list[str] | None = None,
    restyle_subs: bool = False,
    restyle_languages: list[str] | None = None,
) -> MuxPlan:
    keep_audio_languages = set(audio_languages or ["de", "en", "ja"])
    keep_sub_languages = set(sub_languages or ["de", "en"])
    restyle_target_languages = set(restyle_languages or sub_languages or ["de", "en"])

    selected_audio = source.audio_tracks
    selected_subtitles = source.subtitle_tracks
    if remove_unnecessary:
        selected_audio = [track for track in selected_audio if track.language in keep_audio_languages]
        selected_subtitles = [track for track in selected_subtitles if track.language in keep_sub_languages]

    subtitle_transforms: list[SubtitleTransform] = []
    if restyle_subs:
        transformed_indices = {
            track.relative_index
            for track in selected_subtitles
            if track.language in restyle_target_languages
        }
        subtitle_transforms = [
            SubtitleTransform(
                source=source.path,
                relative_index=track.relative_index,
                language=track.language,
                title=track.title,
                is_default=track.is_default,
                is_forced=track.is_forced,
            )
            for track in selected_subtitles
            if track.relative_index in transformed_indices
        ]
        selected_subtitles = [track for track in selected_subtitles if track.relative_index not in transformed_indices]

    keep_source_attachments = not bool(subtitle_transforms) or bool(selected_subtitles)
    selection = SelectionPlan(
        video=[TrackRef(source.path, track, "Keep source video track.") for track in source.video_tracks],
        audio=[TrackRef(source.path, track, "Keep source audio track.") for track in selected_audio],
        subtitles=[TrackRef(source.path, track, "Keep source subtitle track.") for track in selected_subtitles],
        attachments_from=[source.path] if keep_source_attachments else [],
        notes=[
            "Single-file planning starts from the source file and applies optional filtering and subtitle transforms.",
        ],
    )
    notes = [f"Source file: {source.path.name}"]
    if remove_unnecessary:
        notes.append("Track filtering is enabled.")
    if restyle_subs:
        notes.append("Selected subtitle tracks will be restyled before muxing.")

    return MuxPlan(
        mode="single",
        output=output,
        sources=[source.path],
        selection=selection,
        subtitle_transforms=subtitle_transforms,
        source_args={},
        mkv_title=mkv_title,
        fix_tags=fix_tags,
        notes=notes,
    )


def _build_sync_args(tracks: list[TrackInfo], delay_ms: int) -> list[str]:
    args = list[str]()
    for track in tracks:
        args.extend(["--sync", f"{track.index}:{delay_ms}"])
    return args


def plan_batch(donor_root: Path, target_root: Path, output_dir: Path, episode_offset: int = 0, fix_tags: bool = False) -> BatchPlan:
    donor_paths = scan_media_files(donor_root)
    target_paths = scan_media_files(target_root)
    matches, unmatched_donor, unmatched_target, ambiguous_donor, ambiguous_target = match_episode_paths(
        donor_paths,
        target_paths,
        offset=episode_offset,
    )

    plans = list[MuxPlan]()
    for match in matches:
        donor_source = inspect_source(match.donor, episode=match.episode)
        target_source = inspect_source(match.target, episode=match.episode)
        output = output_dir.resolve() / match.target.name
        plans.append(plan_pair(donor_source, target_source, output, fix_tags=fix_tags))

    return BatchPlan(
        donor_root=donor_root.resolve(),
        target_root=target_root.resolve(),
        output_dir=output_dir.resolve(),
        episode_offset=episode_offset,
        matches=plans,
        unmatched_donor=unmatched_donor,
        unmatched_target=unmatched_target,
        ambiguous_donor=ambiguous_donor,
        ambiguous_target=ambiguous_target,
    )


def inspect_path(path: Path) -> SourceFile:
    return inspect_source(path.resolve(), episode=parse_episode_key(path))
