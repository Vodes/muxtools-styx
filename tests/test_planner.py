from pathlib import Path

from muxtools import TrackType

from muxtools_styx.models import SourceFile, track_language
from muxtools_styx.planner import plan_pair, plan_single
from tests.fakes import FakeTrack


def test_plan_pair_uses_target_as_mux_base_and_keeps_donor_attachments_for_signs() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.AUDIO, codec_name="flac", language="en"),
            FakeTrack(index=1, relative_index=0, type=TrackType.SUB, codec_name="ass", language="en", title="Signs & Songs"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.VIDEO, codec_name="hevc", language="ja"),
            FakeTrack(index=1, relative_index=0, type=TrackType.AUDIO, codec_name="eac3", language="ja"),
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


def test_plan_pair_filters_tracks_during_initial_merge_and_only_schedules_restyle_post_mux() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.AUDIO, codec_name="aac", language="en", title="EN"),
            FakeTrack(index=1, relative_index=1, type=TrackType.SUB, codec_name="ass", language="fr", title="FR"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.VIDEO, codec_name="h264", language="ja"),
            FakeTrack(index=1, relative_index=0, type=TrackType.AUDIO, codec_name="aac", language="ja", title="JP"),
            FakeTrack(index=2, relative_index=1, type=TrackType.AUDIO, codec_name="aac", language="de", title="DE"),
            FakeTrack(index=3, relative_index=0, type=TrackType.SUB, codec_name="ass", language="en", title="EN"),
            FakeTrack(index=4, relative_index=1, type=TrackType.SUB, codec_name="ass", language="fr", title="FR"),
        ],
    )

    plan = plan_pair(
        donor,
        target,
        Path("out.mkv"),
        keep_audio=True,
        remove_unnecessary=True,
        audio_languages=["ja", "en"],
        sub_languages=["en"],
        restyle_subs=True,
        restyle_languages=["en"],
    )

    assert [track_language(track.track) for track in plan.selection.audio] == ["ja", "en"]
    assert [track_language(track.track) for track in plan.selection.subtitles] == ["en"]
    assert plan.post_mux_single is not None
    assert plan.post_mux_single.restyle_subs is True
    assert plan.post_mux_single.restyle_languages == ["en"]


def test_plan_pair_can_keep_donor_subtitles_for_missing_languages() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.SUB, codec_name="ass", language="en", title="English Forced", is_forced=True, is_default=False),
            FakeTrack(index=1, relative_index=1, type=TrackType.SUB, codec_name="ass", language="fr", title="French Full"),
            FakeTrack(index=2, relative_index=2, type=TrackType.SUB, codec_name="ass", language="de", title="German Full"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.VIDEO, codec_name="h264", language="ja"),
            FakeTrack(index=1, relative_index=0, type=TrackType.SUB, codec_name="ass", language="de", title="German Full"),
        ],
    )

    plan = plan_pair(donor, target, Path("out.mkv"), keep_subs_missing_languages=True)

    assert [(track_language(track.track), track.track.title) for track in plan.selection.subtitles] == [
        ("de", "German Full"),
        ("en", "English Forced"),
        ("fr", "French Full"),
    ]


