from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from muxtools import AudioFormat, ParsedFile, TrackInfo, TrackType

from muxtools_styx import mux as mux_module
from muxtools_styx.audio import choose_best_japanese
from muxtools_styx.metadata import fixed_metadata
from muxtools_styx.mux import resolve_output_template, resolve_setup_output
from muxtools_styx.selection import MuxOptions, SelectedTrack, Selection, TrackOptions, is_signs_or_forced, select_tracks


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
