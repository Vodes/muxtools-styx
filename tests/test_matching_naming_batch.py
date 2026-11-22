from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from langcodes import Language
from muxtools import TrackInfo

from muxtools_styx.batch import preflight_batch
from muxtools_styx.matching import EpisodeKey, match_episode_paths, parse_episode_key, source_label
from muxtools_styx.naming import SelectedTrack, display_language, normalize_audio_title, normalize_subtitle_title


def test_episode_keys_ignore_filename_for_target_donor_matching() -> None:
    matches, unused_donor, unmatched_target, ambiguous_donor, ambiguous_target = match_episode_paths(
        [Path("[Amazon] Different Name - 02.mkv")],
        [Path("[Crunchyroll] Target Name - 03.mkv")],
        offset=1,
    )

    assert len(matches) == 1
    assert matches[0].episode.number == 3
    assert not unused_donor and not unmatched_target
    assert not ambiguous_donor and not ambiguous_target


def test_parse_episode_key_rejects_ranges() -> None:
    assert parse_episode_key(Path("Show - 01-02.mkv")) is None


@pytest.mark.parametrize("donor_name", ["Show 2 E01.mkv", "Show.S01E01.mkv"])
@pytest.mark.parametrize("season", [0, 2])
def test_donor_season_override_with_episode_offset(donor_name: str, season: int) -> None:
    donor = Path(donor_name)
    target = Path(f"Show.S{season:02d}E02.mkv")
    matches, unused, unmatched, ambiguous_donor, ambiguous_target = match_episode_paths([donor], [target], offset=1, donor_season=season)
    assert len(matches) == 1
    assert matches[0].episode == EpisodeKey(2, season)
    assert matches[0].donor == donor
    assert matches[0].target == target
    assert not unused and not unmatched and not ambiguous_donor and not ambiguous_target


def test_missing_season_does_not_match_automatically() -> None:
    donor = Path("Show 2 E01.mkv")
    target = Path("Show.S02E01.mkv")
    matches, unused, unmatched, _, _ = match_episode_paths([donor], [target])
    assert not matches
    assert unused == [donor]
    assert unmatched == [target]


def test_donor_season_override_preserves_duplicate_and_range_checks() -> None:
    donors = [Path("Show.S01E01.mkv"), Path("Show.S02E01.mkv"), Path("Show - 02-03.mkv")]
    matches, unused, _, ambiguous_donor, _ = match_episode_paths(donors, ["Show.S02E01.mkv"], donor_season=2)
    assert not matches
    assert unused == [donors[2]]
    assert ambiguous_donor == {"S02E01": donors[:2]}


def test_batch_donor_season_override_matches_edgerunners(tmp_path: Path) -> None:
    target_dir = tmp_path / "targets"
    donor_dir = tmp_path / "donors"
    target_dir.mkdir()
    donor_dir.mkdir()
    for episode in range(1, 11):
        (target_dir / f"Cyberpunk.Edgerunners.S02E{episode:02d}.2160p.NF.WEB-DL.DDP5.1.HEVC-NTb.mkv").touch()
        (donor_dir / f"Cyberpunk Edgerunners 2 E{episode:02d} [1080p][E-AC-3][GerJapDub][GerEngSub][Web-DL].mkv").touch()
    result = preflight_batch(target_dir, donor_dir=donor_dir, donor_season=2, output_dir=tmp_path / "muxed")
    assert result.ok
    assert [match.episode for match in result.matches] == [EpisodeKey(episode, 2) for episode in range(1, 11)]
    assert not result.unused_donors and not result.unmatched_targets


def test_donor_season_override_requires_donors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="donor_season requires a donor directory"):
        preflight_batch(tmp_path, donor_season=2)


def test_donor_season_override_rejects_negative_season() -> None:
    with pytest.raises(ValueError, match="donor_season must be non-negative"):
        match_episode_paths([], [], donor_season=-1)


@dataclass
class Track:
    language: str
    title: str | None = None
    is_forced: bool = False
    flag_hearing_impaired: bool | None = None
    disposition: object = field(default_factory=dict)
    type: str = "AUDIO"
    channels: int = 2

    @property
    def sanitized_lang(self) -> Language:
        return Language.get(self.language)

    @property
    def raw_ffprobe(self) -> SimpleNamespace:
        return SimpleNamespace(channels=self.channels, channel_layout=None, disposition=self.disposition)

    @property
    def raw_mkvmerge(self) -> SimpleNamespace:
        return SimpleNamespace(properties=SimpleNamespace(flag_hearing_impaired=self.flag_hearing_impaired))


def test_audio_source_alias_and_channels() -> None:
    selected = SelectedTrack(cast(TrackInfo, Track("jpn")), Path("[Group] Show - 01 [1080p CR].mkv"))
    assert normalize_audio_title(selected) == "Japanese 2.0 (Crunchyroll)"


def test_first_recognized_service_source_is_used() -> None:
    assert source_label("Show.S01E01.WEB-DL.AMZN.mkv") == "Amazon"


