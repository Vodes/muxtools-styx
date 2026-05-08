from pathlib import Path

from muxtools_styx.models import SourceFile, TrackInfo
from muxtools_styx.rules import choose_donor_audio_tracks, choose_donor_sign_subtitles


def test_choose_donor_audio_tracks_skips_existing_language() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="audio", codec_name="flac", language="en"),
            TrackInfo(index=1, relative_index=1, kind="audio", codec_name="aac", language="ja"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="audio", codec_name="eac3", language="ja"),
            TrackInfo(index=1, relative_index=1, kind="audio", codec_name="aac", language="de"),
        ],
    )

    chosen = choose_donor_audio_tracks(donor, target)

    assert [track.language for track in chosen] == ["en"]


def test_choose_donor_sign_subtitles_only_keeps_sign_like_tracks() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="subtitle", codec_name="ass", language="en", title="Full Subtitles"),
            TrackInfo(index=1, relative_index=1, kind="subtitle", codec_name="ass", language="en", title="Signs & Songs"),
        ],
    )

    chosen = choose_donor_sign_subtitles(donor, {"en"})

    assert len(chosen) == 1
    assert chosen[0].title == "Signs & Songs"
