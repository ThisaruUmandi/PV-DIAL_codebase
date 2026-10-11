"""Evaluation KT Step 2, part 2/3:

1. A fresh canonical Colombo run (python -m pvdials run analysis.yaml,
   called directly), cross-checked: comparators.py's independent Shapley
   applied to the averaged game built from the real A-B/A-C v tables must
   match production's own phi_final within ε.
2. The real |S|=2 pair (first in label order over the 2,058-chain
   population): only v({i}), v({j}), v({i,j}) for both directions plus the
   averaged game -- no Shapley values, per Umee's own instruction (she
   computes them by hand first).

Run standalone: python3 experiments/evaluation/step2_colombo_and_pair.py
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from pvdials.analysis import build_results_dict, run_analysis, write_outputs
from pvdials.config import load_defaults
from pvdials.dla.phase1 import _differing_stages
from pvdials.dla.phase3 import pair_is_shapley_computable, run_phase3
from pvdials.physics.pipeline import run_pipeline
from pvdials.physics.shared_inputs import shared_inputs_for
from pvdials.types import Stage
from pvdials.warning_filter import ChandrupatlaWarningFilter

from experiments.evaluation.chain_population import build_configs, default_hardware
from experiments.evaluation.comparators import (
    averaged_game,
    parse_coalition_key,
    shapley_values,
)
from experiments.evaluation.step0_measure_phase3 import _shared
from experiments.evaluation.weather_source import verify_thesis_weather_file

REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_YAML = REPO_ROOT / "analysis.yaml"
OUT_DIR = Path(__file__).resolve().parent / "outputs" / "step2"


def _v_table_from_json(entries: list[dict]) -> dict[frozenset, float]:
    return {parse_coalition_key(e["coalition"]): e["value"] for e in entries}


def _stage_dict_from_json(entries: list[dict]) -> dict[Stage, float]:
    return {Stage[e["stage"]]: e["value"] for e in entries}


def run_colombo_check() -> dict:
    """Fresh canonical run; independent Shapley on the real v tables must
    match production's phi_final within ε (1e-9 relative) -- expected to
    hold exactly by construction (phi_final IS the Shapley value of the
    averaged game, by linearity of the Shapley formula), not a coincidence.
    """
    colombo_dir = OUT_DIR / "colombo"
    with ChandrupatlaWarningFilter() as wf:
        run = run_analysis(str(ANALYSIS_YAML))
    write_outputs(run, str(colombo_dir))
    if wf.count:
        print(f"  ({wf.count} known scipy chandrupatla 0/0 warnings suppressed)")
    results = build_results_dict(run)

    report = {}
    for pair_key in ("A-B", "A-C"):
        p3 = results["phase3"][pair_key]
        v_ab = _v_table_from_json(p3["v_ab"])
        v_ba = _v_table_from_json(p3["v_ba"])
        w = averaged_game(v_ab, v_ba)
        production_phi_final = _stage_dict_from_json(p3["phi_final"])

        phi = shapley_values(w, tuple(Stage))
        max_relative_diff = 0.0
        for stage in Stage:
            denom = max(abs(production_phi_final[stage]), 1e-12)
            max_relative_diff = max(max_relative_diff, abs(phi[stage] - production_phi_final[stage]) / denom)

        report[pair_key] = {
            "comparators_phi": {s.name: phi[s] for s in Stage},
            "production_phi_final": {s.name: production_phi_final[s] for s in Stage},
            "max_relative_diff": max_relative_diff,
            "matches_within_1e-9": max_relative_diff <= 1e-9,
        }
        print(f"{pair_key}: max relative diff (comparators vs production phi_final) = {max_relative_diff:.3e}")

    return report


def _find_first_s2_pair(configs) -> tuple:
    """The first pair, in label order (itertools.combinations order, same
    convention as the exhaustive cache's own pair enumeration), that
    differs at exactly two stages AND is Shapley-computable (every one of
    its 32 coalitions pool-valid) -- a |S|=2 pair whose two differing
    stages can't be freely recombined (e.g. a DC/AC v_dc mismatch) would
    give Phase3NotComputable, not a usable v table.
    """
    for config_a, config_b in itertools.combinations(configs, 2):
        if len(_differing_stages(config_a, config_b)) != 2:
            continue
        computable, _ = pair_is_shapley_computable(config_a, config_b)
        if computable:
            return config_a, config_b
    raise RuntimeError("No Shapley-computable |S|=2 pair found in the population")


def run_s2_pair_check() -> dict:
    module, mounting = default_hardware()
    configs = build_configs(module, mounting)
    config_a, config_b = _find_first_s2_pair(configs)
    s = sorted(_differing_stages(config_a, config_b), key=lambda s: s.value)
    print(f"First |S|=2 pair in label order: {config_a.label} vs {config_b.label}, S={[s_.name for s_ in s]}")

    defaults = load_defaults()
    shared_cec, shared_adr, daylight = _shared()

    shared_a = shared_inputs_for(config_a, shared_cec, shared_adr)
    shared_b = shared_inputs_for(config_b, shared_cec, shared_adr)
    result_a = run_pipeline(config_a, shared_a, defaults)
    result_b = run_pipeline(config_b, shared_b, defaults)

    result = run_phase3(
        config_a, result_a, config_b, result_b,
        shared_cec=shared_cec, shared_adr=shared_adr, daylight=daylight,
        defaults=defaults, record=False,
    )

    i, j = s[0], s[1]
    v_ab, v_ba = result.v_ab, result.v_ba
    w = averaged_game(v_ab, v_ba)
    key_i, key_j, key_ij = frozenset({i}), frozenset({j}), frozenset({i, j})

    def _table(v):
        return {
            f"v({{{i.name}}})": v[key_i],
            f"v({{{j.name}}})": v[key_j],
            f"v({{{i.name},{j.name}}})": v[key_ij],
        }

    report = {
        "pair": [config_a.label, config_b.label],
        "S": [i.name, j.name],
        "v_ab": _table(v_ab),
        "v_ba": _table(v_ba),
        "w_averaged": _table(w),
    }
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    weather_info = verify_thesis_weather_file()
    print(f"Weather file verified: {weather_info}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    colombo_report = {"weather_file": weather_info, **run_colombo_check()}
    (OUT_DIR / "colombo_check.json").write_text(json.dumps(colombo_report, indent=2))

    pair_report = {"weather_file": weather_info, **run_s2_pair_check()}
    (OUT_DIR / "two_stage_pair_v_tables.json").write_text(json.dumps(pair_report, indent=2))
