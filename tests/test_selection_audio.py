from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from muxtools import AudioFormat, ParsedFile, TrackInfo, TrackType

from muxtools_styx import metadata as metadata_module
from muxtools_styx import mux as mux_module
from muxtools_styx.audio import audio_tier, choose_best_japanese
from muxtools_styx.inspect import format_inspection
from muxtools_styx.metadata import edit_metadata_in_place, fixed_metadata, metadata_arguments
from muxtools_styx.mux import process_mux, resolve_output_template, resolve_setup_output
from muxtools_styx.selection import MuxOptions, SelectedTrack, Selection, TrackOptions, TransformOptions, is_signs_or_forced, select_tracks


class Language:
    def __init__(self, tag: str) -> None:
        self.tag = tag

    def to_tag(self) -> str:
        return self.tag


@dataclass
class Track:
    index: int
    relative_index: int
    type: TrackType
    language: str
    codec_name: str = "aac"
    bitrate: int = 128_000
    title: str | None = None
    is_default: bool = False
    is_forced: bool = False
    flag_hearing_impaired: bool | None = None
    disposition: dict[str, int] = field(default_factory=dict)
    other_tags: dict[str, str] = field(default_factory=dict)

    @property
    def sanitized_lang(self) -> Language:
        return Language(self.language)

    @property
    def raw_ffprobe(self) -> Any:
        return SimpleNamespace(bit_rate=str(self.bitrate), disposition=self.disposition)

    @property
    def raw_mkvmerge(self) -> Any:
        return SimpleNamespace(properties=SimpleNamespace(flag_hearing_impaired=self.flag_hearing_impaired))

    def get_audio_format(self) -> AudioFormat | None:
        return {
            "aac": AudioFormat.AAC,
            "eac3": AudioFormat.EAC3,
            "flac": AudioFormat.FLAC,
            "opus": AudioFormat.OPUS,
        }.get(self.codec_name)


class Media:
    def __init__(self, source: str, tracks: list[Track]) -> None:
        self.source = Path(source)
        self.tracks = tracks

    def find_tracks(self, *, type: TrackType) -> list[TrackInfo]:
        return [cast(TrackInfo, track) for track in self.tracks if track.type == type]


def media(source: str, tracks: list[Track]) -> ParsedFile:
    return cast(ParsedFile, Media(source, tracks))


def test_fill_audio_adds_missing_language_and_forced_companion() -> None:
    target = media("target.mkv", [Track(0, 0, TrackType.VIDEO, "und"), Track(1, 0, TrackType.AUDIO, "ja")])
    donor = media(
        "donor.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "ja"),
            Track(2, 1, TrackType.AUDIO, "de"),
            Track(3, 2, TrackType.AUDIO, "de", title="Commentary"),
            Track(4, 0, TrackType.SUB, "de", title="Forced", is_forced=True),
        ],
    )
    result = select_tracks(target, donor, MuxOptions(tracks=TrackOptions(fill_audio=True)))
    assert [track.track.language for track in result.audio] == ["ja", "de", "de"]
    assert [track.track.language for track in result.subtitles] == ["de"]


def test_fill_audio_keeps_cc_sdh_and_dubtitle_companions_for_introduced_audio() -> None:
    target = media(
        "target.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "ja"),
            Track(2, 0, TrackType.SUB, "de", title="Full"),
        ],
    )
    donor = media(
        "donor.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "ja"),
            Track(2, 1, TrackType.AUDIO, "en"),
            Track(3, 0, TrackType.SUB, "en", title=None, disposition={"dub": 1}),
            Track(4, 1, TrackType.SUB, "en", title="Forced", is_forced=True),
            Track(5, 2, TrackType.SUB, "en", codec_name="subrip", title="CC"),
            Track(6, 3, TrackType.SUB, "en", codec_name="subrip", title="SDH", flag_hearing_impaired=True),
            Track(7, 4, TrackType.SUB, "en", codec_name="ass", title="English (Dubtitles)"),
            Track(8, 5, TrackType.SUB, "en", title="Full Subtitles (CCC Converted)"),
            Track(9, 6, TrackType.SUB, "de", codec_name="subrip", title="SDH", flag_hearing_impaired=True),
        ],
    )
    result = select_tracks(target, donor, MuxOptions(tracks=TrackOptions(fill_audio=True)))
    assert [track.track.language for track in result.audio] == ["ja", "en"]
    assert [(track.source_file.name, track.track.index) for track in result.subtitles] == [
        ("target.mkv", 2),
        ("donor.mkv", 4),
        ("donor.mkv", 5),
        ("donor.mkv", 6),
        ("donor.mkv", 7),
    ]


