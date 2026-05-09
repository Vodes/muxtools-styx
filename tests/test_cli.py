from pathlib import Path

from click.testing import CliRunner

from muxtools_styx.cli import app


def test_root_help_includes_debug_flag() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--debug / --no-debug" in result.output


def test_pair_help_includes_fix_tags_flag() -> None:
    result = CliRunner().invoke(app, ["pair", "--help"])

    assert result.exit_code == 0
    assert "Use TARGET as the base file and copy selected tracks from DONOR." in result.output
    assert "--fix-tags / --no-fix-tags" in result.output
    assert "--remove-unnecessary / --keep-all-tracks" in result.output
    assert "--restyle-subs / --no-restyle-subs" in result.output
    assert "--keep-subs-missing-languages / --no-keep-subs-missing-languages" in result.output
    assert "--keep-video / --use-target-video" in result.output
    assert "--best-audio / --no-best-audio" in result.output
    assert "[default: no-keep-audio]" in result.output
    assert "[default: execute]" in result.output


def test_single_help_includes_single_file_options() -> None:
    result = CliRunner().invoke(app, ["single", "--help"])

    assert result.exit_code == 0
    assert "--remove-unnecessary / --keep-all-tracks" in result.output
    assert "--restyle-subs / --no-restyle-subs" in result.output
    assert "[default: execute]" in result.output


def test_batch_help_includes_single_transform_options() -> None:
    result = CliRunner().invoke(app, ["batch", "--help"])

    assert result.exit_code == 0
    assert "--remove-unnecessary / --keep-all-tracks" in result.output
    assert "--restyle-subs / --no-restyle-subs" in result.output


def test_single_execute_surfaces_runtime_errors_without_traceback(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "input.mkv"
    source.write_bytes(b"placeholder")

    class FakePlan:
        def to_dict(self):
            return {"mode": "single"}

    monkeypatch.setattr("muxtools_styx.cli.inspect_path", lambda path: object())
    monkeypatch.setattr("muxtools_styx.cli.plan_single", lambda *args, **kwargs: FakePlan())
    monkeypatch.setattr("muxtools_styx.cli.plan_can_skip_mux", lambda plan: False)

    def fail_execute(plan, debug=False):
        raise RuntimeError("Failed to collect fonts for subtitle 'broken.ass'.")

    monkeypatch.setattr("muxtools_styx.cli.execute_plan", fail_execute)

    result = CliRunner().invoke(app, ["single", str(source), "--execute"])

    assert result.exit_code != 0
    assert "Error: Failed to collect fonts for subtitle 'broken.ass'." in result.output