def test_additional_source_aliases() -> None:
    assert source_label("Show.S01E01.DSNP.mkv") == "Disney+"
    assert source_label("Show.S01E01.D+.mkv") == "Disney+"
    assert source_label("Show.S01E01.AMZ.mkv") == "Amazon"
    assert source_label("Show.S01E01.AMZ-ANV.mkv") == "Aniverse"
    assert source_label("Show.S01E01.HIDI.mkv") == "Hidive"
    assert source_label("Show.S01E01.BILI.mkv") == "Bilibili"
    assert source_label("Show.S01E01.BILIBILI.mkv") == "Bilibili"
    assert source_label("Show S01E01 [BILIBILI COM].mkv") == "Bilibili"
    assert source_label("Show.S01E01.BSite.mkv") == "Bilibili"
    assert source_label("Show.S01E01.ADN.mkv") == "ADN"


def test_supplemental_info_supplies_missing_source_without_overriding_filename() -> None:
    supplemental = "Temppal Item no Chikara (Overgeared) [GerJapDub,GerEngSub,CR]"
    assert source_label("Temppal Item no Chikara E01 [1080p][AAC][GerJapDub][GerEngSub][Web-DL].mkv", supplemental) == "Crunchyroll"
    assert source_label("Show.S01E01.NF.mkv", supplemental) == "Netflix"


def test_supplemental_source_is_used_in_normalized_track_title() -> None:
    selected = SelectedTrack(
        cast(TrackInfo, Track("jpn")),
        Path("Temppal Item no Chikara E01 [1080p][AAC][Web-DL].mkv"),
        "Temppal Item no Chikara (Overgeared) [GerJapDub,GerEngSub,CR]",
    )
    assert normalize_audio_title(selected) == "Japanese 2.0 (Crunchyroll)"


def test_language_display_uses_langcodes_data() -> None:
    assert display_language(cast(TrackInfo, Track("enm"))) == "Middle English"


def test_subtitle_local_provenance_survives_honorific_cleanup() -> None:
    selected = SelectedTrack(cast(TrackInfo, Track("eng", "Full Subtitles [sam] (Honorifics)", type="SUB")), Path("Show - 01 [CR].mkv"))
    assert normalize_subtitle_title(selected) == "English [sam] (Crunchyroll)"


def test_subtitle_ccc_conversion_and_source_are_preserved() -> None:
    selected = SelectedTrack(cast(TrackInfo, Track("eng", "Full Subtitles (CCC Converted)", type="SUB")), Path("Show - 01 [CR].mkv"))
    assert normalize_subtitle_title(selected) == "English (CCC Converted) (Crunchyroll)"


def test_subtitle_suffix_order_is_preserved_before_source() -> None:
    selected = SelectedTrack(
        cast(TrackInfo, Track("eng", "Full Subtitles [sam] (CCC Converted)", type="SUB")),
        Path("Show - 01 [CR].mkv"),
    )
    assert normalize_subtitle_title(selected) == "English [sam] (CCC Converted) (Crunchyroll)"


@pytest.mark.parametrize(
    ("language", "title", "hi", "disposition", "expected"),
    [
        ("eng", "CC", None, {}, "English CC (Crunchyroll)"),
        ("eng", "CC", True, {}, "English CC (Crunchyroll)"),
        ("eng", "English [CC]", None, {}, "English CC (Crunchyroll)"),
        ("eng", "English (Closed Captions)", None, {}, "English CC (Crunchyroll)"),
        ("eng", None, None, {"captions": 1}, "English CC (Crunchyroll)"),
        ("eng", None, None, SimpleNamespace(captions=1, hearing_impaired=0), "English CC (Crunchyroll)"),
        ("eng", None, None, SimpleNamespace(captions=0, hearing_impaired=1), "English SDH (Crunchyroll)"),
        ("eng", "SDH", True, {}, "English SDH (Crunchyroll)"),
        ("ger", "SDH", True, {}, "German SDH (Crunchyroll)"),
        ("es-419", "Latin American (SDH)", True, {}, "Spanish (Latin America) SDH (Crunchyroll)"),
        ("es-ES", "European (SDH)", True, {}, "Spanish (Spain) SDH (Crunchyroll)"),
        ("pt-BR", "Brazilian (SDH)", True, {}, "Portuguese (Brazil) SDH (Crunchyroll)"),
        ("eng", "English [sam] (SDH)", True, {}, "English SDH [sam] (Crunchyroll)"),
        ("eng", "English (Hearing Impaired)", None, {}, "English SDH (Crunchyroll)"),
        ("eng", None, True, {}, "English SDH (Crunchyroll)"),
        ("eng", "English (Dubtitles)", None, {}, "English Dubtitles (Crunchyroll)"),
        ("eng", "Dub", None, {}, "English Dubtitles (Crunchyroll)"),
        ("eng", None, False, {"dub": 1}, "English (Crunchyroll)"),
    ],
)
def test_subtitle_cc_sdh_and_dubtitle_normalization(
    language: str,
    title: str | None,
    hi: bool | None,
    disposition: object,
    expected: str,
) -> None:
    selected = SelectedTrack(
        cast(TrackInfo, Track(language, title, flag_hearing_impaired=hi, disposition=disposition, type="SUB")),
        Path("Show - 01 [CR].mkv"),
    )
    assert normalize_subtitle_title(selected) == expected


def test_preflight_reports_duplicate_outputs(tmp_path: Path) -> None:
    (tmp_path / "Show - 01.mkv").touch()
    (tmp_path / "Show - 02.mkv").touch()
    preflight = preflight_batch(tmp_path, output_resolver=lambda _match: tmp_path / "same.mkv")
    assert not preflight.ok
    assert preflight.output_collisions == (tmp_path / "same.mkv",)
