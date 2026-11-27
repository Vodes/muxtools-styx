from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from muxtools import TrackInfo

from muxtools_styx import subtitles
from muxtools_styx.selection import SelectedTrack


class _Language:
    def __init__(self, tag: str = "en") -> None:
        self._tag = tag

    def to_tag(self) -> str:
        return self._tag


class _Subtitle:
    def unfuck_cr(self, **_kwargs: Any) -> _Subtitle:
        return self

    def purge_macrons(self) -> _Subtitle:
        return self

    def restyle(self, *_args: Any, **_kwargs: Any) -> _Subtitle:
        return self

    def clean_styles(self) -> _Subtitle:
        return self

    def collect_fonts(self, **_kwargs: Any) -> list[Any]:
        return []

    def to_track(self, *_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(delay=0)


def test_restyled_subtitle_does_not_reapply_container_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Path("target.mkv")
    track = cast(
        TrackInfo,
        SimpleNamespace(
            codec_name="ass",
            relative_index=0,
            index=3,
            sanitized_lang=_Language(),
            language="en",
            title=None,
            is_default=True,
            is_forced=False,
        ),
    )
    preserve_delay_calls: list[bool] = []

    def extract(_source: Path, _track: int, *, preserve_delay: bool) -> _Subtitle:
        preserve_delay_calls.append(preserve_delay)
        return _Subtitle()

    monkeypatch.setattr(subtitles.SubFile, "from_mkv", extract)
    monkeypatch.setattr(subtitles, "_replace_unknown_styles", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_repair_layout_resolution", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_extract_font_attachments", lambda _source: [])

    tracks, _, _ = subtitles.transform_subtitles(
        (SelectedTrack(track, source),),
        ("en",),
        title_for=lambda _selected: "English",
        target_source=source,
    )

    assert preserve_delay_calls == [False]
    assert tracks[0].delay == 0


def test_restyled_donor_subtitle_applies_only_manual_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Path("donor.mkv")
    track = cast(
        TrackInfo,
        SimpleNamespace(
            codec_name="ass",
            relative_index=0,
            index=3,
            sanitized_lang=_Language(),
            language="en",
            title=None,
            is_default=True,
            is_forced=False,
        ),
    )
    monkeypatch.setattr(subtitles.SubFile, "from_mkv", lambda *_args, **_kwargs: _Subtitle())
    monkeypatch.setattr(subtitles, "_replace_unknown_styles", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_repair_layout_resolution", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_extract_font_attachments", lambda _source: [])

    tracks, _, _ = subtitles.transform_subtitles(
        (SelectedTrack(track, source),),
        ("en",),
        title_for=lambda _selected: "English",
        target_source=Path("target.mkv"),
        donor_delay=-125,
    )

    assert tracks[0].delay == -125


@pytest.mark.parametrize(
    ("codec_name", "title", "flag_hi"),
    [
        ("ass", "CC", None),
        ("ass", "SDH", True),
        ("subrip", "CC", None),
        ("subrip", "SDH", True),
    ],
)
def test_transform_subtitles_skips_cc_and_sdh_tracks(monkeypatch: pytest.MonkeyPatch, codec_name: str, title: str, flag_hi: bool | None) -> None:
    source = Path("donor.mkv")
    track = cast(
        TrackInfo,
        SimpleNamespace(
            codec_name=codec_name,
            relative_index=2,
            index=5,
            sanitized_lang=_Language(),
            language="en",
            title=title,
            is_default=False,
            is_forced=False,
            raw_mkvmerge=SimpleNamespace(properties=SimpleNamespace(flag_hearing_impaired=flag_hi)),
            raw_ffprobe=SimpleNamespace(disposition={}),
        ),
    )
    warnings: list[str] = []
    monkeypatch.setattr(subtitles, "warn", lambda message, *_args: warnings.append(message))
    monkeypatch.setattr(subtitles.SubFile, "from_mkv", lambda *_args, **_kwargs: pytest.fail("should not extract CC/SDH"))

    tracks, fonts, transformed = subtitles.transform_subtitles(
        (SelectedTrack(track, source),),
        ("en",),
        title_for=lambda _selected: "English CC",
        target_source=Path("target.mkv"),
    )

    assert tracks == []
    assert fonts == []
    assert transformed == set()
    assert warnings == []


def test_transform_subtitles_matches_restyle_languages_unidirectionally(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Path("target.mkv")
    candidates = tuple(
        SelectedTrack(
            cast(
                TrackInfo,
                SimpleNamespace(
                    codec_name="ass",
                    relative_index=idx,
                    index=idx + 1,
                    sanitized_lang=_Language(tag),
                    language=tag,
                    title=None,
                    is_default=False,
                    is_forced=False,
                ),
            ),
            source,
        )
        for idx, tag in enumerate(("en-US", "de", "de-DE", "zh-Hans", "zh-Hant"))
    )
    monkeypatch.setattr(subtitles.SubFile, "from_mkv", lambda *_args, **_kwargs: _Subtitle())
    monkeypatch.setattr(subtitles, "_replace_unknown_styles", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_repair_layout_resolution", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_extract_font_attachments", lambda _source: [])

    _, _, transformed = subtitles.transform_subtitles(
        candidates,
        ("en", "de-DE", "zh-CN"),
        title_for=lambda _selected: "Sub",
        target_source=source,
    )

    assert transformed == {(source, 1), (source, 3), (source, 4)}


def test_transform_subtitles_preserves_bcp47_subtag_without_fix_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Path("target.mkv")
    track = cast(
        TrackInfo,
        SimpleNamespace(
            codec_name="ass",
            relative_index=0,
            index=2,
            sanitized_lang=_Language("es-419"),
            language="spa",
            title=None,
            is_default=False,
            is_forced=False,
        ),
    )
    captured_languages: list[str] = []

    class RecordingSub(_Subtitle):
        def to_track(self, _name: str, language: str, *_args: Any, **_kwargs: Any) -> Any:
            captured_languages.append(language)
            return SimpleNamespace(delay=0)

    monkeypatch.setattr(subtitles.SubFile, "from_mkv", lambda *_args, **_kwargs: RecordingSub())
    monkeypatch.setattr(subtitles, "_replace_unknown_styles", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_repair_layout_resolution", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_extract_font_attachments", lambda _source: [])

    subtitles.transform_subtitles(
        (SelectedTrack(track, source),),
        ("es",),
        title_for=lambda _selected: "Spanish",
        target_source=source,
    )
    assert captured_languages == ["es-419"]


def test_transform_subtitles_enm_opt_out_and_disambiguation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "a" / "ep01.mkv"
    donor = tmp_path / "b" / "ep01.mkv"
    track_enm = cast(
        TrackInfo,
        SimpleNamespace(
            codec_name="ass",
            relative_index=0,
            index=2,
            sanitized_lang=_Language("enm"),
            language="enm",
            title=None,
            is_default=False,
            is_forced=False,
        ),
    )
    track_en = cast(
        TrackInfo,
        SimpleNamespace(
            codec_name="ass",
            relative_index=0,
            index=2,
            sanitized_lang=_Language("en"),
            language="en",
            title=None,
            is_default=False,
            is_forced=False,
        ),
    )
    extracted_paths: list[Path] = []

    class FileSub(_Subtitle):
        def __init__(self, path: Path) -> None:
            self.file = path

        def to_track(self, *_args: Any, **_kwargs: Any) -> Any:
            extracted_paths.append(self.file)
            return SimpleNamespace(delay=0)

    def fake_extract(source: Path, _rel: int, *, preserve_delay: bool) -> FileSub:
        assert not preserve_delay
        shared = tmp_path / f"{source.stem}_2.ass"
        shared.write_text(str(source), encoding="utf-8")
        return FileSub(shared)

    monkeypatch.setattr(subtitles.SubFile, "from_mkv", fake_extract)
    monkeypatch.setattr(subtitles, "_replace_unknown_styles", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_repair_layout_resolution", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_extract_font_attachments", lambda _source: [])

    _, _, transformed_default = subtitles.transform_subtitles(
        (SelectedTrack(track_enm, target), SelectedTrack(track_en, donor)),
        ("en",),
        title_for=lambda _selected: "Sub",
        target_source=target,
    )
    assert transformed_default == {(target, 2), (donor, 2)}
    assert len(set(extracted_paths)) == 2
    assert extracted_paths[0].read_text(encoding="utf-8") == str(target)
    assert extracted_paths[1].read_text(encoding="utf-8") == str(donor)

    _, _, transformed_opt_out = subtitles.transform_subtitles(
        (SelectedTrack(track_enm, target),),
        ("en",),
        title_for=lambda _selected: "Sub",
        target_source=target,
        treat_enm_as_english=False,
    )
    assert transformed_opt_out == set()


def test_transform_subtitles_skips_duplicate_container_fonts_when_source_keeps_ass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "target.mkv"
    restyled_track = cast(
        TrackInfo,
        SimpleNamespace(
            codec_name="ass",
            relative_index=0,
            index=2,
            sanitized_lang=_Language("en"),
            language="en",
            title=None,
            is_default=True,
            is_forced=False,
        ),
    )
    passthrough_ass = cast(
        TrackInfo,
        SimpleNamespace(
            codec_name="ass",
            relative_index=1,
            index=3,
            sanitized_lang=_Language("fr"),
            language="fr",
            title=None,
            is_default=False,
            is_forced=False,
        ),
    )
    container_font = tmp_path / "styx-fonts" / "1_ContainerFont.ttf"
    copied_container_font = tmp_path / "ContainerFont.ttf"
    system_font = tmp_path / "GandhiSans.otf"
    container_font.parent.mkdir(parents=True)
    container_font.write_bytes(b"container-font-bytes")
    copied_container_font.write_bytes(b"container-font-bytes")
    system_font.write_bytes(b"gandhi-font-bytes")

    class FontSub(_Subtitle):
        def collect_fonts(self, **_kwargs: Any) -> list[Any]:
            return [SimpleNamespace(file=copied_container_font), SimpleNamespace(file=system_font)]

    monkeypatch.setattr(subtitles.SubFile, "from_mkv", lambda *_args, **_kwargs: FontSub())
    monkeypatch.setattr(subtitles, "_replace_unknown_styles", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_repair_layout_resolution", lambda _subtitle: None)
    monkeypatch.setattr(subtitles, "_extract_font_attachments", lambda _source: [container_font])

    _, fonts, _ = subtitles.transform_subtitles(
        (SelectedTrack(restyled_track, source), SelectedTrack(passthrough_ass, source)),
        ("en",),
        title_for=lambda _selected: "Sub",
        target_source=source,
    )
    assert [font.file for font in fonts] == [system_font]
