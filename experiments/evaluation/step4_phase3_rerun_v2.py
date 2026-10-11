"""Rerun of Step 4's Phase 3 pass, adding v_ab/v_ba (the 2^|S|-2 non-trivial
S-subset coalition values, per direction) and w_full to each line, so the
single-anchor OAT readings (v_XY({i}), v_YX({i})) become available -- both
this and "save every pair's v tables" are KT requirements the first pass
didn't satisfy.

Nothing else in the schema changes (_phase3_pair_report's save_v_tables=False
path is byte-for-byte what the original run used). Writes to
phase3_results_v2.jsonl / phase3_summary_v2.json / phase3_exclusions_v2.json
-- the original phase3_results.jsonl / phase3_summary.json /
phase3_exclusions.json are never opened for writing here.

Reuses the SAME 100 chains (chains.json, unchanged) and the SAME saved
Phase 1 classification (ensemble_phase1.json's "pairs", unchanged) --
only the physics (deterministic, cheap) and the Phase 3 pass itself
(the expensive part, and the only part that needed to change) are redone.

Run standalone: caffeinate -i python3 -u -m experiments.evaluation.step4_phase3_rerun_v2
"""

from __future__ import annotations

import json

from pvdials.config import load_defaults
from pvdials.physics.pipeline import run_pipeline
from pvdials.physics.shared_inputs import shared_inputs_for
from pvdials.warning_filter import ChandrupatlaWarningFilter

import experiments.evaluation.step4_ensemble as s4
from experiments.evaluation.chain_population import build_configs, default_hardware
from experiments.evaluation.step0_measure_phase3 import _shared
from experiments.evaluation.weather_source import verify_thesis_weather_file


def main() -> None:
    weather_info = verify_thesis_weather_file()
    s4.log(f"Weather file verified: {weather_info}")

    chains = json.loads((s4.OUT_DIR / "chains.json").read_text())["chains"]
    ensemble_phase1 = json.loads((s4.OUT_DIR / "ensemble_phase1.json").read_text())
    phase1_records = ensemble_phase1["pairs"]
    s4.log(f"Loaded {len(chains)} chains and {len(phase1_records)} saved Phase 1 records (unchanged).")

    defaults = load_defaults()
    module, mounting = default_hardware()
    all_configs = {c.label: c for c in build_configs(module, mounting)}

    s4.log("Rebuilding the 100 chains' physics (deterministic, same as the original run)...")
    with ChandrupatlaWarningFilter() as wf:
        shared_cec, shared_adr, daylight = _shared()
        results_by_label = {}
        for label in chains:
            config = all_configs[label]
            shared = shared_inputs_for(config, shared_cec, shared_adr)
            results_by_label[label] = run_pipeline(config, shared, defaults)
    if wf.count:
        s4.log(f"({wf.count} known scipy chandrupatla 0/0 warnings suppressed)")
    s4.log(f"Ran {len(results_by_label)} chains' physics.")

    s4.log("Rerunning Phase 3 on eligible pairs, this time saving v_ab/v_ba/w_full (record=False)...")
    s4.run_phase3_on_ensemble(
        all_configs, results_by_label, shared_cec, shared_adr, daylight, defaults, phase1_records,
        jsonl_filename="phase3_results_v2.jsonl",
        summary_filename="phase3_summary_v2.json",
        exclusions_filename="phase3_exclusions_v2.json",
        save_v_tables=True,
    )
    s4.log("Rerun complete.")


if __name__ == "__main__":
    main()