def test_fill_audio_matches_one_sided_regional_variants_without_crossing_regions() -> None:
    target = media("target.mkv", [Track(0, 0, TrackType.VIDEO, "und"), Track(1, 0, TrackType.AUDIO, "ja")])
    donor = media(
        "donor.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "fr"),
            Track(2, 1, TrackType.AUDIO, "en-US"),
            Track(3, 2, TrackType.AUDIO, "es-419"),
            Track(4, 3, TrackType.AUDIO, "zh-CN"),
            Track(5, 0, TrackType.SUB, "fr-FR", title="European (SDH)", flag_hearing_impaired=True),
            Track(6, 1, TrackType.SUB, "en", title="CC"),
            Track(7, 2, TrackType.SUB, "es-419", title="Latin American (SDH)", flag_hearing_impaired=True),
            Track(8, 3, TrackType.SUB, "es-ES", title="European (SDH)", flag_hearing_impaired=True),
            Track(9, 4, TrackType.SUB, "zh-Hans", title="SDH", flag_hearing_impaired=True),
            Track(10, 5, TrackType.SUB, "zh-Hant", title="SDH", flag_hearing_impaired=True),
        ],
    )
    result = select_tracks(target, donor, MuxOptions(tracks=TrackOptions(fill_audio=True)))
    assert [track.track.index for track in result.subtitles] == [5, 6, 7, 9]


def test_fill_audio_with_keep_subs_missing_languages_still_imports_full_subs() -> None:
    target = media(
        "target.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "ja"),
            Track(2, 0, TrackType.SUB, "de"),
        ],
    )
    donor = media(
        "donor.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "en"),
            Track(2, 0, TrackType.SUB, "en", title="Full"),
            Track(3, 1, TrackType.SUB, "en", title="Forced", is_forced=True),
            Track(4, 2, TrackType.SUB, "en", title="CC"),
        ],
    )
    result = select_tracks(target, donor, MuxOptions(tracks=TrackOptions(fill_audio=True, keep_subs_missing_languages=True)))
    assert [(track.source_file.name, track.track.index) for track in result.subtitles] == [
        ("target.mkv", 2),
        ("donor.mkv", 2),
        ("donor.mkv", 3),
        ("donor.mkv", 4),
    ]


def test_remove_unnecessary_keeps_companions_for_kept_audio_and_drops_orphaned_sdh() -> None:
    target = media(
        "target.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "ja"),
            Track(2, 1, TrackType.AUDIO, "fr"),
            Track(3, 0, TrackType.SUB, "en", title="Full"),
            Track(4, 1, TrackType.SUB, "fr-FR", title="European (SDH)", flag_hearing_impaired=True),
            Track(5, 2, TrackType.SUB, "fr-FR", title="Full"),
            Track(6, 3, TrackType.SUB, "de", title="SDH", flag_hearing_impaired=True),
        ],
    )
    result = select_tracks(
        target,
        None,
        MuxOptions(tracks=TrackOptions(remove_unnecessary=True, audio_languages=("ja", "fr", "de"), sub_languages=("en",))),
    )
    assert [track.track.index for track in result.subtitles] == [3, 4]


