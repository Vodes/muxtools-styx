from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner
from muxtools import ParsedFile, Premux, Setup, SubFile, TrackType, mux

from muxtools_styx.cli import app
from muxtools_styx.postprocess import apply_metadata_postprocess
from muxtools_styx.planner import inspect_path


TEST_DATA_DIR = Path(__file__).parent / "test-data"
SAMPLE_DIR = TEST_DATA_DIR / "sample-files"
INPUT_DIR = TEST_DATA_DIR / "input"

pytestmark = pytest.mark.skipif(
    not SAMPLE_DIR.exists() or not shutil.which("ffprobe") or not shutil.which("mkvmerge"),
    reason="Requires checked-out test-data plus ffprobe and mkvmerge on PATH.",
)


def test_pair_execute_sets_requested_mkv_title(tmp_path: Path) -> None:
    donor = SAMPLE_DIR / "H265-Opus-AAC-sample.mkv"
    target = SAMPLE_DIR / "H264-10bit-FLAC-sample.mkv"
    output = tmp_path / "pair-output.mkv"

    result = CliRunner().invoke(
        app,
        [
            "pair",
            str(donor),
            str(target),
            "-o",
            str(output),
            "--keep-audio",
            "--mkv-title",
            "Styx Integration Test",
            "--execute",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.exists()

    parsed = inspect_path(output)
    assert parsed.container_title == "Styx Integration Test"
    assert [track.language for track in parsed.audio_tracks] == ["ja", "en", "de"]


def test_fix_tags_postprocess_updates_real_audio_and_subtitle_flags(tmp_path: Path) -> None:
    setup = Setup("tag-fix-test", None, allow_binary_download=False, out_dir=str(tmp_path), work_dir=str(tmp_path / "_workdir"), debug=False)
    setup.edit("mkv_title_naming", "")
    setup.edit("skip_mux_branding", True)

    source = SAMPLE_DIR / "H264-10bit-FLAC-sample.mkv"
    full_sub = INPUT_DIR / "vigilantes_s01e01_en.ass"
    sign_sub = INPUT_DIR / "atri-subkt" / "ATRI 03 - TS (Nyarthur).ass"
    output = tmp_path / "tag-fix-source.mkv"

    mux(
        Premux(source, subtitles=None, keep_attachments=False),
        SubFile(full_sub).to_track("English Full Subtitles", "ja", default=False, forced=False),
        SubFile(sign_sub).to_track("Signs & Songs", "en", default=True, forced=False),
        outfile=output,
        quiet=True,
        print_cli=False,
    )

    fixed = apply_metadata_postprocess(output, fix_tags=True)
    parsed = ParsedFile.from_file(fixed)

    audio_tracks = parsed.find_tracks(type=TrackType.AUDIO)
    assert audio_tracks
    assert all(track.is_default for track in audio_tracks)
    assert all(not track.is_forced for track in audio_tracks)

    subtitle_tracks = parsed.find_tracks(type=TrackType.SUB)
    assert len(subtitle_tracks) == 2

    full_track = subtitle_tracks[0]
    sign_track = subtitle_tracks[1]

    assert full_track.sanitized_lang.to_tag() == "en"
    assert full_track.is_default
    assert not full_track.is_forced

    assert sign_track.sanitized_lang.to_tag() == "en"
    assert not sign_track.is_default
    assert sign_track.is_forced


def test_single_execute_remove_unnecessary_filters_real_tracks(tmp_path: Path) -> None:
    source = SAMPLE_DIR / "H265-Opus-AAC-sample.mkv"
    output = tmp_path / "single-filtered.mkv"

    result = CliRunner().invoke(
        app,
        [
            "single",
            str(source),
            "-o",
            str(output),
            "--remove-unnecessary",
            "--audio-language",
            "en",
            "--execute",
        ],
    )

    assert result.exit_code == 0, result.output
    parsed = inspect_path(output)
    assert len(parsed.video_tracks) == 1
    assert [track.language for track in parsed.audio_tracks] == ["en"]


def test_single_execute_restyles_real_subtitles(tmp_path: Path) -> None:
    setup = Setup("single-restyle-source", None, allow_binary_download=False, out_dir=str(tmp_path), work_dir=str(tmp_path / "_workdir_src"), debug=False)
    setup.edit("mkv_title_naming", "")
    setup.edit("skip_mux_branding", True)

    source = SAMPLE_DIR / "H264-10bit-FLAC-sample.mkv"
    full_sub = INPUT_DIR / "vigilantes_s01e01_en.ass"
    intermediate = tmp_path / "single-restyle-source.mkv"
    output = tmp_path / "single-restyled.mkv"

    mux(
        Premux(source, subtitles=None, keep_attachments=False),
        SubFile(full_sub).to_track("English Full Subtitles", "en", default=True, forced=False),
        outfile=intermediate,
        quiet=True,
        print_cli=False,
    )

    result = CliRunner().invoke(
        app,
        [
            "single",
            str(intermediate),
            "-o",
            str(output),
            "--restyle-subs",
            "--restyle-language",
            "en",
            "--execute",
        ],
    )

    assert result.exit_code == 0, result.output
    parsed = ParsedFile.from_file(output)
    subtitle_tracks = parsed.find_tracks(type=TrackType.SUB)
    assert len(subtitle_tracks) == 1

    extracted = SubFile.from_mkv(output, 0)
    expected = SubFile(TEST_DATA_DIR / "output" / "vigilantes_s01e01_en_unfuck_cr_restyled.ass")

    extracted_doc = extracted._read_doc()
    expected_doc = expected._read_doc()

    for style_ac, style_ex in zip(extracted_doc.styles, expected_doc.styles, strict=True):
        assert style_ac.name == style_ex.name

    for line_ac, line_ex in zip(extracted_doc.events, expected_doc.events, strict=True):
        assert line_ac.text == line_ex.text
        assert line_ac.style == line_ex.style


def test_single_execute_restyle_does_not_double_apply_subtitle_delay(tmp_path: Path) -> None:
    setup = Setup("single-restyle-delay-source", None, allow_binary_download=False, out_dir=str(tmp_path), work_dir=str(tmp_path / "_workdir_delay_src"), debug=False)
    setup.edit("mkv_title_naming", "")
    setup.edit("skip_mux_branding", True)

    source = SAMPLE_DIR / "H264-10bit-FLAC-sample.mkv"
    full_sub = INPUT_DIR / "vigilantes_s01e01_en.ass"
    delayed_source = tmp_path / "single-restyle-delayed-source.mkv"
    output = tmp_path / "single-restyle-delayed-output.mkv"

    mux(
        Premux(source, subtitles=None, keep_attachments=False),
        SubFile(full_sub).to_track("English Full Subtitles", "en", default=True, forced=False, args=["--sync", "0:1500"]),
        outfile=delayed_source,
        quiet=True,
        print_cli=False,
    )

    original_extracted = SubFile.from_mkv(delayed_source, 0, preserve_delay=False)
    original_doc = original_extracted._read_doc()
    original_first = next(ev for ev in original_doc.events if getattr(ev, "TYPE", None) == "Dialogue")

    result = CliRunner().invoke(
        app,
        [
            "single",
            str(delayed_source),
            "-o",
            str(output),
            "--restyle-subs",
            "--restyle-language",
            "en",
            "--execute",
        ],
    )

    assert result.exit_code == 0, result.output

    restyled_extracted = SubFile.from_mkv(output, 0, preserve_delay=False)
    restyled_doc = restyled_extracted._read_doc()
    restyled_first = next(ev for ev in restyled_doc.events if getattr(ev, "TYPE", None) == "Dialogue")

    parsed = ParsedFile.from_file(output)
    subtitle_track = parsed.find_tracks(type=TrackType.SUB)[0]
    original_track = ParsedFile.from_file(delayed_source).find_tracks(type=TrackType.SUB)[0]

    assert restyled_first.start == original_first.start
    assert subtitle_track.container_delay == original_track.container_delay
