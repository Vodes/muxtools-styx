from pathlib import Path

from muxtools_styx.models import SourceFile, TrackInfo
from muxtools_styx.planner import plan_pair, plan_single


def test_plan_pair_uses_target_as_mux_base_and_keeps_donor_attachments_for_signs() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="audio", codec_name="flac", language="en"),
            TrackInfo(index=1, relative_index=0, kind="subtitle", codec_name="ass", language="en", title="Signs & Songs"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="video", codec_name="hevc", language="ja"),
            TrackInfo(index=1, relative_index=0, kind="audio", codec_name="eac3", language="ja"),
        ],
    )

    plan = plan_pair(donor, target, Path("out.mkv"))

    assert plan.sources == [target.path, donor.path]
    assert plan.selection.attachments_from == [target.path]
    assert len(plan.selection.audio) == 1


def test_plan_pair_carries_fix_tags_setting() -> None:
    donor = SourceFile(path=Path("donor.mkv"))
    target = SourceFile(path=Path("target.mkv"))

    plan = plan_pair(donor, target, Path("out.mkv"), fix_tags=True)

    assert plan.fix_tags is True


def test_plan_pair_can_switch_video_source_and_add_sync_args() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="video", codec_name="hevc", language="ja"),
            TrackInfo(index=1, relative_index=0, kind="audio", codec_name="flac", language="en"),
            TrackInfo(index=2, relative_index=0, kind="subtitle", codec_name="ass", language="de", title="German Signs"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="video", codec_name="h264", language="ja"),
            TrackInfo(index=1, relative_index=0, kind="audio", codec_name="eac3", language="ja"),
            TrackInfo(index=2, relative_index=0, kind="subtitle", codec_name="ass", language="en", title="English Full"),
        ],
    )

    plan = plan_pair(
        donor,
        target,
        Path("out.mkv"),
        keep_video=True,
        keep_audio=True,
        audio_sync=125,
        sub_sync=-250,
        keep_non_english=True,
    )

    assert plan.sources == [donor.path, target.path]
    assert plan.selection.video[0].source == donor.path
    assert str(donor.path) in plan.source_args
    assert "--sync" in plan.source_args[str(donor.path)]
    assert "1:125" in plan.source_args[str(donor.path)]
    assert "2:-250" in plan.source_args[str(donor.path)]


def test_plan_pair_best_audio_replaces_japanese_track_with_higher_bitrate() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="audio", codec_name="flac", bit_rate=1_500_000, language="ja", title="JP FLAC"),
            TrackInfo(index=1, relative_index=1, kind="audio", codec_name="aac", bit_rate=256_000, language="en", title="EN AAC"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="video", codec_name="h264", language="ja"),
            TrackInfo(index=1, relative_index=0, kind="audio", codec_name="aac", bit_rate=192_000, language="ja", title="JP AAC"),
            TrackInfo(index=2, relative_index=1, kind="audio", codec_name="aac", bit_rate=256_000, language="de", title="DE AAC"),
        ],
    )

    plan = plan_pair(donor, target, Path("out.mkv"), best_audio=True, keep_audio=False)

    assert [(track.source, track.track.title) for track in plan.selection.audio] == [
        (target.path, "DE AAC"),
        (donor.path, "JP FLAC"),
    ]


def test_plan_single_filters_tracks_and_creates_restyle_transforms() -> None:
    source = SourceFile(
        path=Path("source.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="video", codec_name="hevc", language="ja"),
            TrackInfo(index=1, relative_index=0, kind="audio", codec_name="flac", language="ja"),
            TrackInfo(index=2, relative_index=1, kind="audio", codec_name="aac", language="en"),
            TrackInfo(index=3, relative_index=0, kind="subtitle", codec_name="ass", language="en", title="English Full"),
            TrackInfo(index=4, relative_index=1, kind="subtitle", codec_name="ass", language="de", title="German Full"),
        ],
    )

    plan = plan_single(
        source,
        Path("out.mkv"),
        remove_unnecessary=True,
        audio_languages=["en"],
        sub_languages=["en"],
        restyle_subs=True,
        restyle_languages=["en"],
    )

    assert [track.track.language for track in plan.selection.audio] == ["en"]
    assert plan.selection.subtitles == []
    assert len(plan.subtitle_transforms) == 1
    assert plan.subtitle_transforms[0].language == "en"
    assert plan.selection.attachments_from == []


def test_plan_single_uses_pre_rewrite_language_defaults() -> None:
    source = SourceFile(
        path=Path("source.mkv"),
        tracks=[
            TrackInfo(index=0, relative_index=0, kind="video", codec_name="hevc", language="ja"),
            TrackInfo(index=1, relative_index=0, kind="audio", codec_name="flac", language="ja"),
            TrackInfo(index=2, relative_index=1, kind="audio", codec_name="aac", language="en"),
            TrackInfo(index=3, relative_index=2, kind="audio", codec_name="aac", language="de"),
            TrackInfo(index=4, relative_index=3, kind="audio", codec_name="aac", language="fr"),
            TrackInfo(index=5, relative_index=0, kind="subtitle", codec_name="ass", language="en", title="English Full"),
            TrackInfo(index=6, relative_index=1, kind="subtitle", codec_name="ass", language="de", title="German Full"),
            TrackInfo(index=7, relative_index=2, kind="subtitle", codec_name="ass", language="fr", title="French Full"),
        ],
    )

    plan = plan_single(source, Path("out.mkv"), remove_unnecessary=True, restyle_subs=True)

    assert [track.track.language for track in plan.selection.audio] == ["ja", "en", "de"]
    assert [track.track.language for track in plan.selection.subtitles] == []
    assert [track.language for track in plan.subtitle_transforms] == ["en", "de"]