def test_fixed_metadata_never_defaults_cc_sdh_or_dubtitle_and_sets_hi_flags() -> None:
    source = Path("donor.mkv")
    cc = SelectedTrack(cast(TrackInfo, Track(2, 0, TrackType.SUB, "en", title="CC")), source)
    sdh = SelectedTrack(cast(TrackInfo, Track(3, 1, TrackType.SUB, "en", title="SDH", flag_hearing_impaired=True)), source)
    dub = SelectedTrack(cast(TrackInfo, Track(4, 2, TrackType.SUB, "en", title="English (Dubtitles)")), source)
    full = SelectedTrack(cast(TrackInfo, Track(5, 3, TrackType.SUB, "en", title="Full")), source)

    fixed = fixed_metadata((cc, sdh, dub, full))
    assert fixed[(source, 2)] == ("en", False, False, True)
    assert fixed[(source, 3)] == ("en", False, False, True)
    assert fixed[(source, 4)] == ("en", False, False, False)
    assert fixed[(source, 5)] == ("en", True, False, False)

    args = metadata_arguments([cc, dub, full], normalize_names=False, fix_tags=True, title_for=lambda _item: "", fixed=fixed)
    assert ["--hearing-impaired-flag", "2:yes"] == args[args.index("--hearing-impaired-flag") : args.index("--hearing-impaired-flag") + 2]
    assert "4:no" in args
    assert "5:no" in args


def test_format_inspection_includes_hearing_impaired_flag() -> None:
    text = format_inspection(
        {
            "file": "show.mkv",
            "elements": [],
            "video": [],
            "audio": [],
            "subtitles": [
                {
                    "index": 2,
                    "language": "en",
                    "codec": "subrip",
                    "bitrate": None,
                    "title": "SDH",
                    "default": False,
                    "forced": False,
                    "hearing_impaired": True,
                }
            ],
        }
    )
    assert "2: en, subrip, SDH, hearing_impaired" in text


def test_conflicting_audio_modes_and_missing_donor_fail() -> None:
    target = media("target.mkv", [Track(0, 0, TrackType.VIDEO, "und"), Track(1, 0, TrackType.AUDIO, "ja")])
    with pytest.raises(ValueError, match="cannot be used together"):
        select_tracks(target, target, MuxOptions(tracks=TrackOptions(keep_audio=True, fill_audio=True)))
    with pytest.raises(ValueError, match="requires a donor"):
        select_tracks(target, None, MuxOptions(tracks=TrackOptions(keep_video=True)))


def test_selection_keeps_target_and_donor_supplemental_info_separate() -> None:
    target = media("target.mkv", [Track(0, 0, TrackType.VIDEO, "und"), Track(1, 0, TrackType.AUDIO, "ja")])
    donor = media("donor.mkv", [Track(0, 0, TrackType.VIDEO, "und"), Track(1, 0, TrackType.AUDIO, "en")])

    result = select_tracks(
        target,
        donor,
        MuxOptions(tracks=TrackOptions(keep_audio=True)),
        target_supplemental_info="Target [CR]",
        donor_supplemental_info="Donor [AMZN]",
    )

    assert [item.supplemental_info for item in result.audio] == ["Target [CR]", "Donor [AMZN]"]


def test_language_filter_normalizes_user_aliases() -> None:
    target = media("target.mkv", [Track(0, 0, TrackType.VIDEO, "und"), Track(1, 0, TrackType.AUDIO, "ja")])
    result = select_tracks(target, None, MuxOptions(tracks=TrackOptions(remove_unnecessary=True, audio_languages=("jpn",))))
    assert [track.track.language for track in result.audio] == ["ja"]


