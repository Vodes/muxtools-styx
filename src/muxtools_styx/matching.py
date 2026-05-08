from __future__ import annotations

import re
from pathlib import Path

from .models import EpisodeKey, PairMatch

MEDIA_EXTENSIONS = {".mkv", ".mp4", ".m2ts", ".ts"}
IGNORED_NUMBERS = {360, 480, 540, 576, 720, 1080, 1440, 2160}


def scan_media_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() in MEDIA_EXTENSIONS)


def parse_episode_key(path: Path) -> EpisodeKey | None:
    parsed = _parse_with_anitopy(path)
    if parsed is not None:
        return parsed
    return _parse_with_regex(path)


def match_episode_paths(donor_paths: list[Path], target_paths: list[Path], offset: int = 0) -> tuple[list[PairMatch], list[Path], list[Path], dict[str, list[Path]], dict[str, list[Path]]]:
    donor_index, donor_unknown = _index_episode_paths(donor_paths, offset=offset)
    target_index, target_unknown = _index_episode_paths(target_paths, offset=0)

    matches = list[PairMatch]()
    unmatched_donor = list(donor_unknown)
    unmatched_target = list(target_unknown)
    ambiguous_donor = dict[str, list[Path]]()
    ambiguous_target = dict[str, list[Path]]()

    all_keys = sorted(set(donor_index) | set(target_index), key=lambda key: (key.season or 0, key.number))
    for key in all_keys:
        donor_group = donor_index.get(key, [])
        target_group = target_index.get(key, [])

        if len(donor_group) > 1:
            ambiguous_donor[key.label()] = donor_group
            continue
        if len(target_group) > 1:
            ambiguous_target[key.label()] = target_group
            continue
        if donor_group and target_group:
            matches.append(PairMatch(episode=key, donor=donor_group[0], target=target_group[0]))
            continue
        if donor_group:
            unmatched_donor.extend(donor_group)
        if target_group:
            unmatched_target.extend(target_group)

    return matches, sorted(unmatched_donor), sorted(unmatched_target), ambiguous_donor, ambiguous_target


def _parse_with_anitopy(path: Path) -> EpisodeKey | None:
    try:
        import anitopy
    except ModuleNotFoundError:
        return None

    result = anitopy.parse(path.stem)
    if not result:
        return None

    episode_value = _coerce_to_int(result.get("episode_number"))
    if episode_value is None:
        return None
    season_value = _coerce_to_int(result.get("anime_season"))
    return EpisodeKey(number=episode_value, season=season_value, raw=path.stem)


def _parse_with_regex(path: Path) -> EpisodeKey | None:
    stem = path.stem

    direct_patterns = [
        r"\b(?:e|ep|episode)[\s._-]*(\d{1,4})\b",
        r"\b(\d{1,4})v\d\b",
    ]
    for pattern in direct_patterns:
        match = re.search(pattern, stem, re.IGNORECASE)
        if match is not None:
            return EpisodeKey(number=int(match.group(1)), raw=stem)

    candidates = [int(value) for value in re.findall(r"\b(\d{1,4})\b", stem) if int(value) not in IGNORED_NUMBERS]
    if not candidates:
        return None
    return EpisodeKey(number=candidates[-1], raw=stem)


def _coerce_to_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]
    if isinstance(value, str):
        value = value.strip()
        if not value.isdigit():
            return None
        return int(value)
    if isinstance(value, int):
        return value
    return None


def _index_episode_paths(paths: list[Path], offset: int) -> tuple[dict[EpisodeKey, list[Path]], list[Path]]:
    indexed = dict[EpisodeKey, list[Path]]()
    unknown = list[Path]()
    for path in paths:
        episode = parse_episode_key(path)
        if episode is None:
            unknown.append(path)
            continue
        if offset:
            episode = episode.apply_offset(offset)
        indexed.setdefault(episode, []).append(path)
    return indexed, unknown
