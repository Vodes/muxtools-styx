from pathlib import Path

from muxtools_styx.executor import execute_plan
from muxtools_styx.models import MuxPlan, SelectionPlan, SingleTransformOptions


def test_execute_plan_skips_mux_for_direct_postprocess_copy(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    output = tmp_path / "output.mkv"
    source.write_bytes(b"not-a-real-mkv-but-good-enough-for-copy")

    plan = MuxPlan(
        mode="single",
        output=output,
        sources=[source],
        selection=SelectionPlan(),
        mkv_title="Test",
        fix_tags=True,
        direct_postprocess_source=source,
    )

    def fail_mux(*args, **kwargs):
        raise AssertionError("mux() should not be called for metadata-only single plans.")

    def fake_postprocess(path: Path, mkv_title: str | None = None, fix_tags: bool = False) -> Path:
        assert path == output
        assert output.read_bytes() == source.read_bytes()
        assert mkv_title == "Test"
        assert fix_tags is True
        return path

    monkeypatch.setattr("muxtools_styx.executor.mux", fail_mux)
    monkeypatch.setattr("muxtools_styx.executor.apply_metadata_postprocess", fake_postprocess)

    assert execute_plan(plan) == output


def test_execute_plan_runs_post_mux_single_as_second_pass(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    output = tmp_path / "output.mkv"
    source.write_bytes(b"placeholder")

    plan = MuxPlan(
        mode="pair",
        output=output,
        sources=[source],
        selection=SelectionPlan(),
        post_mux_single=SingleTransformOptions(restyle_subs=True, restyle_languages=["en"]),
    )

    first_pass_output = tmp_path / "_workdir" / "output" / "output.merged.mkv"

    class FakeSource:
        pass

    def fake_execute_followup(plan_arg, debug=False):
        if plan_arg.output == first_pass_output:
            return first_pass_output
        assert plan_arg.output == output
        assert plan_arg.fix_tags is False
        assert plan_arg.mkv_title is None
        assert plan_arg.post_mux_single is None
        return output

    def fake_plan_single(source_arg, output_arg, **kwargs):
        assert source_arg.__class__.__name__ == "FakeSource"
        assert output_arg == output
        assert kwargs["restyle_subs"] is True
        assert kwargs["restyle_languages"] == ["en"]
        return MuxPlan(mode="single", output=output, sources=[first_pass_output], selection=SelectionPlan())

    monkeypatch.setattr("muxtools_styx.executor.execute_plan", fake_execute_followup)
    monkeypatch.setattr("muxtools_styx.executor.inspect_source", lambda path: FakeSource(), raising=False)
    monkeypatch.setattr("muxtools_styx.executor.plan_single", fake_plan_single, raising=False)

    # Import paths are local in the helper, so patch the real modules too.
    monkeypatch.setattr("muxtools_styx.muxtools_adapter.inspect_source", lambda path: FakeSource())
    monkeypatch.setattr("muxtools_styx.planner.plan_single", fake_plan_single)

    assert execute_plan(plan) == output