def test_language_filter_uses_unidirectional_langcodes_hierarchy_and_equivalence() -> None:
    target = media(
        "target.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "ja"),
            Track(2, 0, TrackType.SUB, "en"),
            Track(3, 1, TrackType.SUB, "en-US"),
            Track(4, 2, TrackType.SUB, "de"),
            Track(5, 3, TrackType.SUB, "de-DE"),
            Track(6, 4, TrackType.SUB, "es"),
            Track(7, 5, TrackType.SUB, "es-419"),
            Track(8, 6, TrackType.SUB, "es-ES"),
            Track(9, 7, TrackType.SUB, "zh-Hans"),
            Track(10, 8, TrackType.SUB, "zh-Hans-CN"),
            Track(11, 9, TrackType.SUB, "zh-Hant"),
        ],
    )
    result = select_tracks(
        target,
        None,
        MuxOptions(
            tracks=TrackOptions(
                remove_unnecessary=True,
                audio_languages=("ja",),
                sub_languages=("en", "de-DE", "es-419", "zh-CN"),
            )
        ),
    )
    assert [track.track.language for track in result.subtitles] == ["en", "en-US", "de-DE", "es-419", "zh-Hans", "zh-Hans-CN"]


def test_ambiguous_video_and_forced_default_handling() -> None:
    target = media(
        "target.mkv",
        [Track(0, 0, TrackType.VIDEO, "und"), Track(1, 1, TrackType.VIDEO, "und"), Track(2, 0, TrackType.AUDIO, "ja")],
    )
    with pytest.raises(ValueError, match="exactly one video"):
        select_tracks(target, None, MuxOptions())
    assert is_signs_or_forced(cast(TrackInfo, Track(3, 0, TrackType.SUB, "en", is_default=True, is_forced=True)))


def test_fixed_metadata_has_one_default_per_language_across_sources() -> None:
    first = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja")), Path("target.mkv"))
    second = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja")), Path("donor.mkv"))
    fixed = fixed_metadata((first, second))
    assert fixed[(first.source_file, first.track.index)][1]
    assert not fixed[(second.source_file, second.track.index)][1]


def test_in_place_metadata_uses_relative_type_order_and_removes_track_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "target.mkv"
    calls: list[tuple[str, dict[str, object]]] = []
    editor_init: list[dict[str, object]] = []

    class Editor:
        def __init__(self, path: Path, **kwargs: object) -> None:
            assert path == target
            editor_init.append(kwargs)

        def audio_track(self, **kwargs: object) -> None:
            calls.append(("audio", kwargs))

        def video_track(self, **kwargs: object) -> None:
            calls.append(("video", kwargs))

        def sub_track(self, **kwargs: object) -> None:
            calls.append(("sub", kwargs))

        def info(self, **kwargs: object) -> None:
            calls.append(("info", kwargs))

        def run(self) -> tuple[Path, bool]:
            return target, True

    monkeypatch.setattr(metadata_module, "MKVPropEdit", Editor)
    tracks = (
        SelectedTrack(cast(TrackInfo, Track(5, 2, TrackType.SUB, "en", title="CC")), target),
        SelectedTrack(cast(TrackInfo, Track(4, 1, TrackType.SUB, "en", title="Full Subtitles")), target),
        SelectedTrack(cast(TrackInfo, Track(3, 1, TrackType.AUDIO, "en")), target),
        SelectedTrack(cast(TrackInfo, Track(0, 0, TrackType.VIDEO, "und")), target),
        SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja")), target),
        SelectedTrack(cast(TrackInfo, Track(2, 0, TrackType.SUB, "en", title="Signs", is_forced=True)), target),
    )

    result = edit_metadata_in_place(target, tracks, normalize_names=False, fix_tags=True, title="Show - 01")

    assert result == target
    assert editor_init == [{"tags": {}}, {"track_statistics": True}]
    assert [kind for kind, _kwargs in calls] == ["info", "video", "audio", "audio", "sub", "sub", "sub"]
    assert calls[0][1] == {"title": "Show - 01", "muxing_application": None}
    assert all(kwargs["tags"] == {} for _kind, kwargs in calls[1:])
    assert calls[2][1] == {"name": None, "language": "ja", "default": True, "forced": False, "tags": {}}
    assert calls[4][1]["forced"] is True
    assert calls[4][1]["flag_hearing_impaired"] is False
    assert calls[5][1]["default"] is True
    assert calls[5][1]["flag_hearing_impaired"] is False
    assert calls[6][1]["default"] is False
    assert calls[6][1]["flag_hearing_impaired"] is True


