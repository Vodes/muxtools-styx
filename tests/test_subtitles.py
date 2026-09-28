from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from muxtools import TrackInfo

from muxtools_styx import subtitles
from muxtools_styx.selection import SelectedTrack


class _Language:
    def to_tag(self) -> str:
        return "en"


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
