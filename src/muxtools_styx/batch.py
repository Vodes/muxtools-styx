"""Batch discovery, preflight, and sequential mux dispatch.

Preflight is intentionally a value-producing operation.  It does not inspect
media tracks or invoke extraction, and therefore remains safe for ``--dry-run``
and for callers that want to review all collisions before starting a batch.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from muxtools import warn

from .matching import EpisodeKey, _index_episode_paths, format_episode, match_episode_paths, parse_episode_key, scan_media_files

if TYPE_CHECKING:
    from muxtools import ParsedFile

    from .selection import MuxOptions, Selection


class BatchValidationError(RuntimeError):
    """Raised when preflight finds an unsafe or ambiguous batch."""

    def __init__(self, preflight: BatchPreflight) -> None:
        self.preflight = preflight
        super().__init__(preflight.error_message())


@dataclass(frozen=True, slots=True)
class BatchMatch:
    """One accepted target and optional donor input."""

    episode: EpisodeKey
    target: Path
    donor: Path | None = None

    def to_dict(self) -> dict[str, object]:
        return {"episode": self.episode.to_dict(), "target": str(self.target), "donor": None if self.donor is None else str(self.donor)}


@dataclass(frozen=True, slots=True)
class BatchPreflight:
    """All match and safety diagnostics collected before muxing starts."""

    matches: tuple[BatchMatch, ...] = ()
    unmatched_targets: tuple[Path, ...] = ()
    unused_donors: tuple[Path, ...] = ()
    ambiguous_targets: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    ambiguous_donors: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    skipped: tuple[Path, ...] = ()
    outputs: tuple[Path, ...] = ()
    output_collisions: tuple[Path, ...] = ()
    parse_failures: tuple[Path, ...] = ()

    @property
    def ok(self) -> bool:
        unskipped_parse_failures = set(self.parse_failures) - set(self.skipped)
        return not (
            self.ambiguous_targets
            or self.ambiguous_donors
            or self.output_collisions
            or unskipped_parse_failures
            or (self.unmatched_targets and not self.skipped)
        )

    def error_message(self) -> str:
        problems: list[str] = []
        if self.ambiguous_targets:
            problems.append(f"ambiguous target episodes: {', '.join(sorted(self.ambiguous_targets))}")
        if self.ambiguous_donors:
            problems.append(f"ambiguous donor episodes: {', '.join(sorted(self.ambiguous_donors))}")
        unskipped_parse_failures = [path for path in self.parse_failures if path not in self.skipped]
        if unskipped_parse_failures:
            problems.append(f"unparseable media files: {', '.join(path.name for path in unskipped_parse_failures)}")
        if self.unmatched_targets and not self.skipped:
            problems.append(f"unmatched targets: {', '.join(path.name for path in self.unmatched_targets)}")
        if self.output_collisions:
            problems.append(f"output collisions: {', '.join(str(path) for path in self.output_collisions)}")
        return "; ".join(problems) or "batch preflight failed"

    def to_dict(self) -> dict[str, object]:
        return {
            "matches": [match.to_dict() for match in self.matches],
            "unmatched_targets": [str(path) for path in self.unmatched_targets],
            "unused_donors": [str(path) for path in self.unused_donors],
            "ambiguous_targets": {key: [str(path) for path in paths] for key, paths in self.ambiguous_targets.items()},
            "ambiguous_donors": {key: [str(path) for path in paths] for key, paths in self.ambiguous_donors.items()},
            "skipped": [str(path) for path in self.skipped],
            "outputs": [str(path) for path in self.outputs],
            "output_collisions": [str(path) for path in self.output_collisions],
            "parse_failures": [str(path) for path in self.parse_failures],
        }


@dataclass(frozen=True, slots=True)
class BatchResult:
    outputs: tuple[Path, ...] = ()
    skipped: tuple[Path, ...] = ()
    preflight: BatchPreflight | None = None

    def to_dict(self) -> dict[str, object]:
        return {"outputs": [str(path) for path in self.outputs], "skipped": [str(path) for path in self.skipped]}


def _as_tuple_map(value: dict[str, list[Path]]) -> dict[str, tuple[Path, ...]]:
    return {key: tuple(paths) for key, paths in value.items()}


def _default_output_path(target: Path, output_dir: Path | None) -> Path:
    return (output_dir / f"{target.stem}.mkv") if output_dir is not None else target.with_suffix(".mkv")


def _discover_batch(
    target_dir: str | Path,
    *,
    donor_dir: str | Path | None = None,
    donor_season: int | None = None,
    episode_offset: int = 0,
    skip_unmatched: bool = False,
) -> BatchPreflight:
    if donor_season is not None and donor_dir is None:
        raise ValueError("donor_season requires a donor directory")
    if episode_offset != 0 and donor_dir is None:
        warn("episode_offset is ignored without a donor directory.", preflight_batch)

    target_root = Path(target_dir)
    targets = scan_media_files(target_root)
    donor_root = Path(donor_dir) if donor_dir is not None else None
    donors = scan_media_files(donor_root) if donor_root is not None else []

    if donor_root is None:
        target_index, unknown_targets = _index_episode_paths(targets)
        parse_failures = tuple(unknown_targets)
        ambiguous_targets = {key.label(): tuple(paths) for key, paths in target_index.items() if len(paths) > 1}
        matches = tuple(BatchMatch(key, paths[0]) for key, paths in target_index.items() if len(paths) == 1)
        unmatched_targets = parse_failures
        ambiguous_donors: dict[str, tuple[Path, ...]] = {}
        unused_donors: tuple[Path, ...] = ()
    else:
        pairs, unused_donor, unmatched_target, ambiguous_donor, ambiguous_target = match_episode_paths(
            donors, targets, episode_offset, donor_season=donor_season
        )
        matches = tuple(BatchMatch(pair.episode, pair.target, pair.donor) for pair in pairs)
        unmatched_targets = tuple(unmatched_target)
        unused_donors = tuple(unused_donor)
        ambiguous_targets = _as_tuple_map(ambiguous_target)
        ambiguous_donors = _as_tuple_map(ambiguous_donor)
        parse_failures = tuple(path for path in unmatched_target if not _has_episode(path))

    skipped = unmatched_targets if skip_unmatched else ()
    return BatchPreflight(
        matches=matches,
        unmatched_targets=unmatched_targets,
        unused_donors=unused_donors,
        ambiguous_targets=ambiguous_targets,
        ambiguous_donors=ambiguous_donors,
        skipped=skipped,
        parse_failures=parse_failures,
    )


def _check_output_collisions(
    matches: tuple[BatchMatch, ...],
    outputs: list[Path],
    *,
    overwrite: bool,
    options: MuxOptions | None = None,
) -> tuple[Path, ...]:
    from .mux import can_edit_in_place

    collisions: list[Path] = []
    seen: set[Path] = set()
    for match, output in zip(matches, outputs, strict=True):
        resolved = output.expanduser().resolve()
        target_resolved = match.target.expanduser().resolve()
        donor_resolved = match.donor.expanduser().resolve() if match.donor is not None else None
        in_place = (
            options is not None
            and match.target.suffix.casefold() == ".mkv"
            and can_edit_in_place(options, match.donor, output, match.target, allow_implicit_in_place=False)
        )
        hits_donor = donor_resolved is not None and resolved == donor_resolved
        hits_target_illegally = resolved == target_resolved and not in_place
        exists_blocked = resolved.exists() and not overwrite and not in_place
        if resolved in seen or hits_donor or hits_target_illegally or exists_blocked:
            collisions.append(output)
        seen.add(resolved)
    return tuple(collisions)


def preflight_batch(
    target_dir: str | Path,
    *,
    donor_dir: str | Path | None = None,
    donor_season: int | None = None,
    episode_offset: int = 0,
    skip_unmatched: bool = False,
    output_dir: str | Path | None = None,
    output_resolver: Callable[[BatchMatch], Path] | None = None,
    overwrite: bool = False,
) -> BatchPreflight:
    """Discover files and validate every match before expensive mux work."""

    if output_dir is not None and output_resolver is not None:
        warn("output_dir is ignored when output_resolver is provided.", preflight_batch)
    preflight = _discover_batch(
        target_dir,
        donor_dir=donor_dir,
        donor_season=donor_season,
        episode_offset=episode_offset,
        skip_unmatched=skip_unmatched,
    )
    outputs = [
        Path(output_resolver(match))
        if output_resolver is not None
        else _default_output_path(match.target, Path(output_dir) if output_dir is not None else None)
        for match in preflight.matches
    ]
    collisions = _check_output_collisions(preflight.matches, outputs, overwrite=overwrite)
    return replace(preflight, outputs=tuple(outputs), output_collisions=collisions)


def _has_episode(path: Path) -> bool:
    return parse_episode_key(path) is not None


def process_batch(
    target_dir: str | Path,
    *,
    donor_dir: str | Path | None = None,
    donor_season: int | None = None,
    supplemental_info: str | None = None,
    donor_supplemental_info: str | None = None,
    episode_offset: int = 0,
    episode_padding: int = 2,
    skip_unmatched: bool = False,
    dry_run: bool = False,
    output_dir: str | Path | None = None,
    output_resolver: Callable[[BatchMatch, ParsedFile, Selection], Path] | None = None,
    overwrite: bool = False,
    options: MuxOptions | None = None,
    setup_factory: Callable[[BatchMatch, Path], None] | None = None,
) -> BatchResult | BatchPreflight:
    """Preflight and then process accepted pairs sequentially.

    No worker pool is used because muxtools' ``Setup`` is process-wide state.
    """
    from muxtools import ParsedFile

    from .selection import MuxOptions, select_tracks, validate_options

    if episode_padding < 2:
        raise ValueError("episode_padding must be at least 2")
    if output_dir is not None and output_resolver is not None:
        warn("output_dir is ignored when output_resolver is provided.", process_batch)
    mux_options = options or MuxOptions()
    validate_options(
        mux_options,
        Path(donor_dir) if donor_dir is not None else None,
        donor_supplemental_info=donor_supplemental_info,
    )

    preflight = _discover_batch(
        target_dir,
        donor_dir=donor_dir,
        donor_season=donor_season,
        episode_offset=episode_offset,
        skip_unmatched=skip_unmatched,
    )
    if not preflight.ok:
        raise BatchValidationError(preflight)

    parsed_cache: dict[Path, tuple[ParsedFile, ParsedFile | None, Selection]] = {}
    outputs: list[Path] = []
    for match in preflight.matches:
        if output_resolver is None and dry_run:
            outputs.append(_default_output_path(match.target, Path(output_dir) if output_dir is not None else None))
            continue
        target_info = ParsedFile.from_file(match.target, process_batch)
        donor_info = ParsedFile.from_file(match.donor, process_batch) if match.donor else None
        selection = select_tracks(
            target_info,
            donor_info,
            mux_options,
            target_supplemental_info=supplemental_info,
            donor_supplemental_info=donor_supplemental_info,
            warn_unused=False,
        )
        parsed_cache[match.target] = (target_info, donor_info, selection)
        if output_resolver is None:
            outputs.append(_default_output_path(match.target, Path(output_dir) if output_dir is not None else None))
        else:
            outputs.append(Path(output_resolver(match, target_info, selection)))

    collisions = _check_output_collisions(preflight.matches, outputs, overwrite=overwrite, options=mux_options)
    preflight = replace(preflight, outputs=tuple(outputs), output_collisions=collisions)
    if not preflight.ok:
        raise BatchValidationError(preflight)
    if dry_run:
        return preflight

    from .mux import can_edit_in_place, process_mux

    multi_season = len({match.episode.season for match in preflight.matches}) > 1
    results: list[Path] = []
    for match, output in zip(preflight.matches, preflight.outputs, strict=True):
        in_place = can_edit_in_place(mux_options, match.donor, output, match.target, allow_implicit_in_place=False)
        explicit_title: str | None = None
        if in_place:
            if mux_options.transforms.fix_tags:
                from .matching import parse_filename

                info = parse_filename(match.target)
                ep_str = format_episode(match.episode.number, episode_padding)
                explicit_title = f"{info.title or match.target.stem} - {ep_str}"
        elif setup_factory is not None:
            setup_factory(match, output)
        else:
            from muxtools import Setup

            from .matching import parse_filename

            info = parse_filename(match.target)
            ep_str = format_episode(match.episode.number, episode_padding)
            workdir_name = match.episode.label() if multi_season else ep_str
            Setup(
                episode=ep_str,
                show_name=info.title or match.target.stem,
                out_dir=str(output.parent),
                out_name=output.name,
                clean_work_dirs=True,
                work_dir=str(Path.cwd() / "_workdir" / workdir_name),
            )
        cached = parsed_cache.get(match.target)
        result = process_mux(
            match.target,
            donor=match.donor,
            supplemental_info=supplemental_info,
            donor_supplemental_info=donor_supplemental_info,
            options=mux_options,
            outfile=output,
            overwrite=overwrite,
            allow_implicit_in_place=False,
            explicit_mkv_title=explicit_title,
            _target_info=cached[0] if cached else None,
            _donor_info=cached[1] if cached else None,
            _selection=cached[2] if cached else None,
            _warn_options=False,
        )
        results.append(Path(result))
    return BatchResult(tuple(results), preflight.skipped, preflight)


__all__ = [
    "BatchMatch",
    "BatchPreflight",
    "BatchResult",
    "BatchValidationError",
    "preflight_batch",
    "process_batch",
]