@pytest.mark.parametrize("skip_branding", [False, True])
@pytest.mark.parametrize("existing_branding", [False, True])
@pytest.mark.parametrize("title", [None, "Show - 01"])
def test_in_place_metadata_preserves_muxing_library_and_brands_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip_branding: bool, existing_branding: bool, title: str | None
) -> None:
    from muxtools import __version__

    target = tmp_path / "target.mkv"
    library = "libebml v1.4.5 + libmatroska v1.7.1"
    branded = f"{library} + muxtools v{__version__}"
    original = branded if existing_branding else library
    calls: list[dict[str, object]] = []

    class Editor:
        def __init__(self, path: Path) -> None:
            assert path == target

        def info(self, **kwargs: object) -> None:
            calls.append(kwargs)

        def run(self) -> tuple[Path, bool]:
            return target, True

    monkeypatch.setattr(metadata_module, "MKVPropEdit", Editor)
    monkeypatch.setattr(metadata_module, "get_setup_attr", lambda *_args: skip_branding)
    assert edit_metadata_in_place(target, (), normalize_names=True, fix_tags=False, title=title, muxing_application=original) == target
    if skip_branding and title is None:
        assert calls == []
    else:
        assert calls == [{"title": title, "muxing_application": None if skip_branding else branded}]


def test_documented_best_audio_tiers() -> None:
    candidates = [
        SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "aac", 128_000)), Path("Show - 01 [CR].mkv")),
        SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "eac3", 224_000)), Path("Show - 01 [AMZN].mkv")),
        SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "aac", 192_000)), Path("Show - 01 [CR].mkv")),
        SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "aac", 256_000)), Path("Show - 01 [CR].mkv")),
    ]
    assert choose_best_japanese(candidates) is candidates[-1]
    assert choose_best_japanese(candidates[:-1]) is candidates[2]
    assert choose_best_japanese(candidates[:2]) is candidates[1]


def test_unknown_codec_does_not_win_on_bitrate() -> None:
    known = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "aac", 128_000)), Path("target.mkv"))
    unknown = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "unknown", 1_500_000)), Path("donor.mkv"))
    assert choose_best_japanese([known, unknown]) is known


def test_lossless_beats_lossy_and_unclassified_target_wins_conservatively() -> None:
    aac = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "aac", 256_000)), Path("target.mkv"))
    flac_target = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "flac", 900_000)), Path("target.mkv"))
    flac_donor = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "flac", 1_500_000)), Path("donor.mkv"))
    opus = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "opus", 192_000)), Path("target.mkv"))
    nf_eac3 = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "eac3", 640_000)), Path("Show [NF].mkv"))
    assert choose_best_japanese([aac, flac_donor]) is flac_donor
    assert choose_best_japanese([flac_target, flac_donor]) is flac_target
    assert choose_best_japanese([opus, aac]) is opus
    assert choose_best_japanese([nf_eac3, aac]) is nf_eac3
    assert choose_best_japanese([opus, flac_donor]) is flac_donor


def test_best_audio_compares_donor_in_default_and_fill_audio_modes() -> None:
    target = media(
        "target.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "ja", "aac", 128_000),
            Track(2, 1, TrackType.AUDIO, "en", "aac", 128_000),
        ],
    )
    donor = media(
        "donor.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "ja", "aac", 256_000),
            Track(2, 1, TrackType.AUDIO, "de", "aac", 192_000),
        ],
    )
    default_best = select_tracks(target, donor, MuxOptions(tracks=TrackOptions(best_audio=True)))
    assert [(item.source_file.name, item.track.language) for item in default_best.audio] == [
        ("donor.mkv", "ja"),
        ("target.mkv", "en"),
    ]
    fill_best = select_tracks(target, donor, MuxOptions(tracks=TrackOptions(fill_audio=True, best_audio=True)))
    assert [(item.source_file.name, item.track.language) for item in fill_best.audio] == [
        ("donor.mkv", "ja"),
        ("target.mkv", "en"),
        ("donor.mkv", "de"),
    ]


