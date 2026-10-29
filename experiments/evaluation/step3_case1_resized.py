"""Step 3, case 1 with the transposition perturbation resized: delta 0.0075
(case 1 uses 0.03) gives a transposition nRMSD of about 0.005, under the
0.5 h tau of 0.013, so Phase 1 should skip transposition and name DC while
Baseline A (the first stage whose model differs) names transposition. DC
keeps delta 0.50. The delta was set once, from a scan of 0.006-0.009 (nRMSD
0.0039-0.0058), then fixed.

step3_perturbation_cases.py and its outputs are untouched. Writes
step3_<offset>/case1_resized.json (a non-zero offset is required).

Run: PVDIAL_OFFSET_H=0.5 PVDIAL_TAU=0.013 python3 -m experiments.evaluation.step3_case1_resized
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pvdials.dla.phase1 import run_phase1
from pvdials.physics.pipeline import run_pipeline
from pvdials.types import PipelineConfig, Stage
from pvdials.warning_filter import ChandrupatlaWarningFilter

from experiments.evaluation.baselines import baseline_a_stage, baseline_b_stage
from experiments.evaluation.step0_measure_phase3 import _shared
from experiments.evaluation.step3_perturbation_cases import CONFIG_A
from experiments.evaluation.weather_source import verify_thesis_weather_file
from experiments.tau_calibration.run_settings import OFFSET_H, output_dir, require_tau, run_defaults, run_record
from tests.dla.mock_adapters import install_mock_model

OUT_DIR = output_dir(Path(__file__).resolve().parent / "outputs" / "step3")
TRANSPOSITION_DELTA = 0.0075
DC_DELTA = 0.50


def main() -> None:
    if OFFSET_H == 0.0:
        raise SystemExit("STOP: this writes only to an offset folder -- set PVDIAL_OFFSET_H.")
    require_tau()
    weather_info = verify_thesis_weather_file()
    shared_cec, _, daylight = _shared()
    defaults = run_defaults()
    mp = pytest.MonkeyPatch()
    try:
        with ChandrupatlaWarningFilter():
            install_mock_model(mp, Stage.TRANSPOSITION, "mock_transposition_small", "isotropic", delta=TRANSPOSITION_DELTA)
            install_mock_model(mp, Stage.DC, "mock_dc_large", "singlediode_cec", delta=DC_DELTA)
            config_b = PipelineConfig("B", "erbs", "mock_transposition_small", "faiman", "mock_dc_large", "sandia")
            result_a = run_pipeline(CONFIG_A, shared_cec, defaults)
            result_b = run_pipeline(config_b, shared_cec, defaults)
            phase1 = run_phase1(CONFIG_A, result_a, config_b, result_b, daylight, defaults=defaults)
    finally:
        mp.undo()

    nrmsd = {s: phase1.metrics[s].nrmsd for s in Stage}
    k = phase1.k.name if phase1.k is not None else None
    baseline_a = baseline_a_stage(phase1.differing_stages).name
    report = {
        "run_record": run_record(shared_cec.ctx),
        "weather_file": weather_info,
        "construction": {"TRANSPOSITION_delta": TRANSPOSITION_DELTA, "DC_delta": DC_DELTA,
                         "shared_stages": ["DECOMPOSITION", "TEMPERATURE_model", "AC_model"]},
        "measured_nrmsd": {s.name: v for s, v in nrmsd.items()},
        "outcome": phase1.outcome,
        "k": k,
        "baseline_a": baseline_a,
        "baseline_b": baseline_b_stage(nrmsd).name,
        "expected": {"k": "DC", "baseline_a": "TRANSPOSITION", "baseline_b": "DC"},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "case1_resized.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
