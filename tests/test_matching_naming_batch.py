from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from langcodes import Language
from muxtools import TrackInfo

from muxtools_styx.batch import preflight_batch
from muxtools_styx.matching import match_episode_paths, parse_episode_key, source_label
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


@dataclass
class Track:
    language: str
    title: str | None = None
    is_forced: bool = False
    type: str = "AUDIO"
    channels: int = 2

    @property
    def sanitized_lang(self) -> Language:
        return Language.get(self.language)

    @property
    def raw_ffprobe(self) -> SimpleNamespace:
        return SimpleNamespace(channels=self.channels, channel_layout=None)


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


def test_preflight_reports_duplicate_outputs(tmp_path: Path) -> None:
    (tmp_path / "Show - 01.mkv").touch()
    (tmp_path / "Show - 02.mkv").touch()
    preflight = preflight_batch(tmp_path, output_resolver=lambda _match: tmp_path / "same.mkv")
    assert not preflight.ok
    assert preflight.output_collisions == (tmp_path / "same.mkv",)
