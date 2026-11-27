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
    assert source_label("Show.S01E01.Disney+.mkv") == "Disney+"
    assert source_label("Show.S01E01.AMZ.mkv") == "Amazon"
    assert source_label("Show.S01E01.Amazon.mkv") == "Amazon"
    assert source_label("Show.S01E01.AMZ-ANV.mkv") == "Aniverse"
    assert source_label("Show.S01E01.Aniverse.mkv") == "Aniverse"
    assert source_label("Show.S01E01.HIDI.mkv") == "Hidive"
    assert source_label("Show.S01E01.Hidive.mkv") == "Hidive"
    assert source_label("Show.S01E01.BILI.mkv") == "Bilibili"
    assert source_label("Show.S01E01.BILIBILI.mkv") == "Bilibili"
    assert source_label("Show S01E01 [BILIBILI COM].mkv") == "Bilibili"
    assert source_label("Show.S01E01.BSite.mkv") == "Bilibili"
    assert source_label("Show.S01E01.ADN.mkv") == "ADN"


def test_supplemental_info_supplies_missing_source_without_overriding_filename() -> None:
    supplemental = "Temppal Item no Chikara (Overgeared) [GerJapDub,GerEngSub,CR]"
    assert source_label("Temppal Item no Chikara E01 [1080p][AAC][GerJapDub][GerEngSub][Web-DL].mkv", supplemental) == "Crunchyroll"
    assert source_label("Show.S01E01.NF.mkv", supplemental) == "Netflix"
    assert source_label("Show E01 [Web-DL].mkv", "Show [CR] 1080p/AAC") == "Crunchyroll"
    assert source_label("Show E01 [Web-DL].mkv", "Amazon") == "Amazon"


def test_supplemental_source_is_used_in_normalized_track_title() -> None:
    selected = SelectedTrack(
        cast(TrackInfo, Track("jpn")),
        Path("Temppal Item no Chikara E01 [1080p][AAC][Web-DL].mkv"),
        "Temppal Item no Chikara (Overgeared) [GerJapDub,GerEngSub,CR]",
    )
    assert normalize_audio_title(selected) == "Japanese 2.0 (Crunchyroll)"


def test_language_display_uses_langcodes_data() -> None:
    assert display_language(cast(TrackInfo, Track("enm"))) == "English"
    assert display_language(cast(TrackInfo, Track("enm")), treat_enm_as_english=False) == "Middle English"


def test_subtitle_local_provenance_preserves_honorifics_without_duplication() -> None:
    selected = SelectedTrack(cast(TrackInfo, Track("eng", "Full Subtitles [sam] (Honorifics)", type="SUB")), Path("Show - 01 [CR].mkv"))
    assert normalize_subtitle_title(selected) == "English (Honorifics) [sam]"
    rerun = SelectedTrack(cast(TrackInfo, Track("eng", "English (Honorifics) [sam]", type="SUB")), Path("Show - 01 [CR].mkv"))
    assert normalize_subtitle_title(rerun) == "English (Honorifics) [sam]"


def test_enm_track_mentions_honorifics_and_respects_opt_out() -> None:
    enm_track = SelectedTrack(cast(TrackInfo, Track("enm", "Full Subtitles [sam]", type="SUB")), Path("Show - 01 [CR].mkv"))
    assert normalize_subtitle_title(enm_track) == "English (Honorifics) [sam]"
    assert normalize_subtitle_title(enm_track, treat_enm_as_english=False) == "Middle English [sam]"
    enm_cr = SelectedTrack(cast(TrackInfo, Track("enm", "Full Subtitles", type="SUB")), Path("Show - 01 [CR].mkv"))
    assert normalize_subtitle_title(enm_cr) == "English (Honorifics) (Crunchyroll)"
    enm_signs = SelectedTrack(cast(TrackInfo, Track("enm", "Signs & Songs [sam]", type="SUB")), Path("Show - 01 [CR].mkv"))
    assert normalize_subtitle_title(enm_signs) == "English Signs/Songs (Honorifics) [sam]"
    no_honorifics = SelectedTrack(cast(TrackInfo, Track("eng", "English (No Honorifics)", type="SUB")), Path("Show - 01 [CR].mkv"))
    assert normalize_subtitle_title(no_honorifics) == "English (No Honorifics)"


def test_subtitle_ccc_conversion_and_source_are_preserved() -> None:
    selected = SelectedTrack(cast(TrackInfo, Track("eng", "Full Subtitles (CCC Converted)", type="SUB")), Path("Show - 01 [CR].mkv"))
    assert normalize_subtitle_title(selected) == "English (CCC Converted) (Crunchyroll)"


def test_subtitle_suffix_order_is_preserved_without_duplicate_source() -> None:
    selected = SelectedTrack(
        cast(TrackInfo, Track("eng", "Full Subtitles [sam] (CCC Converted)", type="SUB")),
        Path("Show - 01 [CR].mkv"),
    )
    assert normalize_subtitle_title(selected) == "English [sam] (CCC Converted)"


