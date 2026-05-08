from click.testing import CliRunner

from muxtools_styx.cli import app


def test_root_help_includes_debug_flag() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--debug / --no-debug" in result.output


def test_pair_help_includes_fix_tags_flag() -> None:
    result = CliRunner().invoke(app, ["pair", "--help"])

    assert result.exit_code == 0
    assert "--fix-tags / --no-fix-tags" in result.output
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
