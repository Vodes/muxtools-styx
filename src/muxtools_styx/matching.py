"""Filename parsing and deterministic target/donor matching.

The native Anitomy binding is deliberately kept at the edge of this module.  The
matching policy only needs a title, season, and episode; preserving the complete
ordered element list in :class:`FilenameInfo` lets callers use the other values
without making the parser pretend to be a metadata database.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ._anitomy import Element, ElementKind, parse

MEDIA_EXTENSIONS = frozenset({".mkv", ".mp4", ".m2ts", ".ts", ".webm", ".mov", ".avi"})
SOURCE_NAMES = {
    "CR": "Crunchyroll",
    "CRUNCHYROLL": "Crunchyroll",
    "AMZN": "Amazon",
    "AMAZON": "Amazon",
    "NF": "Netflix",
    "NETFLIX": "Netflix",
}


@dataclass(frozen=True, slots=True)
class EpisodeKey:
    """The season/episode identity used for matching.

    ``raw`` is informational only and intentionally excluded from equality so
    differently named target and donor releases can still match.
    """

    number: int
    season: int | None = None
    raw: str | None = field(default=None, compare=False)

    def apply_offset(self, offset: int) -> EpisodeKey:
        return EpisodeKey(self.number + offset, self.season, self.raw)

    def label(self) -> str:
        return f"S{self.season:02d}E{self.number:02d}" if self.season is not None else f"{self.number:02d}"

    def __str__(self) -> str:
        return self.label()

    def to_dict(self) -> dict[str, int | str | None]:
        return {"number": self.number, "season": self.season, "raw": self.raw, "label": self.label()}


@dataclass(frozen=True, slots=True)
class FilenameInfo:
    """Ordered parser output and the fields used by batch matching."""

    path: Path
    elements: tuple[Element, ...] = ()
    title: str | None = None
    season: int | None = None
    episode: int | None = None
    source: str | None = None
    release_group: str | None = None
    multi_episode: bool = False

    @property
    def key(self) -> EpisodeKey | None:
        if self.episode is None or self.multi_episode:
            return None
        return EpisodeKey(self.episode, self.season, self.path.stem)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "title": self.title,
            "season": self.season,
            "episode": self.episode,
            "source": self.source,
            "release_group": self.release_group,
            "multi_episode": self.multi_episode,
            "elements": [element_to_dict(element) for element in self.elements],
        }


@dataclass(frozen=True, slots=True)
class PairMatch:
    """A target/donor pair accepted by the matcher."""

    episode: EpisodeKey
    donor: Path
    target: Path

    @property
    def key(self) -> EpisodeKey:
        return self.episode

    def to_dict(self) -> dict[str, object]:
        return {"episode": self.episode.to_dict(), "donor": str(self.donor), "target": str(self.target)}


def element_value(element: Element) -> str:
    return element.value


def element_to_dict(element: Element) -> dict[str, object]:
    return {"kind": element.kind.name, "value": element.value, "position": element.position}


def first_element(elements: Iterable[Element], kind: ElementKind) -> Element | None:
    """Return the first ordered element with ``kind`` (or ``None``)."""

    return next((element for element in elements if element.kind is kind), None)


def element_values(elements: Iterable[Element], kind: ElementKind) -> list[str]:
    """Return all values for a kind while retaining parser order and duplicates."""

    return [element.value for element in elements if element.kind is kind]


def _int_value(value: object) -> int | None:
    text = str(value).strip()
    if not re.fullmatch(r"\d{1,4}", text):
        return None
    return int(text)


def _find_int(elements: Sequence[Element], kind: ElementKind) -> tuple[int | None, bool]:
    for element in elements:
        if element.kind is not kind:
            continue
        number = _int_value(element.value)
        if number is not None:
            return number, False
    return None, False


def parse_filename(path: str | Path) -> FilenameInfo:
    """Parse one filename using native Anitomy, with a conservative fallback."""

    path = Path(path)
    elements = tuple(parse(path.name))
    episode_values = element_values(elements, ElementKind.EPISODE)
    episode, multi = _find_int(elements, ElementKind.EPISODE)
    multi = multi or len(episode_values) > 1
    season, season_multi = _find_int(elements, ElementKind.SEASON)
    multi = multi or season_multi

    title_element = first_element(elements, ElementKind.TITLE)
    source_element = first_element(elements, ElementKind.SOURCE)
    group_element = first_element(elements, ElementKind.RELEASE_GROUP)
    title = element_value(title_element).strip() if title_element is not None else None
    source = element_value(source_element).strip() if source_element is not None else None
    release_group = element_value(group_element).strip() if group_element is not None else None

    return FilenameInfo(path, elements, title or None, season, episode, source or None, release_group or None, multi)


def parse_episode_key(path: str | Path) -> EpisodeKey | None:
    return parse_filename(path).key


def source_label(path: str | Path) -> str | None:
    for value in element_values(parse_filename(path).elements, ElementKind.SOURCE):
        source = value.strip().strip("[](){}").strip()
        if label := SOURCE_NAMES.get(source.upper()):
            return label
    return None


def scan_media_files(root: str | Path) -> list[Path]:
    """Scan immediate regular media files in deterministic filename order."""

    root = Path(root)
    return sorted(
        (path for path in root.iterdir() if path.is_file() and path.suffix.casefold() in MEDIA_EXTENSIONS),
        key=lambda path: (path.name.casefold(), path.name),
    )


def _index_episode_paths(paths: Iterable[Path], offset: int = 0) -> tuple[dict[EpisodeKey, list[Path]], list[Path]]:
    indexed: dict[EpisodeKey, list[Path]] = {}
    unknown: list[Path] = []
    for path in sorted((Path(item) for item in paths), key=lambda item: item.name.casefold()):
        key = parse_episode_key(path)
        if key is None:
            unknown.append(path)
            continue
        shifted = key.apply_offset(offset) if offset else key
        indexed.setdefault(shifted, []).append(path)
    return indexed, unknown


def match_episode_paths(
    donor_paths: Iterable[str | Path], target_paths: Iterable[str | Path], offset: int = 0
) -> tuple[list[PairMatch], list[Path], list[Path], dict[str, list[Path]], dict[str, list[Path]]]:
    """Match donor files to targets by season/episode.

    The offset is applied only to donor keys.  The five-tuple return is kept
    intentionally simple for callers that need to render detailed diagnostics.
    """

    donor_index, donor_unknown = _index_episode_paths((Path(path) for path in donor_paths), offset)
    target_index, target_unknown = _index_episode_paths(Path(path) for path in target_paths)
    matches: list[PairMatch] = []
    unmatched_donor = list(donor_unknown)
    unmatched_target = list(target_unknown)
    ambiguous_donor: dict[str, list[Path]] = {}
    ambiguous_target: dict[str, list[Path]] = {}

    for key in sorted(set(donor_index) | set(target_index), key=lambda item: (item.season is None, item.season or 0, item.number)):
        donors = donor_index.get(key, [])
        targets = target_index.get(key, [])
        if len(donors) > 1:
            ambiguous_donor[key.label()] = donors
        if len(targets) > 1:
            ambiguous_target[key.label()] = targets
        if len(donors) == 1 and len(targets) == 1:
            matches.append(PairMatch(key, donors[0], targets[0]))
        elif len(donors) == 1 and not targets:
            unmatched_donor.extend(donors)
        elif len(targets) == 1 and not donors:
            unmatched_target.extend(targets)

    return (
        matches,
        sorted(unmatched_donor, key=lambda item: item.name.casefold()),
        sorted(unmatched_target, key=lambda item: item.name.casefold()),
        ambiguous_donor,
        ambiguous_target,
    )


__all__ = [
    "MEDIA_EXTENSIONS",
    "SOURCE_NAMES",
    "EpisodeKey",
    "FilenameInfo",
    "PairMatch",
    "element_to_dict",
    "element_value",
    "element_values",
    "first_element",
    "match_episode_paths",
    "parse_episode_key",
    "parse_filename",
    "scan_media_files",
    "source_label",
]
