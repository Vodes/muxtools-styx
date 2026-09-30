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
from muxtools_styx.metadata import edit_metadata_in_place, fixed_metadata
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
    other_tags: dict[str, str] = field(default_factory=dict)

    @property
    def sanitized_lang(self) -> Language:
        return Language(self.language)

    @property
    def raw_ffprobe(self) -> Any:
        return SimpleNamespace(bit_rate=str(self.bitrate))

    def get_audio_format(self) -> AudioFormat | None:
        return {"aac": AudioFormat.AAC, "eac3": AudioFormat.EAC3}.get(self.codec_name)


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

    class Editor:
        def __init__(self, path: Path) -> None:
            assert path == target

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
        SelectedTrack(cast(TrackInfo, Track(4, 1, TrackType.SUB, "en", title="Full Subtitles")), target),
        SelectedTrack(cast(TrackInfo, Track(3, 1, TrackType.AUDIO, "en")), target),
        SelectedTrack(cast(TrackInfo, Track(0, 0, TrackType.VIDEO, "und")), target),
        SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja")), target),
        SelectedTrack(cast(TrackInfo, Track(2, 0, TrackType.SUB, "en", title="Signs", is_forced=True)), target),
    )

    result = edit_metadata_in_place(target, tracks, normalize_names=False, fix_tags=True, title="Show - 01")

    assert result == target
    assert [kind for kind, _kwargs in calls] == ["info", "video", "audio", "audio", "sub", "sub"]
    assert calls[0][1] == {"title": "Show - 01", "muxing_application": None}
    assert all(kwargs["tags"] == {} for _kind, kwargs in calls[1:])
    assert calls[2][1] == {"name": None, "language": "ja", "default": True, "forced": False, "tags": {}}
    assert calls[4][1]["forced"] is True


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
    unknown = SelectedTrack(cast(TrackInfo, Track(1, 0, TrackType.AUDIO, "ja", "flac", 1_500_000)), Path("donor.mkv"))
    assert choose_best_japanese([known, unknown]) is known


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