def test_plan_pair_can_switch_video_source_and_add_sync_args() -> None:
    donor = SourceFile(
        path=Path("donor.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.VIDEO, codec_name="hevc", language="ja"),
            FakeTrack(index=1, relative_index=0, type=TrackType.AUDIO, codec_name="flac", language="en"),
            FakeTrack(index=2, relative_index=0, type=TrackType.SUB, codec_name="ass", language="de", title="German Signs"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.VIDEO, codec_name="h264", language="ja"),
            FakeTrack(index=1, relative_index=0, type=TrackType.AUDIO, codec_name="eac3", language="ja"),
            FakeTrack(index=2, relative_index=0, type=TrackType.SUB, codec_name="ass", language="en", title="English Full"),
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
            FakeTrack(index=0, relative_index=0, type=TrackType.AUDIO, codec_name="flac", bit_rate=1_500_000, language="ja", title="JP FLAC"),
            FakeTrack(index=1, relative_index=1, type=TrackType.AUDIO, codec_name="aac", bit_rate=256_000, language="en", title="EN AAC"),
        ],
    )
    target = SourceFile(
        path=Path("target.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.VIDEO, codec_name="h264", language="ja"),
            FakeTrack(index=1, relative_index=0, type=TrackType.AUDIO, codec_name="aac", bit_rate=192_000, language="ja", title="JP AAC"),
            FakeTrack(index=2, relative_index=1, type=TrackType.AUDIO, codec_name="aac", bit_rate=256_000, language="de", title="DE AAC"),
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
            FakeTrack(index=0, relative_index=0, type=TrackType.VIDEO, codec_name="hevc", language="ja"),
            FakeTrack(index=1, relative_index=0, type=TrackType.AUDIO, codec_name="flac", language="ja"),
            FakeTrack(index=2, relative_index=1, type=TrackType.AUDIO, codec_name="aac", language="en"),
            FakeTrack(index=3, relative_index=0, type=TrackType.SUB, codec_name="ass", language="en", title="English Full"),
            FakeTrack(index=4, relative_index=1, type=TrackType.SUB, codec_name="ass", language="de", title="German Full"),
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

    assert [track_language(track.track) for track in plan.selection.audio] == ["en"]
    assert plan.selection.subtitles == []
    assert len(plan.subtitle_transforms) == 1
    assert plan.subtitle_transforms[0].language == "en"
    assert plan.selection.attachments_from == []


def test_plan_single_keeps_attachments_when_untransformed_subtitles_remain() -> None:
    source = SourceFile(
        path=Path("source.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.VIDEO, codec_name="hevc", language="ja"),
            FakeTrack(index=1, relative_index=0, type=TrackType.SUB, codec_name="ass", language="en", title="English Full"),
            FakeTrack(index=2, relative_index=1, type=TrackType.SUB, codec_name="ass", language="de", title="German Full"),
        ],
    )

    plan = plan_single(
        source,
        Path("out.mkv"),
        restyle_subs=True,
        restyle_languages=["en"],
    )

    assert [track_language(track.track) for track in plan.selection.subtitles] == ["de"]
    assert [track.language for track in plan.subtitle_transforms] == ["en"]
    assert plan.selection.attachments_from == []


def test_plan_single_uses_pre_rewrite_language_defaults() -> None:
    source = SourceFile(
        path=Path("source.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.VIDEO, codec_name="hevc", language="ja"),
            FakeTrack(index=1, relative_index=0, type=TrackType.AUDIO, codec_name="flac", language="ja"),
            FakeTrack(index=2, relative_index=1, type=TrackType.AUDIO, codec_name="aac", language="en"),
            FakeTrack(index=3, relative_index=2, type=TrackType.AUDIO, codec_name="aac", language="de"),
            FakeTrack(index=4, relative_index=3, type=TrackType.AUDIO, codec_name="aac", language="fr"),
            FakeTrack(index=5, relative_index=0, type=TrackType.SUB, codec_name="ass", language="en", title="English Full"),
            FakeTrack(index=6, relative_index=1, type=TrackType.SUB, codec_name="ass", language="de", title="German Full"),
            FakeTrack(index=7, relative_index=2, type=TrackType.SUB, codec_name="ass", language="fr", title="French Full"),
        ],
    )

    plan = plan_single(source, Path("out.mkv"), remove_unnecessary=True, restyle_subs=True)

    assert [track_language(track.track) for track in plan.selection.audio] == ["ja", "en", "de"]
    assert [track_language(track.track) for track in plan.selection.subtitles] == []
    assert [track.language for track in plan.subtitle_transforms] == ["en", "de"]


def test_plan_single_marks_metadata_only_runs_as_direct_postprocess() -> None:
    source = SourceFile(
        path=Path("source.mkv"),
        tracks=[
            FakeTrack(index=0, relative_index=0, type=TrackType.VIDEO, codec_name="hevc", language="ja"),
            FakeTrack(index=1, relative_index=0, type=TrackType.AUDIO, codec_name="flac", language="ja"),
        ],
    )

    plan = plan_single(source, Path("out.mkv"), mkv_title="Title", fix_tags=True)

    assert plan.direct_postprocess_source == source.path