@pytest.mark.parametrize(
    ("language", "title", "filename", "expected"),
    [
        ("eng", "English (Crunchyroll)", "[sam] Show - 01 [1080p CR].mkv", "English (Crunchyroll)"),
        ("ger", "German (Amazon)", "donor.mkv", "German (Amazon)"),
        ("eng", "English (CR)", "Show - 01 [CR].mkv", "English (Crunchyroll)"),
        ("eng", "English (Forced)", "Show - 01 [CR].mkv", "English Signs/Songs (Crunchyroll)"),
        ("eng", "English (Force)", "Show - 01 [CR].mkv", "English Signs/Songs (Crunchyroll)"),
        ("eng", "Signs & Songs [sam]", "[sam] Show - 01 [1080p CR].mkv", "English Signs/Songs [sam]"),
        ("es-419", "Spanish (Latin America)", "Show - 01 [CR].mkv", "Spanish (Latin America) (Crunchyroll)"),
        ("eng", "Full Subtitles", "[GJM] Show - 01 [1080p BD].mkv", "English"),
    ],
)
def test_subtitle_normalization_is_idempotent_and_avoids_group_fallback(language: str, title: str, filename: str, expected: str) -> None:
    selected = SelectedTrack(cast(TrackInfo, Track(language, title, type="SUB")), Path(filename))
    assert normalize_subtitle_title(selected) == expected


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
        ("eng", "English [sam] (SDH)", True, {}, "English SDH [sam]"),
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


def test_preflight_ignores_unparseable_donors_and_skip_unmatched_skips_unparseable_targets(tmp_path: Path) -> None:
    target_dir = tmp_path / "targets"
    donor_dir = tmp_path / "donors"
    target_dir.mkdir()
    donor_dir.mkdir()
    (target_dir / "Show - 01.mkv").touch()
    (target_dir / "NCOP.mkv").touch()
    (donor_dir / "Show - 01.mkv").touch()
    (donor_dir / "Show - 01-02.mkv").touch()
    (donor_dir / "PV.mkv").touch()

    preflight_strict = preflight_batch(target_dir, donor_dir=donor_dir, output_dir=tmp_path / "out")
    assert not preflight_strict.ok
    assert [path.name for path in preflight_strict.parse_failures] == ["NCOP.mkv"]
    assert {path.name for path in preflight_strict.unused_donors} == {"PV.mkv", "Show - 01-02.mkv"}

    preflight_skip = preflight_batch(target_dir, donor_dir=donor_dir, skip_unmatched=True, output_dir=tmp_path / "out")
    assert preflight_skip.ok
    assert [path.name for path in preflight_skip.skipped] == ["NCOP.mkv"]
    assert preflight_skip.to_dict()["outputs"] == [str(tmp_path / "out" / "Show - 01.mkv")]

    donor_free_skip = preflight_batch(target_dir, skip_unmatched=True, output_dir=tmp_path / "out")
    assert donor_free_skip.ok
    assert [path.name for path in donor_free_skip.skipped] == ["NCOP.mkv"]


def test_parse_episode_key_rejects_multi_season() -> None:
    assert parse_episode_key(Path("Show S01-S02 E01.mkv")) is None


def test_process_batch_default_setup_works_and_defers_probing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from muxtools import ParsedFile

    from muxtools_styx import batch as batch_module
    from muxtools_styx import mux as mux_module
    from muxtools_styx import selection as selection_module
    from muxtools_styx.selection import MuxOptions, Selection, TransformOptions

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("vof_setup", "{}")
    target_dir = tmp_path / "targets"
    target_dir.mkdir()
    ep1 = target_dir / "Show - 01.mkv"
    ep1.touch()

    # Match validation fails before any media probing happens.
    (target_dir / "NCOP.mkv").touch()
    monkeypatch.setattr(ParsedFile, "from_file", lambda *_args: pytest.fail("should not probe before match validation"))
    with pytest.raises(batch_module.BatchValidationError):
        batch_module.process_batch(target_dir, output_dir=tmp_path / "out")

    (target_dir / "NCOP.mkv").unlink()
    probes: list[Path] = []
    parsed = cast(ParsedFile, object())
    monkeypatch.setattr(ParsedFile, "from_file", lambda path, *_args: probes.append(Path(path)) or parsed)
    monkeypatch.setattr(selection_module, "select_tracks", lambda *_args, **_kwargs: Selection((), (), (), ep1))
    monkeypatch.setattr(mux_module, "process_mux", lambda target, *, outfile=None, **_kwargs: Path(outfile or target))

    # Content-changing output == target fails preflight even with overwrite=True.
    with pytest.raises(batch_module.BatchValidationError, match="output collisions"):
        batch_module.process_batch(
            target_dir,
            overwrite=True,
            options=MuxOptions(transforms=TransformOptions(restyle_subs=True)),
        )

    # Default setup succeeds without config_file TypeError and probes each file once.
    probes.clear()
    result = batch_module.process_batch(target_dir, output_dir=tmp_path / "out")
    assert isinstance(result, batch_module.BatchResult)
    assert result.outputs == (tmp_path / "out" / "Show - 01.mkv",)
    assert probes == [ep1]

    # preflight_batch rejects output == target even with overwrite=True.
    assert not preflight_batch(target_dir, overwrite=True).ok

    # In-place metadata-only batch skips creating _workdir/.
    in_place_dir = tmp_path / "in_place_cwd"
    in_place_dir.mkdir()
    monkeypatch.chdir(in_place_dir)
    in_place_result = batch_module.process_batch(
        target_dir,
        options=MuxOptions(transforms=TransformOptions(fix_tags=True)),
    )
    assert isinstance(in_place_result, batch_module.BatchResult)
    assert in_place_result.outputs == (ep1,)
    assert not (in_place_dir / "_workdir").exists()
