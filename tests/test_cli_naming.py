from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from muxtools import ParsedFile, get_setup_attr
from muxtools.muxing.muxer import output_names

from muxtools_styx import cli
from muxtools_styx import mux as mux_module
from muxtools_styx import selection as selection_module
from muxtools_styx.mux import resolve_setup_output
from muxtools_styx.selection import Selection


@pytest.mark.parametrize(("command", "episode_override"), [("mux", None), ("mux", "7"), ("batch", None)])
@pytest.mark.parametrize("padding", [None, 3])
@pytest.mark.parametrize("custom_templates", [False, True])
def test_cli_episode_padding_in_filename_and_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    padding: int | None,
    custom_templates: bool,
    episode_override: str | None,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("vof_setup", "{}")
    target_dir = tmp_path / "targets"
    target_dir.mkdir()
    target = target_dir / "Cyberpunk.Edgerunners.S02E01.mkv"
    target.touch()
    out_dir = tmp_path / "muxed"
    parsed = cast(ParsedFile, object())
    selection = Selection((), (), (), target)
    monkeypatch.setattr(ParsedFile, "from_file", lambda *_args: parsed)
    monkeypatch.setattr(selection_module, "select_tracks", lambda *_args, **_kwargs: selection)
    monkeypatch.setattr(cli, "composed_media", lambda *_args: parsed)
    monkeypatch.setattr(mux_module, "composed_media", lambda *_args: parsed)
    results: list[tuple[Path, str, str]] = []

    def fake_mux(_target: Path, *, outfile: Path | None = None, **_kwargs: object) -> Path:
        output = outfile or resolve_setup_output(parsed, selection)
        title = output_names()[1]
        results.append((output, title, str(get_setup_attr("episode"))))
        return output

    monkeypatch.setattr(cli, "process_mux", fake_mux)
    monkeypatch.setattr(mux_module, "process_mux", fake_mux)
    arguments = [command, str(target if command == "mux" else target_dir), "--out-dir", str(out_dir)]
    if padding is not None:
        arguments.extend(["--episode-padding", str(padding)])
    if episode_override is not None:
        arguments.extend(["--episode", episode_override])
    if custom_templates:
        arguments.extend(["--out-name", "$show$ - S02E$ep$", "--mkv-title", "$show$ - S02E$ep$"])
    cli.app(arguments, result_action="return_value")

    episode = (episode_override or "1").zfill(padding or 2)
    stem = f"Cyberpunk Edgerunners - S02E{episode}" if custom_templates else f"Cyberpunk Edgerunners - {episode}"
    filename = stem + (".mkv" if custom_templates else " (premux).mkv")
    assert results == [(out_dir / filename, stem, episode)]


@pytest.mark.parametrize("command", ["mux", "batch"])
@pytest.mark.parametrize("padding", [0, 1])
def test_cli_rejects_episode_padding_below_two(tmp_path: Path, command: str, padding: int) -> None:
    with pytest.raises(ValueError, match="episode_padding must be at least 2"):
        cli.app([command, str(tmp_path), "--episode-padding", str(padding)])


@pytest.mark.parametrize("flag", ["--episode", "-o", "--output"])
def test_batch_rejects_single_file_flags(tmp_path: Path, flag: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.app(["batch", str(tmp_path), flag, "01"])
    assert exc_info.value.code == 2


@pytest.mark.parametrize("episode", ["123", "0001", "OVA"])
def test_cli_preserves_long_episode_numbers_and_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, episode: str) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("vof_setup", "{}")
    setup = cli._setup(
        Path("Show - 01.mkv"),
        episode=episode,
        show_name=None,
        out_dir=tmp_path,
        out_name="$show$ - $ep$",
        mkv_title="$show$ - $ep$",
        clean_work_dirs=True,
    )
    assert setup.episode == episode


@pytest.mark.parametrize(("filename", "expected"), [("Show - 07.5.mkv", "07.5"), ("Show 4a.mkv", "4a")])
def test_cli_infers_non_integer_episode_labels(filename: str, expected: str) -> None:
    episode, _show = cli._infer_episode_and_show(Path(filename), None, None, 2)
    assert episode == expected


def test_cli_mux_explicit_out_dir_disables_in_place_and_in_place_skips_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("vof_setup", "{}")
    target = tmp_path / "Show - 01.mkv"
    target.touch()
    seen: list[dict[str, object]] = []

    def fake_mux(path: Path, **kwargs: object) -> Path:
        seen.append({"path": path, **kwargs})
        return path

    monkeypatch.setattr(cli, "process_mux", fake_mux)

    cli.app(["mux", str(target), "--fix-tags"], result_action="return_value")
    assert seen[-1]["allow_implicit_in_place"] is True
    assert not (tmp_path / "_workdir").exists()

    cli.app(["mux", str(target), "--fix-tags", "--out-dir", str(tmp_path / "stage")], result_action="return_value")
    assert seen[-1]["allow_implicit_in_place"] is False
    assert (tmp_path / "_workdir").exists()


def test_cli_validation_failure_does_not_create_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("vof_setup", "{}")
    target = tmp_path / "Show - 01.mkv"
    target.touch()
    with pytest.raises(ValueError, match="requires a donor"):
        cli.app(["mux", str(target), "--keep-video"], result_action="return_value")
    assert not (tmp_path / "_workdir").exists()

    with pytest.raises(FileNotFoundError):
        cli.app(["mux", str(tmp_path / "missing - 01.mkv")], result_action="return_value")
    assert not (tmp_path / "_workdir").exists()


def test_json_mode_routes_muxtools_logs_to_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import json
    import sys

    from muxtools import warn
    from muxtools.utils.log import logger as muxtools_logger

    monkeypatch.setattr(muxtools_logger, "handlers", list(muxtools_logger.handlers))
    target = tmp_path / "Show - 01.mkv"
    target.touch()

    def fake_mux(path: Path, **_kwargs: object) -> Path:
        warn("diagnostic message", fake_mux)
        return path

    monkeypatch.setattr(cli, "process_mux", fake_mux)
    monkeypatch.setattr(sys, "argv", ["muxtools-styx", "--json", "mux", str(target), "--fix-tags"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"output": str(target.resolve())}
    assert "diagnostic message" in captured.err
