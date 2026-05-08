from pathlib import Path

from muxtools_styx.matching import match_episode_paths, parse_episode_key


def test_parse_episode_key_falls_back_to_regex() -> None:
    episode = parse_episode_key(Path("[SubsPlease] Example Show - 03 [1080p].mkv"))

    assert episode is not None
    assert episode.number == 3


def test_match_episode_paths_applies_offset_to_donor_side() -> None:
    donor_paths = [Path("Donor Show - 02.mkv")]
    target_paths = [Path("Target Show - 03.mkv")]

    matches, unmatched_donor, unmatched_target, ambiguous_donor, ambiguous_target = match_episode_paths(
        donor_paths,
        target_paths,
        offset=1,
    )

    assert len(matches) == 1
    assert matches[0].episode.number == 3
    assert not unmatched_donor
    assert not unmatched_target
    assert not ambiguous_donor
    assert not ambiguous_target
