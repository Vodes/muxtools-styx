from pathlib import Path

from muxtools import TrackType

from muxtools_styx.models import SourceFile
from muxtools_styx.rules import choose_donor_audio_tracks, choose_donor_sign_subtitles, choose_donor_subtitles_missing_languages
from tests.fakes import FakeTrack


def test_choose_donor_audio_tracks_skips_existing_language() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.AUDIO, codec_name="flac", language="en"),
            FakeTrack(index=1, relative_index=1, type=TrackType.AUDIO, codec_name="aac", language="ja"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.AUDIO, codec_name="eac3", language="ja"),
            FakeTrack(index=1, relative_index=1, type=TrackType.AUDIO, codec_name="aac", language="de"),
        ],
    )

    chosen = choose_donor_audio_tracks(donor, target)

    assert [track.language for track in chosen] == ["en"]


def test_choose_donor_sign_subtitles_only_keeps_sign_like_tracks() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.SUB, codec_name="ass", language="en", title="Full Subtitles"),
            FakeTrack(index=1, relative_index=1, type=TrackType.SUB, codec_name="ass", language="en", title="Signs & Songs"),
        ],
    )

    chosen = choose_donor_sign_subtitles(donor, {"en"})

    assert len(chosen) == 1
    assert chosen[0].title == "Signs & Songs"


def test_choose_donor_subtitles_missing_languages_skips_existing_target_languages() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.SUB, codec_name="ass", language="en", title="English Full"),
            FakeTrack(index=1, relative_index=1, type=TrackType.SUB, codec_name="ass", language="fr", title="French Full"),
            FakeTrack(index=2, relative_index=2, type=TrackType.SUB, codec_name="ass", language="de", title="German Full"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.SUB, codec_name="ass", language="en", title="English Full"),
            FakeTrack(index=1, relative_index=1, type=TrackType.SUB, codec_name="ass", language="de", title="German Full"),
        ],
    )

    chosen = choose_donor_subtitles_missing_languages(donor, target)

    assert [track.language for track in chosen] == ["fr"]
