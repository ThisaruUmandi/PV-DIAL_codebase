"""Evaluation KT Step 4: the ensemble (100 chains, seed 20260929) and the
all-pairs population (2,116,653 pairs, from the existing exhaustive cache).

Phase 1 (informative rate vs Baseline A, Baseline B agreement) on both; then
Phase 3 (through the production code path, record=False) on the ensemble's
eligible pairs only.

Two real stop points (cache-consistency, not "unfavourable result"):
  1. the re-derived 30.27%/45.83% all-pairs figures must match the cache
     exactly;
  2. every ensemble pair's real nRMSD profile (via run_phase1()) must match
     the cache's own row within 1e-9 relative.

Run standalone (long): caffeinate -i python3 -u -m experiments.evaluation.step4_ensemble
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np

from pvdials.config import load_defaults
from pvdials.dla.phase1 import run_phase1
from pvdials.dla.phase3 import Phase3NotComputable, pair_is_shapley_computable, run_phase3
from pvdials.physics.pipeline import run_pipeline
from pvdials.physics.shared_inputs import shared_inputs_for
from pvdials.types import Stage
from pvdials.warning_filter import ChandrupatlaWarningFilter

from experiments.evaluation.baselines import baseline_a_stage, baseline_b_stage, informative_rate_parts
from experiments.evaluation.chain_population import build_configs, default_hardware, load_cached_labels, sample_chains
from experiments.evaluation.comparators import argmax_with_ties, attribution_gap, averaged_game, coalition_key, rank_agreement, shapley_values, wilson_interval
from experiments.evaluation.step0_measure_phase3 import _shared
from experiments.evaluation.weather_source import verify_thesis_weather_file

SEED = 20260929
ENSEMBLE_SIZE = 100
TAU = 0.093
STAGE_ORDER = (Stage.DECOMPOSITION, Stage.TRANSPOSITION, Stage.TEMPERATURE, Stage.DC, Stage.AC)
TAU_GRID = np.linspace(0, 1, 501)
BAND = (0.088, 0.098)

CACHE_DIR = Path(__file__).resolve().parents[1] / "tau_calibration" / "outputs" / "trivial_plateau_amendment" / "exhaustive_cache"
OUT_DIR = Path(__file__).resolve().parent / "outputs" / "step4"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_cache():
    nrmsd_matrix = np.load(CACHE_DIR / "nrmsd_matrix_n2058_exhaustive.npy")
    min_s_idx = np.load(CACHE_DIR / "min_s_idx_n2058_exhaustive.npy")
    labels = load_cached_labels()
    return nrmsd_matrix, min_s_idx, labels


def k_idx_at_tau(nrmsd_matrix: np.ndarray, tau: float) -> np.ndarray:
    """-1 for outcome 1, else the column index (0-4) of the first stage over tau."""
    over = nrmsd_matrix > tau
    has_any = over.any(axis=1)
    k_col = np.argmax(over, axis=1)  # first True; argmax's own tie-break is "first"
    return np.where(has_any, k_col, -1)


def baseline_b_idx_vectorized(nrmsd_matrix: np.ndarray) -> np.ndarray:
    """Vectorized Baseline B: rise(s) = nrmsd(s) - nrmsd(s-1), nrmsd(0)=0,
    argmax with ties->earliest (numpy's own argmax already picks the first
    occurrence of the max, matching baselines.baseline_b_stage's tie rule).
    """
    zeros = np.zeros((nrmsd_matrix.shape[0], 1))
    padded = np.concatenate([zeros, nrmsd_matrix], axis=1)
    rises = np.diff(padded, axis=1)
    return np.argmax(rises, axis=1)


def step1_write_chains(labels: list[str]) -> list[str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chains = sample_chains(labels, ENSEMBLE_SIZE, SEED)
    (OUT_DIR / "chains.json").write_text(json.dumps({"seed": SEED, "n": ENSEMBLE_SIZE, "chains": chains}, indent=2))
    log(f"Wrote {len(chains)} sampled chains to chains.json (seed={SEED}).")
    return chains


def step2_all_pairs_baseline_check(nrmsd_matrix, min_s_idx) -> dict:
    k_idx = k_idx_at_tau(nrmsd_matrix, TAU)
    outcome1 = k_idx == -1
    outcome1_share = float(outcome1.mean())
    k_eq_mins_share = float(((k_idx == min_s_idx) & (~outcome1)).mean())

    EXPECTED_OUTCOME1 = 0.3027
    EXPECTED_K_EQ_MINS = 0.4583
    exact_match = (
        abs(outcome1_share - EXPECTED_OUTCOME1) < 5e-5
        and abs(k_eq_mins_share - EXPECTED_K_EQ_MINS) < 5e-5
    )
    part_b_share = float(((k_idx > min_s_idx) & (~outcome1)).mean())
    informative_rate = float(outcome1_share + part_b_share)

    b_idx = baseline_b_idx_vectorized(nrmsd_matrix)
    has_k = ~outcome1
    b_agreement = float((b_idx[has_k] == k_idx[has_k]).mean())
    all_three_agree = float((has_k & (b_idx == k_idx) & (k_idx == min_s_idx)).mean())

    ktable = np.zeros((5, 5), dtype=np.int64)
    for ki in range(5):
        for bi in range(5):
            ktable[ki, bi] = int(((k_idx == ki) & (b_idx == bi) & has_k).sum())

    return {
        "tau": TAU,
        "n_pairs": int(nrmsd_matrix.shape[0]),
        "outcome1_share": outcome1_share,
        "k_eq_min_s_share": k_eq_mins_share,
        "expected_outcome1_share": EXPECTED_OUTCOME1,
        "expected_k_eq_min_s_share": EXPECTED_K_EQ_MINS,
        "exact_match_to_stated_figures": exact_match,
        "informative_rate": informative_rate,
        "informative_rate_part_a_outcome1": outcome1_share,
        "informative_rate_part_b_k_gt_mins": part_b_share,
        "baseline_b_agreement_with_k": b_agreement,
        "phase1_a_b_all_agree_share": float(all_three_agree),
        "k_times_b_table": ktable.tolist(),
        "stage_order": [s.name for s in STAGE_ORDER],
    }


def step3_tau_band_curve(nrmsd_matrix, min_s_idx) -> dict:
    outcome1_by_tau = []
    k_eq_mins_by_tau = []
    b_agreement_by_tau = []
    b_idx = baseline_b_idx_vectorized(nrmsd_matrix)
    for tau in TAU_GRID:
        k_idx = k_idx_at_tau(nrmsd_matrix, float(tau))
        outcome1 = k_idx == -1
        outcome1_by_tau.append(float(outcome1.mean()))
        k_eq_mins_by_tau.append(float(((k_idx == min_s_idx) & (~outcome1)).mean()))
        has_k = ~outcome1
        b_agreement_by_tau.append(float((b_idx[has_k] == k_idx[has_k]).mean()) if has_k.any() else None)
    return {
        "tau_grid": TAU_GRID.tolist(),
        "stable_band": list(BAND),
        "outcome1_share_by_tau": outcome1_by_tau,
        "k_eq_min_s_share_by_tau": k_eq_mins_by_tau,
        "baseline_b_agreement_by_tau": b_agreement_by_tau,
    }


def build_pair_to_row(n: int) -> dict[tuple[int, int], int]:
    log(f"Building pair-to-row lookup for n={n} (this takes a few seconds)...")
    return {pair: row for row, pair in enumerate(itertools.combinations(range(n), 2))}


def main() -> None:
    weather_info = verify_thesis_weather_file()
    log(f"Weather file verified: {weather_info}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "weather_file.json").write_text(json.dumps(weather_info, indent=2))
    log("Loading exhaustive cache...")
    nrmsd_matrix, min_s_idx, labels = load_cache()
    label_to_index = {label: i for i, label in enumerate(labels)}

    chains = step1_write_chains(labels)

    log("All-pairs Baseline A/B re-derivation...")
    all_pairs_report = step2_all_pairs_baseline_check(nrmsd_matrix, min_s_idx)
    (OUT_DIR / "all_pairs_baseline_check.json").write_text(json.dumps(all_pairs_report, indent=2))
    log(
        f"outcome1={all_pairs_report['outcome1_share']:.6%} "
        f"k=min(S)={all_pairs_report['k_eq_min_s_share']:.6%} "
        f"exact_match={all_pairs_report['exact_match_to_stated_figures']}"
    )
    if not all_pairs_report["exact_match_to_stated_figures"]:
        log("STOP: all-pairs Baseline A figures do not match the stated 30.27%/45.83%.")
        sys.exit(1)

    log("tau-band curve (whole grid)...")
    band_report = step3_tau_band_curve(nrmsd_matrix, min_s_idx)
    (OUT_DIR / "tau_band_curve.json").write_text(json.dumps(band_report, indent=2))
    log("tau-band curve written.")

    log("Building ensemble physics (100 chains, record=False)...")
    defaults = load_defaults()
    module, mounting = default_hardware()
    all_configs = {c.label: c for c in build_configs(module, mounting)}
    with ChandrupatlaWarningFilter() as wf:
        shared_cec, shared_adr, daylight = _shared()
        results_by_label = {}
        for label in chains:
            config = all_configs[label]
            shared = shared_inputs_for(config, shared_cec, shared_adr)
            results_by_label[label] = run_pipeline(config, shared, defaults)
    if wf.count:
        log(f"({wf.count} known scipy chandrupatla 0/0 warnings suppressed)")
    log(f"Ran {len(results_by_label)} chains' physics.")

    log("Ensemble Phase 1 (production run_phase1), cross-checked against the cache...")
    pair_to_row = build_pair_to_row(len(labels))
    ensemble_pairs = list(itertools.combinations(chains, 2))
    max_relative_diff_overall = 0.0
    ensemble_phase1_records = []
    for label_a, label_b in ensemble_pairs:
        config_a, config_b = all_configs[label_a], all_configs[label_b]
        result_a, result_b = results_by_label[label_a], results_by_label[label_b]
        phase1 = run_phase1(config_a, result_a, config_b, result_b, daylight, defaults=defaults)
        if isinstance(phase1, str):
            ensemble_phase1_records.append({"pair": [label_a, label_b], "not_computable": phase1})
            continue

        i, j = label_to_index[label_a], label_to_index[label_b]
        row = pair_to_row[(min(i, j), max(i, j))]
        cached_profile = nrmsd_matrix[row]
        measured_profile = np.array([phase1.metrics[s].nrmsd for s in STAGE_ORDER])
        denom = np.maximum(np.abs(cached_profile), 1e-12)
        rel_diff = np.max(np.abs(measured_profile - cached_profile) / denom)
        max_relative_diff_overall = max(max_relative_diff_overall, float(rel_diff))
        if rel_diff > 1e-9:
            log(
                f"STOP: pair {label_a}-{label_b} nRMSD profile differs from cache by "
                f"{rel_diff:.3e} relative (stages: "
                f"{dict(zip([s.name for s in STAGE_ORDER], (measured_profile - cached_profile).tolist()))})."
            )
            import subprocess

            since = "28/09"
            try:
                git_log = subprocess.run(
                    ["git", "log", "--oneline", f"--since={since}", "--",
                     "src/pvdials/physics/adapters", "src/pvdials/dla/metrics.py"],
                    capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2],
                ).stdout
            except Exception:
                git_log = "(could not run git log)"
            log(f"Physics-relevant commits since cache was built:\n{git_log}")
            sys.exit(1)

        min_s = baseline_a_stage(_differing_stages_from_configs(config_a, config_b))
        baseline_b = baseline_b_stage({s: phase1.metrics[s].nrmsd for s in STAGE_ORDER})
        part_a, part_b = informative_rate_parts(phase1.outcome, phase1.k, min_s)
        ensemble_phase1_records.append({
            "pair": [label_a, label_b],
            "outcome": phase1.outcome,
            "k": phase1.k.name if phase1.k else None,
            "min_s": min_s.name,
            "baseline_b": baseline_b.name,
            "nrmsd_profile": {s.name: float(phase1.metrics[s].nrmsd) for s in STAGE_ORDER},
            "informative_diff_a_outcome1": part_a,
            "informative_diff_b_k_gt_mins": part_b,
        })

    log(f"Ensemble Phase 1 done. Max relative diff vs cache: {max_relative_diff_overall:.3e} (within 1e-9: {max_relative_diff_overall <= 1e-9}).")
    (OUT_DIR / "ensemble_phase1.json").write_text(json.dumps({
        "max_relative_diff_vs_cache": max_relative_diff_overall,
        "pairs": ensemble_phase1_records,
    }, indent=2))

    log("Ensemble Phase 3 on eligible pairs (record=False)...")
    run_phase3_on_ensemble(all_configs, results_by_label, shared_cec, shared_adr, daylight, defaults, ensemble_phase1_records)

    log("Step 4 complete.")


def _differing_stages_from_configs(config_a, config_b):
    from pvdials.dla.phase1 import _differing_stages
    return _differing_stages(config_a, config_b)


def run_phase3_on_ensemble(
    all_configs, results_by_label, shared_cec, shared_adr, daylight, defaults, phase1_records,
    jsonl_filename="phase3_results.jsonl", summary_filename="phase3_summary.json",
    exclusions_filename="phase3_exclusions.json", save_v_tables: bool = False,
):
    jsonl_path = OUT_DIR / jsonl_filename
    already_done = set()
    if jsonl_path.exists():
        with open(jsonl_path) as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    already_done.add(tuple(rec["pair"]))
        log(f"Resuming: {len(already_done)} pairs already completed.")

    excluded = {"outcome1": 0, "s_lt_2": 0, "pool_invalid": 0}
    eligible_count = 0
    with open(jsonl_path, "a") as out_f:
        for rec in phase1_records:
            if "not_computable" in rec:
                continue
            pair = tuple(rec["pair"])
            if pair in already_done:
                continue
            if rec["outcome"] == 1:
                excluded["outcome1"] += 1
                continue
            label_a, label_b = pair
            config_a, config_b = all_configs[label_a], all_configs[label_b]
            differing = _differing_stages_from_configs(config_a, config_b)
            if len(differing) < 2:
                excluded["s_lt_2"] += 1
                continue
            computable, invalid = pair_is_shapley_computable(config_a, config_b)
            if not computable:
                excluded["pool_invalid"] += 1
                continue

            eligible_count += 1
            result_a, result_b = results_by_label[label_a], results_by_label[label_b]
            result3 = run_phase3(
                config_a, result_a, config_b, result_b,
                shared_cec=shared_cec, shared_adr=shared_adr, daylight=daylight,
                defaults=defaults, record=False,
            )
            if isinstance(result3, (str, Phase3NotComputable)):
                excluded["pool_invalid"] += 1
                continue

            out_rec = _phase3_pair_report(pair, differing, result3, save_v_tables=save_v_tables)
            out_f.write(json.dumps(out_rec) + "\n")
            out_f.flush()
            if eligible_count % 50 == 0:
                log(f"  {eligible_count} eligible pairs processed...")

    log(f"Phase 3 done. Eligible processed this run: {eligible_count}. Excluded: {excluded}")
    (OUT_DIR / exclusions_filename).write_text(json.dumps(excluded, indent=2))
    summarize_phase3(jsonl_path, summary_filename)


def _phase3_pair_report(pair, differing_stages, result3, save_v_tables: bool = False) -> dict:
    stages = tuple(differing_stages)
    w = averaged_game(result3.v_ab, result3.v_ba)
    singleton = {s: w[frozenset({s})] for s in stages}
    full = frozenset(stages)
    loo = {s: w[full] - w[full - {s}] for s in stages}
    phi_final = {s: result3.phi_final[s] for s in stages}

    gap_singleton = attribution_gap(singleton, w[full])
    gap_loo = attribution_gap(loo, w[full])
    rank_singleton = rank_agreement(phi_final, singleton)
    rank_loo = rank_agreement(phi_final, loo)

    record = {
        "pair": list(pair),
        "S": [s.name for s in stages],
        "rmsd_ab": result3.rmsd_ab,
        "phi_final": {s.name: result3.phi_final[s] for s in Stage},
        "phi_ab": {s.name: result3.phi_ab[s] for s in Stage},
        "phi_ba": {s.name: result3.phi_ba[s] for s in Stage},
        "singleton": {s.name: singleton[s] for s in stages},
        "loo": {s.name: loo[s] for s in stages},
        "gap_singleton": gap_singleton,
        "gap_loo": gap_loo,
        "rank_agreement_singleton": rank_singleton,
        "rank_agreement_loo": rank_loo,
        "any_phi_final_below_neg_eps": any(v < -1e-9 for v in result3.phi_final.values()),
    }
    if save_v_tables:
        # Only the S-subset coalitions (2^|S| of them via the canonical
        # S-scoped key, per Step 0's dedup finding -- coalitions differing
        # only outside S give an identical value), minus the 2 trivial ones
        # (empty and full S) -- exactly 2^|S|-2 entries per direction.
        s_frozen = frozenset(stages)
        record["v_ab"] = {
            coalition_key(c): v for c, v in result3.v_ab.items()
            if c.issubset(s_frozen) and c != frozenset() and c != s_frozen
        }
        record["v_ba"] = {
            coalition_key(c): v for c, v in result3.v_ba.items()
            if c.issubset(s_frozen) and c != frozenset() and c != s_frozen
        }
        record["w_full"] = w[full]
    return record


def summarize_phase3(jsonl_path: Path, summary_filename: str = "phase3_summary.json") -> None:
    records = [json.loads(line) for line in open(jsonl_path) if line.strip()]
    if not records:
        log("No eligible Phase 3 records to summarize.")
        return

    s_sizes = [len(r["S"]) for r in records]
    gaps_singleton = [r["gap_singleton"] for r in records if math_isfinite(r["gap_singleton"])]
    gaps_loo = [r["gap_loo"] for r in records if math_isfinite(r["gap_loo"])]

    def pctl(vals, q):
        return float(np.percentile(vals, q)) if vals else None

    rank_s2 = [r for r in records if len(r["S"]) == 2]
    rank_ge3 = [r for r in records if len(r["S"]) >= 3]

    def agreement_stats(subset, key):
        n = len(subset)
        agree = sum(1 for r in subset if r[key] == "agree")
        rate = agree / n if n else None
        interval = wilson_interval(agree, n) if n else (None, None)
        return {"n": n, "agree": agree, "rate": rate, "wilson_95": interval}

    disagreeing = [r for r in records if r["rank_agreement_singleton"] == "disagree"]
    share_negative_phi = sum(1 for r in records if r["any_phi_final_below_neg_eps"]) / len(records)

    summary = {
        "n_eligible": len(records),
        "s_distribution": {str(k): s_sizes.count(k) for k in sorted(set(s_sizes))},
        "gap_singleton": {
            "median": pctl(gaps_singleton, 50), "p10": pctl(gaps_singleton, 10),
            "p90": pctl(gaps_singleton, 90), "max": max(gaps_singleton) if gaps_singleton else None,
        },
        "gap_loo": {
            "median": pctl(gaps_loo, 50), "p10": pctl(gaps_loo, 10),
            "p90": pctl(gaps_loo, 90), "max": max(gaps_loo) if gaps_loo else None,
        },
        "rank_agreement_singleton_overall": agreement_stats(records, "rank_agreement_singleton"),
        "rank_agreement_singleton_s2": agreement_stats(rank_s2, "rank_agreement_singleton"),
        "rank_agreement_singleton_s_ge3": agreement_stats(rank_ge3, "rank_agreement_singleton"),
        "rank_agreement_loo_overall": agreement_stats(records, "rank_agreement_loo"),
        "disagreeing_pairs_singleton": [
            {"pair": r["pair"], "S": r["S"], "phi_final": r["phi_final"], "singleton": r["singleton"]}
            for r in disagreeing
        ],
        "share_pairs_with_any_phi_final_below_neg_eps": share_negative_phi,
    }
    (OUT_DIR / summary_filename).write_text(json.dumps(summary, indent=2))
    log(f"Phase 3 summary written. n_eligible={len(records)}, "
        f"rank_agreement(s2)={agreement_stats(rank_s2, 'rank_agreement_singleton')['rate']}")


def math_isfinite(x) -> bool:
    return x is not None and x == x and abs(x) != float("inf")


if __name__ == "__main__":
    main()
