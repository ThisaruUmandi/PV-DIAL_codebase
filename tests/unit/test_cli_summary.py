"""28/09 item (b): a failed pipeline check is named, with its problems, in the
CLI summary -- not just reported as checks_passed=False. Uses a stub run
object so no pipeline has to be executed (no database needed).
"""

from types import SimpleNamespace

from pvdials.__main__ import _print_summary
from pvdials.analysis import failed_check_names
from pvdials.data.validate import ValidationResult
from pvdials.report import StageSummary
from pvdials.types import PipelineConfig, Stage

_STAGE_SUMMARY = {
    Stage.DECOMPOSITION: StageSummary(model="erbs", dni_kwh_m2=1.0, dhi_kwh_m2=1.0),
    Stage.TRANSPOSITION: StageSummary(model="isotropic", poa_global_kwh_m2=1.0),
    Stage.TEMPERATURE: StageSummary(model="faiman", temp_cell_mean_c=30.0, temp_cell_max_c=60.0),
    Stage.DC: StageSummary(model="singlediode_cec", annual_energy_kwh=1.0),
    Stage.AC: StageSummary(model="sandia", annual_energy_kwh=1.0),
}


def _config(label: str) -> PipelineConfig:
    return PipelineConfig(label, "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")


def _stub_run(checks: dict) -> SimpleNamespace:
    labels = list(checks)
    return SimpleNamespace(
        name="stub",
        analysis_id="stub-id",
        load_result=SimpleNamespace(validation=ValidationResult()),
        site_result=SimpleNamespace(tier4=ValidationResult(), offset_report=()),
        pipelines=SimpleNamespace(
            configs={label: _config(label) for label in labels},
            checks=checks,
            annual_yield_kwh={label: 1.0 for label in labels},
        ),
        stage_summaries={label: _STAGE_SUMMARY for label in labels},
        phase1_results={},
        phase2_result=None,
        phase3_results={},
        reexec_result=None,
    )


def test_failed_check_names_lists_only_the_failing_checks():
    checks = {
        "decomposition": ValidationResult(),
        "ac_not_exceeding_dc": ValidationResult(passed=False, problems=["AC exceeds DC on 3 rows"]),
        "dc": ValidationResult(passed=False, problems=["non-finite p_dc"]),
    }
    assert failed_check_names(checks) == ["ac_not_exceeding_dc", "dc"]
    assert failed_check_names({"decomposition": ValidationResult()}) == []


def test_cli_summary_names_the_failed_check_and_its_problem(capsys):
    run = _stub_run(
        {
            "A": {"decomposition": ValidationResult()},
            "B": {
                "decomposition": ValidationResult(),
                "ac_not_exceeding_dc": ValidationResult(
                    passed=False, problems=["AC exceeds DC on 3 rows"]
                ),
            },
        }
    )

    _print_summary(run)
    out = capsys.readouterr().out

    assert "A: checks_passed=True" in out
    assert "B: checks_passed=False" in out
    assert "Failed checks: ac_not_exceeding_dc" in out
    assert "- AC exceeds DC on 3 rows" in out
    # Only B's failure is reported: exactly one "Failed checks" line.
    assert out.count("Failed checks:") == 1
