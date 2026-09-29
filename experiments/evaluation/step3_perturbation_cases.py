"""Evaluation KT Step 3: three perturbation cases via tests/dla/mock_adapters.py
on the real Colombo file. Every perturbation value is fixed in the approved
plan; results are reported as measured, never retuned afterwards to make a
case "pass" -- there is no pass/fail here except the one internal-consistency
check inside case 3 (the code's phi against the Shapley formula applied to
the measured v table).

Run standalone: python3 -m experiments.evaluation.step3_perturbation_cases
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from pvdials.config import load_defaults
from pvdials.dla.metrics import stage_series
from pvdials.dla.phase1 import run_phase1
from pvdials.dla.phase3 import Phase3NotComputable, run_phase3
from pvdials.physics.pipeline import run_pipeline
from pvdials.types import PipelineConfig, Stage
from pvdials.warning_filter import ChandrupatlaWarningFilter

from experiments.evaluation.baselines import baseline_a_stage, baseline_b_stage
from experiments.evaluation.comparators import averaged_game, shapley_values
from experiments.evaluation.step0_measure_phase3 import _shared
from experiments.evaluation.weather_source import verify_thesis_weather_file
from tests.dla.mock_adapters import install_mock_model, install_mock_temperature_model

OUT_DIR = Path(__file__).resolve().parent / "outputs" / "step3"

CONFIG_A = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")


def case1_phase1(shared_cec, shared_adr, daylight, defaults) -> dict:
    """Small perturbation (delta=0.03) at TRANSPOSITION, sized to stay under
    tau; large perturbation (delta=0.50) at DC, sized to clear it. Stage 1
    (decomposition), 3 (temperature model itself) and 5 (ac model itself)
    are the same model name on both sides.
    """
    mp = pytest.MonkeyPatch()
    try:
        install_mock_model(mp, Stage.TRANSPOSITION, "mock_transposition_small", "isotropic", delta=0.03)
        install_mock_model(mp, Stage.DC, "mock_dc_large", "singlediode_cec", delta=0.50)
        config_b = PipelineConfig(
            "B", "erbs", "mock_transposition_small", "faiman", "mock_dc_large", "sandia"
        )
        result_a = run_pipeline(CONFIG_A, shared_cec, defaults)
        result_b = run_pipeline(config_b, shared_cec, defaults)
        phase1 = run_phase1(CONFIG_A, result_a, config_b, result_b, daylight, defaults=defaults)
    finally:
        mp.undo()

    nrmsd_by_stage = {s: phase1.metrics[s].nrmsd for s in Stage}
    baseline_a = baseline_a_stage(phase1.differing_stages)
    baseline_b = baseline_b_stage(nrmsd_by_stage)

    return {
        "construction": {
            "shared_stages": ["DECOMPOSITION", "TEMPERATURE_model", "AC_model"],
            "TRANSPOSITION_delta": 0.03,
            "DC_delta": 0.50,
        },
        "estimated_nrmsd_before_running": {
            "DECOMPOSITION": 0.0,
            "TRANSPOSITION": "~0.01-0.015",
            "TEMPERATURE": "~0.005-0.01",
            "DC": "~0.15-0.25",
            "AC": "~0.15-0.25",
        },
        "measured_nrmsd": {s.name: nrmsd_by_stage[s] for s in Stage},
        "outcome": phase1.outcome,
        "k": phase1.k.name if phase1.k is not None else None,
        "baseline_a": baseline_a.name,
        "baseline_b": baseline_b.name,
        "expected": {"k": "DC", "baseline_a": "TRANSPOSITION", "baseline_b": "DC"},
        "matches_expectation": {
            "k": (phase1.k.name if phase1.k else None) == "DC",
            "baseline_a": baseline_a.name == "TRANSPOSITION",
            "baseline_b": baseline_b.name == "DC",
        },
    }


def case2_one_perturbed_stage(shared_cec, shared_adr, daylight, defaults) -> dict:
    """A perturbation at TEMPERATURE only (delta=0.10, rise-above-ambient
    perturbation). |S|=1 by construction, so 100% of phi_final must go to
    TEMPERATURE regardless of whether Phase 1's outcome gate admits the pair
    in production -- run_phase3 is called directly either way, per the KT's
    own fallback for a case that might not reach outcome 2/3.
    """
    mp = pytest.MonkeyPatch()
    try:
        install_mock_temperature_model(mp, "mock_temperature_only", "faiman", delta=0.10)
        config_b = PipelineConfig(
            "B2", "erbs", "isotropic", "mock_temperature_only", "singlediode_cec", "sandia"
        )
        result_a = run_pipeline(CONFIG_A, shared_cec, defaults)
        result_b = run_pipeline(config_b, shared_cec, defaults)
        phase1 = run_phase1(CONFIG_A, result_a, config_b, result_b, daylight, defaults=defaults)
        result3 = run_phase3(
            CONFIG_A, result_a, config_b, result_b,
            shared_cec=shared_cec, shared_adr=shared_adr, daylight=daylight,
            defaults=defaults, record=False,
        )
    finally:
        mp.undo()

    if isinstance(result3, Phase3NotComputable) or isinstance(result3, str):
        return {
            "construction": {"TEMPERATURE_delta": 0.10, "mode": "rise-above-ambient multiplicative"},
            "phase1_outcome": phase1.outcome,
            "phase3_status": "not computable" if isinstance(result3, Phase3NotComputable) else result3,
        }

    return {
        "construction": {"TEMPERATURE_delta": 0.10, "mode": "rise-above-ambient multiplicative"},
        "phase1_outcome": phase1.outcome,
        "phase1_k": phase1.k.name if phase1.k else None,
        "share_TEMPERATURE": result3.share[Stage.TEMPERATURE],
        "phi_final": {s.name: result3.phi_final[s] for s in Stage},
        "expected_share_TEMPERATURE": 1.0,
        "matches_expectation": result3.share[Stage.TEMPERATURE] == pytest.approx(1.0, abs=1e-9),
    }


def case3_two_multiplicative(shared_cec, shared_adr, daylight, defaults) -> dict:
    """a=0.30 at TRANSPOSITION, c=0.10 at AC (the KT's own example values).
    Paper formulas are for the A-anchored direction; compared against the
    measured v_ab. The exact internal-consistency check (code's phi_final
    against the Shapley formula applied to the measured v table) is the
    real pass/fail; paper-vs-measured is reported with its cause, never a
    stop condition.
    """
    a, c = 0.30, 0.10
    mp = pytest.MonkeyPatch()
    try:
        install_mock_model(mp, Stage.TRANSPOSITION, "mock_transposition_a30", "isotropic", delta=a)
        install_mock_model(mp, Stage.AC, "mock_ac_c10", "sandia", delta=c)
        config_b = PipelineConfig(
            "B3", "erbs", "mock_transposition_a30", "faiman", "singlediode_cec", "mock_ac_c10"
        )
        result_a = run_pipeline(CONFIG_A, shared_cec, defaults)
        result_b = run_pipeline(config_b, shared_cec, defaults)
        result3 = run_phase3(
            CONFIG_A, result_a, config_b, result_b,
            shared_cec=shared_cec, shared_adr=shared_adr, daylight=daylight,
            defaults=defaults, record=False,
        )
        anchor_ac = stage_series(result_a.outputs, Stage.AC, daylight)
    finally:
        mp.undo()

    r = float(np.sqrt(np.mean(np.asarray(anchor_ac, dtype=float) ** 2)))

    paper_v = {
        "v_ab({TRANSPOSITION})": a * r,
        "v_ab({AC})": c * r,
        "v_ab({TRANSPOSITION,AC})": (a + c + a * c) * r,
        "phi_ab(TRANSPOSITION)": (a + a * c / 2) * r,
        "phi_ab(AC)": (c + a * c / 2) * r,
    }

    key_t = frozenset({Stage.TRANSPOSITION})
    key_ac = frozenset({Stage.AC})
    key_tac = frozenset({Stage.TRANSPOSITION, Stage.AC})
    measured_v = {
        "v_ab({TRANSPOSITION})": result3.v_ab[key_t],
        "v_ab({AC})": result3.v_ab[key_ac],
        "v_ab({TRANSPOSITION,AC})": result3.v_ab[key_tac],
        "phi_ab(TRANSPOSITION)": result3.phi_ab[Stage.TRANSPOSITION],
        "phi_ab(AC)": result3.phi_ab[Stage.AC],
    }

    diffs = {
        k: {
            "paper": paper_v[k], "measured": measured_v[k],
            "absolute_diff": measured_v[k] - paper_v[k],
            "relative_diff": (measured_v[k] - paper_v[k]) / paper_v[k] if paper_v[k] != 0 else None,
        }
        for k in paper_v
    }

    # The exact, internal-consistency check -- a stop condition if it fails.
    w = averaged_game(result3.v_ab, result3.v_ba)
    independent_phi = shapley_values(w, tuple(Stage))
    production_phi_final = result3.phi_final
    max_relative_diff = max(
        abs(independent_phi[s] - production_phi_final[s]) / max(abs(production_phi_final[s]), 1e-12)
        for s in Stage
    )

    return {
        "construction": {"a": a, "c": c, "R_measured": r},
        "paper_vs_measured": diffs,
        "note": "differences attributed to the linearity assumption (AC scales "
                "linearly with POA), not the Shapley formula -- v_ab({AC}) has no "
                "such assumption and is expected closer to exact.",
        "internal_consistency_check": {
            "max_relative_diff_phi_final_vs_independent_shapley_of_averaged_game": max_relative_diff,
            "within_1e-9": max_relative_diff <= 1e-9,
        },
    }


def main() -> None:
    weather_info = verify_thesis_weather_file()
    print(f"Weather file verified: {weather_info}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    defaults = load_defaults()
    with ChandrupatlaWarningFilter() as wf:
        shared_cec, shared_adr, daylight = _shared()
        report = {
            "weather_file": weather_info,
            "case1_phase1": case1_phase1(shared_cec, shared_adr, daylight, defaults),
            "case2_one_perturbed_stage": case2_one_perturbed_stage(shared_cec, shared_adr, daylight, defaults),
            "case3_two_multiplicative": case3_two_multiplicative(shared_cec, shared_adr, daylight, defaults),
        }
    if wf.count:
        print(f"({wf.count} known scipy chandrupatla 0/0 warnings suppressed)")
    print(json.dumps(report, indent=2, default=str))
    (OUT_DIR / "perturbation_cases.json").write_text(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
