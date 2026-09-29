"""Evaluation KT Step 6: the evaluation table, filled. Reads only saved
outputs from Steps 2-5 -- never the database. Every number, with the fixed
values and seeds echoed; the section-1 table's numbers placed next to each
"what failure looks like" condition. No verdict written -- that's Umee's.

Run standalone: python3 -m experiments.evaluation.step6_fill_table
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.evaluation.wording import check_banned_words

BASE = Path(__file__).resolve().parent / "outputs"
OUT_DIR = BASE
FIGURES_DIR = BASE / "figures"

SEED_ENSEMBLE = 20260929
SEED_REPLAY_SAMPLE = 20260929
TAU_DEFAULT = 0.093
STABLE_BAND = (0.088, 0.098)
EFFICIENCY_EPS = 1e-9
PROVENANCE_TOLERANCE = 1e-9


def _load(path: Path):
    return json.loads(path.read_text())


def main() -> None:
    step2_colombo = _load(BASE / "step2" / "colombo_check.json")
    step2_pair = _load(BASE / "step2" / "two_stage_pair_v_tables.json")
    step3 = _load(BASE / "step3" / "perturbation_cases.json")
    step4_all_pairs = _load(BASE / "step4" / "all_pairs_baseline_check.json")
    step4_ensemble_phase1 = _load(BASE / "step4" / "ensemble_phase1.json")
    step4_phase3_summary = _load(BASE / "step4" / "phase3_summary.json")
    step4_phase3_exclusions = _load(BASE / "step4" / "phase3_exclusions.json")
    step4_chains = _load(BASE / "step4" / "chains.json")
    step5 = _load(BASE / "step5" / "replay_results.json")

    # Ensemble-level informative rate / Baseline B agreement (computed from
    # ensemble_phase1.json's per-pair records -- not aggregated at Step 4
    # build time, done here as pure read-only post-processing).
    pairs = [p for p in step4_ensemble_phase1["pairs"] if "not_computable" not in p]
    n = len(pairs)
    part_a = sum(1 for p in pairs if p["informative_diff_a_outcome1"])
    part_b = sum(1 for p in pairs if p["informative_diff_b_k_gt_mins"])
    has_k = [p for p in pairs if p["k"] is not None]
    b_agree = sum(1 for p in has_k if p["baseline_b"] == p["k"])
    ensemble_informative = {
        "n": n, "part_a_outcome1": part_a / n, "part_b_k_gt_mins": part_b / n,
        "informative_rate": (part_a + part_b) / n,
        "baseline_b_agreement_with_k": b_agree / len(has_k) if has_k else None,
    }

    evaluation_results = {
        "fixed_values": {
            "default_tau": TAU_DEFAULT,
            "stable_tau_band": list(STABLE_BAND),
            "ensemble_seed": SEED_ENSEMBLE,
            "replay_sample_seed": SEED_REPLAY_SAMPLE,
            "efficiency_tolerance_eps": EFFICIENCY_EPS,
            "provenance_tolerance": PROVENANCE_TOLERANCE,
        },
        "step2_colombo_worked_examples": step2_colombo,
        "step2_two_stage_pair": step2_pair,
        "step3_perturbation_cases": step3,
        "step4_all_pairs_baseline": step4_all_pairs,
        "step4_ensemble_informative_rate": ensemble_informative,
        "step4_ensemble_chains": {"seed": step4_chains["seed"], "n": step4_chains["n"]},
        "step4_phase3_summary": step4_phase3_summary,
        "step4_phase3_exclusions": step4_phase3_exclusions,
        "step5_provenance_roundtrip": {
            "n_records": step5["n_records"], "n_passed": step5["n_passed"],
            "all_passed": step5["all_passed"], "seed": step5["seed"],
        },
    }

    (OUT_DIR / "evaluation_results.json").write_text(json.dumps(evaluation_results, indent=2))

    md = _build_markdown(
        step4_all_pairs, ensemble_informative, step4_phase3_summary,
        step4_phase3_exclusions, step5,
    )
    hits = check_banned_words(md)
    if hits:
        raise RuntimeError(f"Banned words found in evaluation_table.md:\n" + "\n".join(hits))
    (OUT_DIR / "evaluation_table.md").write_text(md)

    print("Step 6 done. evaluation_results.json and evaluation_table.md written.")
    print(f"Banned-word scan: clean ({len(hits)} hits).")


def _build_markdown(all_pairs, ensemble_informative, phase3_summary, exclusions, step5) -> str:
    return f"""# Evaluation table (filled)

| Claim | Comparator | Metric | Data | What failure looks like |
|---|---|---|---|---|
| Phase 1: WHERE disagreement first becomes material | Baseline A: min(S) | Informative rate: {ensemble_informative['informative_rate']:.4f} (ensemble), {all_pairs['informative_rate']:.4f} (all pairs) -- part (a) outcome 1: {ensemble_informative['part_a_outcome1']:.4f} / {all_pairs['informative_rate_part_a_outcome1']:.4f}; part (b) k>min(S): {ensemble_informative['part_b_k_gt_mins']:.4f} / {all_pairs['informative_rate_part_b_k_gt_mins']:.4f} | Ensemble (100 chains, seed {SEED_ENSEMBLE}) and all 2,116,653 pairs | At the default tau, Phase 1 agrees with Baseline A on nearly every pair (informative rate near 0) |
| Phase 1: second check | Baseline B: largest single-step nRMSD rise | Agreement with k: {ensemble_informative['baseline_b_agreement_with_k']:.4f} (ensemble), {all_pairs['baseline_b_agreement_with_k']:.4f} (all pairs) | Same runs | If A, B and Phase 1 always agree, tau is doing no work |
| Phase 3: HOW MUCH each stage contributed | OAT: singleton and leave-one-out readings | Attribution gap (singleton) median {phase3_summary['gap_singleton']['median']:.4f}, P10 {phase3_summary['gap_singleton']['p10']:.4f}, P90 {phase3_summary['gap_singleton']['p90']:.4f}, max {phase3_summary['gap_singleton']['max']:.4f}. Rank agreement (singleton): {phase3_summary['rank_agreement_singleton_overall']['rate']:.4f} overall (Wilson 95% {phase3_summary['rank_agreement_singleton_overall']['wilson_95']}), \\|S\\|=2: {phase3_summary['rank_agreement_singleton_s2']['rate']:.4f}, \\|S\\|>=3: {phase3_summary['rank_agreement_singleton_s_ge3']['rate']:.4f} | {phase3_summary['n_eligible']} eligible ensemble pairs (excluded: {exclusions}) | Gap near zero and ranks always agree would mean Shapley adds cost without changing the answer at this site |
| Provenance (O2) | Not comparative: verification | {step5['n_passed']}/{step5['n_records']} sampled records ({step5['seed']}) replayed bitwise-identical, all_passed={step5['all_passed']} | 3 original + 10 derived + 2 reexec | Any stage output that cannot be reproduced from the record |

Descriptive, not in the section-1 table: share of eligible pairs with any phi_final below -epsilon: {phase3_summary['share_pairs_with_any_phi_final_below_neg_eps']:.4f}.
"""


if __name__ == "__main__":
    main()