def test_fill_audio_and_missing_subs_use_language_matching_and_full_sub_check() -> None:
    target = media(
        "target.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "en"),
            Track(2, 0, TrackType.SUB, "de", title="Signs", is_forced=True),
            Track(3, 1, TrackType.SUB, "en", title="Full"),
        ],
    )
    donor = media(
        "donor.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "en-US"),
            Track(2, 0, TrackType.SUB, "en-US", title="Full"),
            Track(3, 1, TrackType.SUB, "de", title="Full"),
            Track(4, 2, TrackType.SUB, "de", title="Forced", is_forced=True),
        ],
    )
    result = select_tracks(target, donor, MuxOptions(tracks=TrackOptions(fill_audio=True, keep_subs_missing_languages=True)))
    assert [(item.source_file.name, item.track.language) for item in result.audio] == [("target.mkv", "en")]
    assert [(item.source_file.name, item.track.index) for item in result.subtitles] == [
        ("target.mkv", 2),
        ("target.mkv", 3),
        ("donor.mkv", 3),
    ]


def test_remove_unnecessary_requires_audio_for_all_companions_and_handles_enm() -> None:
    target = media(
        "target.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "ja"),
            Track(2, 0, TrackType.SUB, "en", title="Full"),
            Track(3, 1, TrackType.SUB, "enm", title="Full (Honorifics)"),
            Track(4, 2, TrackType.SUB, "de", title="Full"),
            Track(5, 3, TrackType.SUB, "de", title="Signs", is_forced=True),
            Track(6, 4, TrackType.SUB, "de", title="SDH", flag_hearing_impaired=True),
            Track(7, 5, TrackType.SUB, "en", title="English (Dubtitles)"),
        ],
    )
    result = select_tracks(
        target,
        None,
        MuxOptions(tracks=TrackOptions(remove_unnecessary=True, audio_languages=("ja", "en", "de"), sub_languages=("en", "de"))),
    )
    assert [item.track.index for item in result.subtitles] == [2, 3, 4]

    opt_out = select_tracks(
        target,
        None,
        MuxOptions(
            tracks=TrackOptions(remove_unnecessary=True, audio_languages=("ja",), sub_languages=("en", "de")),
            treat_enm_as_english=False,
        ),
    )
    assert [item.track.index for item in opt_out.subtitles] == [2, 4]

    fixed = fixed_metadata(result.subtitles)
    assert fixed[(target.source, 2)] == ("en", True, False, False)
    assert fixed[(target.source, 3)] == ("enm", False, False, False)


def test_is_signs_or_forced_avoids_substring_false_positives() -> None:
    assert is_signs_or_forced(cast(TrackInfo, Track(2, 0, TrackType.SUB, "en", title="English (Forced)")))
    assert is_signs_or_forced(cast(TrackInfo, Track(2, 0, TrackType.SUB, "en", title="English (Force)")))
    assert not is_signs_or_forced(cast(TrackInfo, Track(2, 0, TrackType.SUB, "en", title="English [FansubDesign]")))
    assert not is_signs_or_forced(cast(TrackInfo, Track(2, 0, TrackType.SUB, "en", title="English (Unforced)")))


def test_attached_pic_cover_art_and_keep_video_and_donor_audio() -> None:
    target = media(
        "target.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 1, TrackType.VIDEO, "und", disposition={"attached_pic": 1}),
        ],
    )
    donor = media(
        "donor.mkv",
        [
            Track(0, 0, TrackType.VIDEO, "und"),
            Track(1, 0, TrackType.AUDIO, "ja"),
        ],
    )
    result = select_tracks(target, donor, MuxOptions(tracks=TrackOptions(keep_audio=True)))
    assert [item.track.index for item in result.video] == [0]
    assert [item.source_file.name for item in result.audio] == ["donor.mkv"]


