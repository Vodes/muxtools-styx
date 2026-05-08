from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

TrackKind = Literal["video", "audio", "subtitle", "attachment", "chapters", "mkv", "unknown"]


@dataclass(frozen=True, slots=True)
class EpisodeKey:
    number: int
    season: int | None = None
    raw: str | None = field(default=None, compare=False)

    def apply_offset(self, offset: int) -> "EpisodeKey":
        return EpisodeKey(number=self.number + offset, season=self.season, raw=self.raw)

    def label(self) -> str:
        if self.season is None:
            return f"{self.number:02d}"
        return f"S{self.season:02d}E{self.number:02d}"

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "number": self.number,
            "season": self.season,
            "raw": self.raw,
            "label": self.label(),
        }


@dataclass(frozen=True, slots=True)
class TrackInfo:
    index: int
    relative_index: int
    kind: TrackKind
    codec_name: str
    codec_long_name: str | None = None
    bit_rate: int | None = None
    language: str | None = None
    title: str | None = None
    is_default: bool = False
    is_forced: bool = False
    container_delay: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "relative_index": self.relative_index,
            "kind": self.kind,
            "codec_name": self.codec_name,
            "codec_long_name": self.codec_long_name,
            "bit_rate": self.bit_rate,
            "language": self.language,
            "title": self.title,
            "is_default": self.is_default,
            "is_forced": self.is_forced,
            "container_delay": self.container_delay,
        }


@dataclass(slots=True)
class SourceFile:
    path: Path
    tracks: list[TrackInfo] = field(default_factory=list)
    episode: EpisodeKey | None = None
    container_format: str | None = None
    container_title: str | None = None
    is_video_file: bool = True

    @property
    def video_tracks(self) -> list[TrackInfo]:
        return [track for track in self.tracks if track.kind == "video"]

    @property
    def audio_tracks(self) -> list[TrackInfo]:
        return [track for track in self.tracks if track.kind == "audio"]

    @property
    def subtitle_tracks(self) -> list[TrackInfo]:
        return [track for track in self.tracks if track.kind == "subtitle"]

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "episode": None if self.episode is None else self.episode.to_dict(),
            "container_format": self.container_format,
            "container_title": self.container_title,
            "is_video_file": self.is_video_file,
            "tracks": [track.to_dict() for track in self.tracks],
        }


@dataclass(frozen=True, slots=True)
class TrackRef:
    source: Path
    track: TrackInfo
    reason: str

    def to_dict(self) -> dict[str, object]:
        data = self.track.to_dict()
        data["source"] = str(self.source)
        data["reason"] = self.reason
        return data


@dataclass(slots=True)
class SelectionPlan:
    video: list[TrackRef] = field(default_factory=list)
    audio: list[TrackRef] = field(default_factory=list)
    subtitles: list[TrackRef] = field(default_factory=list)
    attachments_from: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "video": [track.to_dict() for track in self.video],
            "audio": [track.to_dict() for track in self.audio],
            "subtitles": [track.to_dict() for track in self.subtitles],
            "attachments_from": [str(path) for path in self.attachments_from],
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class SubtitleTransform:
    source: Path
    relative_index: int
    language: str | None
    title: str | None
    is_default: bool
    is_forced: bool
    kind: str = "restyle"

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "relative_index": self.relative_index,
            "language": self.language,
            "title": self.title,
            "is_default": self.is_default,
            "is_forced": self.is_forced,
            "kind": self.kind,
        }


@dataclass(slots=True)
class MuxPlan:
    mode: str
    output: Path
    sources: list[Path]
    selection: SelectionPlan
    subtitle_transforms: list[SubtitleTransform] = field(default_factory=list)
    source_args: dict[str, list[str]] = field(default_factory=dict)
    mkv_title: str | None = None
    fix_tags: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "output": str(self.output),
            "sources": [str(path) for path in self.sources],
            "selection": self.selection.to_dict(),
            "subtitle_transforms": [transform.to_dict() for transform in self.subtitle_transforms],
            "source_args": self.source_args,
            "mkv_title": self.mkv_title,
            "fix_tags": self.fix_tags,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class PairMatch:
    episode: EpisodeKey
    donor: Path
    target: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "episode": self.episode.to_dict(),
            "donor": str(self.donor),
            "target": str(self.target),
        }


@dataclass(slots=True)
class BatchPlan:
    donor_root: Path
    target_root: Path
    output_dir: Path
    episode_offset: int
    matches: list[MuxPlan] = field(default_factory=list)
    unmatched_donor: list[Path] = field(default_factory=list)
    unmatched_target: list[Path] = field(default_factory=list)
    ambiguous_donor: dict[str, list[Path]] = field(default_factory=dict)
    ambiguous_target: dict[str, list[Path]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "donor_root": str(self.donor_root),
            "target_root": str(self.target_root),
            "output_dir": str(self.output_dir),
            "episode_offset": self.episode_offset,
            "matches": [match.to_dict() for match in self.matches],
            "unmatched_donor": [str(path) for path in self.unmatched_donor],
            "unmatched_target": [str(path) for path in self.unmatched_target],
            "ambiguous_donor": {key: [str(path) for path in paths] for key, paths in self.ambiguous_donor.items()},
            "ambiguous_target": {key: [str(path) for path in paths] for key, paths in self.ambiguous_target.items()},
        }
