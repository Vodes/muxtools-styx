from pathlib import Path

from muxtools import TrackType

from muxtools_styx.models import TrackRef
from muxtools_styx.transforms import build_subtitle_tracks
from tests.fakes import FakeTrack


def test_build_subtitle_tracks_ignores_font_collection_failures_for_passthrough_subtitles(monkeypatch) -> None:
    class FakeSubFile:
        file = Path("broken.ass")

        def to_track(self, name: str, lang: str, default: bool, forced: bool):
            return {
                "name": name,
                "lang": lang,
                "default": default,
                "forced": forced,
            }

    warnings = []

    monkeypatch.setattr("muxtools_styx.transforms.SubFile.from_mkv", lambda *args, **kwargs: FakeSubFile())
    monkeypatch.setattr(
        "muxtools_styx.transforms._collect_fonts_for_subtitle",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Failed to collect fonts for subtitle 'broken.ass'.")),
    )
    monkeypatch.setattr("muxtools_styx.transforms.warn", lambda message, *args, **kwargs: warnings.append(message))

    tracks, fonts = build_subtitle_tracks(
        transforms=[],
        passthrough_text_subtitles=[
            TrackRef(
                source=Path("source.mkv"),
                track=FakeTrack(
                    index=1,
                    relative_index=0,
                    type=TrackType.SUB,
                    codec_name="ass",
                    language="en",
                    title="Broken",
                ),
                reason="Keep source subtitle track.",
            )
        ],
    )

    assert len(tracks) == 1
    assert fonts == []
    assert warnings == ["Failed to collect fonts for subtitle 'broken.ass'. Font collection was skipped for this unchanged subtitle track."]