def test_donor_equals_target_raises() -> None:
    target = media("same.mkv", [Track(0, 0, TrackType.VIDEO, "und"), Track(1, 0, TrackType.AUDIO, "ja")])
    with pytest.raises(ValueError, match="cannot be the same"):
        select_tracks(target, target, MuxOptions(tracks=TrackOptions(keep_audio=True)))


def test_literal_dollar_in_output_template_is_allowed(tmp_path: Path) -> None:
    result = resolve_output_template("$100 Girlfriend - 01", cast(ParsedFile, object()), tmp_path)
    assert result == tmp_path / "$100 Girlfriend - 01.mkv"
    with pytest.raises(ValueError, match="unresolved output token"):
        resolve_output_template("Show - $unknown$", cast(ParsedFile, object()), tmp_path)


def test_can_edit_in_place_ignores_unused_languages_and_tpp(tmp_path: Path) -> None:
    target = tmp_path / "target.mkv"
    options = MuxOptions(
        tracks=TrackOptions(audio_languages=("ja",), sub_languages=("de",)),
        transforms=TransformOptions(fix_tags=True, restyle_languages=("de",), tpp=True),
    )
    assert mux_module.can_edit_in_place(options, None, None, target, allow_implicit_in_place=True)
    assert not mux_module.can_edit_in_place(options, None, None, target, allow_implicit_in_place=False)
    assert mux_module.can_edit_in_place(options, None, target, target, allow_implicit_in_place=False)


def test_build_mux_inputs_preserves_chapters_track_order_and_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "target.mkv"
    donor = tmp_path / "donor.mkv"
    target.touch()
    donor.touch()
    recorded: list[dict[str, object]] = []

    class FakePremux:
        def __init__(self, source: Path, **kwargs: object) -> None:
            self.source = source
            self.args = list(cast(list[str], kwargs.get("mkvmerge_args", [])))
            recorded.append({"source": source, **kwargs})

    monkeypatch.setattr(mux_module, "Premux", FakePremux)

    donor_video = SelectedTrack(cast(TrackInfo, Track(0, 0, TrackType.VIDEO, "und")), donor)
    donor_audio = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja")), donor)
    selection = Selection((donor_video,), (donor_audio,), (), target)
    inputs = mux_module.build_mux_inputs(selection, MuxOptions(transforms=TransformOptions(fix_tags=True)))

    assert len(recorded) == 2
    assert recorded[0]["source"] == donor
    assert recorded[1]["source"] == target
    assert recorded[1]["keep_chapters"] is True
    assert "--no-global-tags" in cast(list[str], recorded[0]["mkvmerge_args"])
    assert "--no-track-tags" in cast(list[str], recorded[0]["mkvmerge_args"])
    assert inputs[0].args[:2] == ["--track-order", "0:0,0:1"]


def test_supplemental_source_is_used_for_amazon_audio_tier() -> None:
    selected = SelectedTrack(
        cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "eac3", 224_000)),
        Path("Show - 01 [WEB-DL].mkv"),
        "Show [AMZN]",
    )
    assert audio_tier(selected) == (2, 224_000)


def test_output_template_cannot_escape_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a path"):
        resolve_output_template("../outside", cast(ParsedFile, object()), tmp_path)


def test_output_template_rejects_deferred_crc32(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be preflighted safely"):
        resolve_output_template("Show - 01 [$crc32$]", cast(ParsedFile, object()), tmp_path)


def test_setup_output_resolves_standard_show_and_episode_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "vof_setup",
        json.dumps(
            {
                "show_name": "Overgeared",
                "episode": "01",
                "out_dir": str(tmp_path),
                "out_name": "$show$ - $ep$ (premux)",
            }
        ),
    )
    monkeypatch.setattr(mux_module, "composed_media", lambda _target, _selection: cast(ParsedFile, object()))

    result = resolve_setup_output(cast(ParsedFile, object()), cast(Selection, object()))

    assert result == tmp_path / "Overgeared - 01 (premux).mkv"


@pytest.mark.parametrize("explicit_output", [False, True])
def test_metadata_only_mux_edits_input_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, explicit_output: bool) -> None:
    target = tmp_path / "target.mkv"
    target.touch()
    selection = Selection(
        (SelectedTrack(cast(TrackInfo, Track(0, 0, TrackType.VIDEO, "und")), target),),
        (SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja")), target),),
        (),
        target,
    )
    edited: list[Path] = []
    edited_info: list[dict[str, Any]] = []
    monkeypatch.setattr(
        mux_module.ParsedFile,
        "from_file",
        lambda *_args: cast(
            ParsedFile,
            SimpleNamespace(
                container_info=SimpleNamespace(raw_mkvmerge=SimpleNamespace(properties=SimpleNamespace(muxing_application="original library")))
            ),
        ),
    )
    monkeypatch.setattr(mux_module, "select_tracks", lambda *_args, **_kwargs: selection)
    monkeypatch.setattr(
        mux_module,
        "edit_metadata_in_place",
        lambda path, *_args, **kwargs: edited_info.append(kwargs) or edited.append(path) or path,
    )
    monkeypatch.setattr(mux_module, "resolve_setup_output", lambda *_args: pytest.fail("resolved a remux output"))
    monkeypatch.setattr(mux_module, "mux", lambda *_args, **_kwargs: pytest.fail("started a remux"))

    result = process_mux(
        target,
        options=MuxOptions(transforms=TransformOptions(fix_tags=True, normalize_track_names=True)),
        outfile=target if explicit_output else None,
    )

    assert result == target.resolve()
    assert edited == [target.resolve()]
    assert edited_info[0]["muxing_application"] == "original library"


def test_content_changing_mux_cannot_use_input_as_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "target.mkv"
    target.touch()
    selection = Selection(
        (SelectedTrack(cast(TrackInfo, Track(0, 0, TrackType.VIDEO, "und")), target),),
        (SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja")), target),),
        (),
        target,
    )
    monkeypatch.setattr(mux_module.ParsedFile, "from_file", lambda *_args: cast(ParsedFile, object()))
    monkeypatch.setattr(mux_module, "select_tracks", lambda *_args, **_kwargs: selection)

    with pytest.raises(ValueError, match="output may equal the input"):
        process_mux(target, options=MuxOptions(transforms=TransformOptions(restyle_subs=True)), outfile=target, overwrite=True)

    monkeypatch.setattr(mux_module, "resolve_setup_output", lambda *_args: target.resolve())
    with pytest.raises(ValueError, match="output may equal the input"):
        process_mux(target, options=MuxOptions(transforms=TransformOptions(restyle_subs=True)), overwrite=True)

    donor = tmp_path / "donor.mkv"
    donor.touch()
    with pytest.raises(ValueError, match="cannot overwrite the donor"):
        process_mux(target, donor=donor, options=MuxOptions(tracks=TrackOptions(keep_audio=True)), outfile=donor, overwrite=True)


def test_in_place_explicit_mkv_title_is_not_cleaned_twice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / ".hack Sign - 01.mkv"
    target.touch()
    selection = Selection(
        (SelectedTrack(cast(TrackInfo, Track(0, 0, TrackType.VIDEO, "und")), target),),
        (SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja")), target),),
        (),
        target,
    )
    titles: list[str | None] = []
    monkeypatch.setattr(
        mux_module.ParsedFile,
        "from_file",
        lambda *_args: cast(ParsedFile, SimpleNamespace(container_info=SimpleNamespace(raw_mkvmerge=None))),
    )
    monkeypatch.setattr(mux_module, "select_tracks", lambda *_args, **_kwargs: selection)
    monkeypatch.setattr(
        mux_module,
        "edit_metadata_in_place",
        lambda path, *_args, **kwargs: titles.append(kwargs.get("title")) or path,
    )
    process_mux(
        target,
        options=MuxOptions(transforms=TransformOptions(fix_tags=True)),
        explicit_mkv_title=".hack//Sign - 01",
    )
    assert titles == [".hack//Sign - 01"]
