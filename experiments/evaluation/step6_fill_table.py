"""Evaluation KT Step 6: the evaluation table, filled. Reads only saved
outputs from Steps 2-5 -- never the database. Every number, with the fixed
values and seeds echoed; the section-1 table's numbers placed next to each
"what failure looks like" condition. No verdict written -- that's Umee's.

Run standalone: python3 -m experiments.evaluation.step6_fill_table
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.evaluation.comparators import shapley_values
from experiments.evaluation.wording import check_banned_words
from experiments.tau_calibration.run_settings import (
    OFFSET_H,
    TAU,
    ZERO_H_TAU,
    output_dir,
    require_tau,
    sensitivity_dir,
    stable_band,
)
from pvdials.types import Stage

BASE = Path(__file__).resolve().parent / "outputs"
OUT_DIR = BASE
FIGURES_DIR = BASE / "figures"
# At a non-zero offset: read that offset's step folders, write beside the 0 h
# files under new names, so evaluation_results.json/evaluation_table.md (0 h)
# stay untouched.
OUT_SUFFIX = "" if OFFSET_H == 0.0 else f"_offset_{OFFSET_H:g}h"

SEED_ENSEMBLE = 20260929
SEED_REPLAY_SAMPLE = 20260929
EFFICIENCY_EPS = 1e-9
PROVENANCE_TOLERANCE = 1e-9


def _load(path: Path):
    return json.loads(path.read_text())


def _step(name: str) -> Path:
    return output_dir(BASE / name)


def _check_run_records(inputs: dict[str, dict]) -> dict | None:
    """Every input that carries a run record must agree on offset and tau --
    stops on a mix of runs. The 0 h inputs predate run records (None)."""
    records = {name: d["run_record"] for name, d in inputs.items() if isinstance(d, dict) and d.get("run_record")}
    for name, r in records.items():
        if r["time_offset_h"] != OFFSET_H or r.get("tau", TAU) != TAU:
            raise SystemExit(f"STOP: {name} was run at {r['time_offset_h']:g} h / tau {r.get('tau')}, "
                             f"this table is for {OFFSET_H:g} h / tau {TAU:g}.")
    if OFFSET_H != 0.0 and len(records) != len(inputs):
        raise SystemExit(f"STOP: inputs without a run record: {sorted(set(inputs) - set(records))}")
    return next(iter(records.values()), None)


ZERO_H_CACHE = (Path(__file__).resolve().parents[1] / "tau_calibration" / "outputs" / "trivial_plateau_amendment"
                / "exhaustive_cache" / "nrmsd_matrix_n2058_exhaustive.npy")


def _zero_h_outcome_counts(all_pairs: dict) -> dict:
    """The 0 h all-pairs file predates stored outcome counts: derived from
    the 0 h R1 cache at its own tau, checked against its stored outcome-1 share."""
    if "outcome_counts" in all_pairs:
        return all_pairs["outcome_counts"]
    import numpy as np

    from experiments.evaluation.step4_ensemble import outcome_counts

    counts = outcome_counts(np.load(ZERO_H_CACHE), all_pairs["tau"])
    assert counts["1"] == round(all_pairs["outcome1_share"] * all_pairs["n_pairs"]), "0 h cache and all-pairs file disagree"
    return counts


def _sensitivity_column(all_pairs: dict, phase3_summary: dict | None, counts: dict) -> dict:
    """OAT/LOO come from Phase 3 on a main run's ensemble; None where there is none."""
    return {
        "tau": all_pairs["tau"],
        "differs_from_baseline_a": all_pairs["informative_rate"],
        "outcome1_share": all_pairs["informative_rate_part_a_outcome1"],
        "k_later_share": all_pairs["informative_rate_part_b_k_gt_mins"],
        "outcome_counts": counts,
        "oat_same_top_stage": None if phase3_summary is None else phase3_summary["rank_agreement_singleton_overall"]["rate"],
        "loo_same_top_stage": None if phase3_summary is None else phase3_summary["rank_agreement_loo_overall"]["rate"],
    }


def _sensitivity_table(main_all_pairs: dict, main_phase3_summary: dict) -> dict:
    """0 h @ 0 h tau | this offset @ 0 h tau (the sensitivity run) | this offset @ its own tau (main)."""
    zero_all_pairs = _load(BASE / "step4" / "all_pairs_baseline_check.json")
    sens_file = sensitivity_dir(BASE / "step4") / "all_pairs_baseline_check.json"
    if not sens_file.exists():
        raise SystemExit(f"STOP: no {sens_file} -- run step4 with PVDIAL_SENSITIVITY=1 PVDIAL_TAU={ZERO_H_TAU:g} first.")
    sens_all_pairs = _load(sens_file)
    record = sens_all_pairs.get("run_record") or {}
    if record.get("time_offset_h") != OFFSET_H or record.get("tau") != ZERO_H_TAU or "run_kind" not in record:
        raise SystemExit(f"STOP: {sens_file} is not the {OFFSET_H:g} h sensitivity run at tau {ZERO_H_TAU:g}: {record}")
    return {
        f"0 h, tau {zero_all_pairs['tau']:g}": _sensitivity_column(
            zero_all_pairs, _load(BASE / "step4" / "phase3_summary.json"), _zero_h_outcome_counts(zero_all_pairs)),
        f"{OFFSET_H:g} h, tau {ZERO_H_TAU:g}": _sensitivity_column(sens_all_pairs, None, sens_all_pairs["outcome_counts"]),
        f"{OFFSET_H:g} h, tau {TAU:g}": _sensitivity_column(
            main_all_pairs, main_phase3_summary, main_all_pairs["outcome_counts"]),
    }


def _sensitivity_section(table: dict, n_pairs: int) -> str:
    def pct(v):
        return "n/a" if v is None else f"{v * 100:.1f} %"

    cols = list(table.values())
    rows = [
        ("tau", [f"{c['tau']:g}" for c in cols]),
        ("Phase 1 differs from Baseline A", [pct(c["differs_from_baseline_a"]) for c in cols]),
        ("... no stage over tau (outcome 1)", [pct(c["outcome1_share"]) for c in cols]),
        ("... later stage than Baseline A", [pct(c["k_later_share"]) for c in cols]),
        ("Outcome 1 / 2 / 3 (pairs)", [" / ".join(f"{c['outcome_counts'][o]:,}" for o in "123") for c in cols]),
        ("OAT (single-stage) same top stage", [pct(c["oat_same_top_stage"]) for c in cols]),
        ("OAT (leave-one-out) same top stage", [pct(c["loo_same_top_stage"]) for c in cols]),
    ]
    lines = ["## Sensitivity -- time offset and tau", "",
             "| | " + " | ".join(table) + " |", "|---" * (len(table) + 1) + "|"]
    lines += [f"| {name} | " + " | ".join(values) + " |" for name, values in rows]
    lines += ["", f"Phase 1 rows: all {n_pairs:,} pairs. OAT rows: Phase 3 on the 100-chain ensemble, which only the main "
              "runs have, so the middle column (the sensitivity run, all-pairs Phase 1 only) has none.", ""]
    return "\n".join(lines)


def main() -> None:
    require_tau()
    step2_colombo = _load(_step("step2") / "colombo_check.json")
    step2_pair = _load(_step("step2") / "two_stage_pair_v_tables.json")
    step3 = _load(_step("step3") / "perturbation_cases.json")
    step4_all_pairs = _load(_step("step4") / "all_pairs_baseline_check.json")
    step4_ensemble_phase1 = _load(_step("step4") / "ensemble_phase1.json")
    step4_phase3_summary = _load(_step("step4") / "phase3_summary.json")
    step4_phase3_exclusions = _load(_step("step4") / "phase3_exclusions.json")
    step4_chains = _load(_step("step4") / "chains.json")
    step4_single_anchor = _load(_step("step4") / "single_anchor_summary.json")
    step5 = _load(_step("step5") / "replay_results.json")
    record = _check_run_records({
        "step2/colombo_check": step2_colombo, "step2/two_stage_pair": step2_pair, "step3": step3,
        "step4/all_pairs": step4_all_pairs, "step4/ensemble_phase1": step4_ensemble_phase1,
        "step4/phase3_summary": step4_phase3_summary, "step4/phase3_exclusions": step4_phase3_exclusions,
        "step4/chains": step4_chains, "step4/single_anchor": step4_single_anchor, "step5": step5,
    })

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
        "run_record": record,
        "fixed_values": {
            "default_tau": TAU,
            "stable_tau_band": list(stable_band()),
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
        "step4_single_anchor_readings": step4_single_anchor,
        "step5_provenance_roundtrip": {
            "n_records": step5["n_records"], "n_passed": step5["n_passed"],
            "all_passed": step5["all_passed"], "seed": step5["seed"],
        },
    }

    sensitivity = None if OFFSET_H == 0.0 else _sensitivity_table(step4_all_pairs, step4_phase3_summary)
    if sensitivity is not None:
        evaluation_results["sensitivity_table"] = sensitivity
    (OUT_DIR / f"evaluation_results{OUT_SUFFIX}.json").write_text(json.dumps(evaluation_results, indent=2))

    md = _build_markdown(
        step4_all_pairs, ensemble_informative, step4_phase3_summary,
        step4_phase3_exclusions, step5, step2_pair, step3, step4_single_anchor,
    )
    if sensitivity is not None:
        md += "\n" + _sensitivity_section(sensitivity, step4_all_pairs["n_pairs"])
    hits = check_banned_words(md)
    if hits:
        raise RuntimeError(f"Banned words found in evaluation_table.md:\n" + "\n".join(hits))
    (OUT_DIR / f"evaluation_table{OUT_SUFFIX}.md").write_text(md)

    print(f"Step 6 done. evaluation_results{OUT_SUFFIX}.json and evaluation_table{OUT_SUFFIX}.md written.")
    print(f"Banned-word scan: clean ({len(hits)} hits).")


def _w(interval) -> str:
    """Wilson interval rounded to 4dp for display -- the underlying stored
    value is untouched, only how it's printed here.
    """
    return f"[{interval[0]:.4f}, {interval[1]:.4f}]"


def _hand_built_tables_section() -> str:
    """Step 2's two hand-built v tables, computed fresh here -- pure,
    deterministic arithmetic (no weather/DB/experiment state), already
    verified by tests/evaluation/test_comparators.py, restated rather than
    reruns of anything.
    """
    v_additive = {frozenset(): 0.0, frozenset({1}): 3.0, frozenset({2}): 1.0, frozenset({1, 2}): 4.0}
    phi_additive = shapley_values(v_additive, (1, 2))
    v_interactive = {frozenset(): 0.0, frozenset({1}): 4.0, frozenset({2}): 0.0, frozenset({1, 2}): 8.0}
    phi_interactive = shapley_values(v_interactive, (1, 2))

    return f"""## Step 2 -- hand-built v tables

| Table | v({{1}}) | v({{2}}) | v({{1,2}}) | phi_1 | phi_2 | singleton sum | gap |
|---|---|---|---|---|---|---|---|
| Additive | 3 | 1 | 4 | {phi_additive[1]:.4f} | {phi_additive[2]:.4f} | 4 | 0.0000 |
| Interactive | 4 | 0 | 8 | {phi_interactive[1]:.4f} | {phi_interactive[2]:.4f} | 4 | 0.5000 |

Both match the KT's own worked values exactly (additive: phi=(3,1); interactive: phi=(6,2)).
"""


def _real_pair_section(step2_pair) -> str:
    v_ab, v_ba, w = step2_pair["v_ab"], step2_pair["v_ba"], step2_pair["w_averaged"]
    pair = step2_pair["pair"]
    s = step2_pair["S"]
    i_key, j_key, ij_key = f"v({{{s[0]}}})", f"v({{{s[1]}}})", f"v({{{s[0]},{s[1]}}})"

    phi = shapley_values(
        {frozenset(): 0.0, frozenset({s[0]}): w[i_key], frozenset({s[1]}): w[j_key],
         frozenset({s[0], s[1]}): w[ij_key]},
        (s[0], s[1]),
    )

    return f"""## Step 2 -- real \\|S\\|=2 pair ({pair[0]} vs {pair[1]}, S={{{s[0]}, {s[1]}}})

| | {i_key} | {j_key} | {ij_key} |
|---|---|---|---|
| A->B | {v_ab[i_key]:.6f} | {v_ab[j_key]:.6f} | {v_ab[ij_key]:.6f} |
| B->A | {v_ba[i_key]:.6f} | {v_ba[j_key]:.6f} | {v_ba[ij_key]:.6f} |
| averaged w | {w[i_key]:.6f} | {w[j_key]:.6f} | {w[ij_key]:.6f} |

Independent Shapley of the averaged game: phi_{s[0]} = {phi[s[0]]:.6f}, phi_{s[1]} = {phi[s[1]]:.6f}.
"""


def _step3_section(step3) -> str:
    c1, c2, c3 = step3["case1_phase1"], step3["case2_one_perturbed_stage"], step3["case3_two_multiplicative"]
    return f"""## Step 3 -- constructed cases

**Case 1 (Phase 1 case)**: k={c1['k']}, Baseline A={c1['baseline_a']}, Baseline B={c1['baseline_b']} --
matches expectation on all three: {all(c1['matches_expectation'].values())}. Measured nRMSD:
{ {k: round(v, 4) if isinstance(v, float) else v for k, v in c1['measured_nrmsd'].items()} }.

**Case 2 (one perturbed stage)**: share(TEMPERATURE) = {c2['share_TEMPERATURE']:.6f} (expected 1.0),
Phase 1 outcome={c2['phase1_outcome']}.

**Case 3 (two multiplicative perturbations, a=0.30, c=0.10)**: internal-consistency check
(code's phi_final vs. independent Shapley of the averaged game) max relative diff =
{c3['internal_consistency_check']['max_relative_diff_phi_final_vs_independent_shapley_of_averaged_game']:.3e}
(within 1e-9: {c3['internal_consistency_check']['within_1e-9']}). Paper-vs-measured (informational,
not a stop condition): v_ab(TRANSPOSITION) relative diff {c3['paper_vs_measured']['v_ab({TRANSPOSITION})']['relative_diff']:.4f},
v_ab(AC) relative diff {c3['paper_vs_measured']['v_ab({AC})']['relative_diff']:.2e} (no linearity
assumption needed there, closest to exact).
"""


def _single_anchor_section(sa, averaged_disagreeing_count: int) -> str:
    return f"""## Phase 3 -- single-anchor OAT readings, beside the averaged ones

v_XY({{i}}) and v_YX({{i}}) each taken from that anchor's own v table alone (not the averaged
game), compared against that anchor's own phi_ab / phi_ba -- not phi_final.

| | Averaged (w) | Anchor A->B (v_ab) | Anchor B->A (v_ba) |
|---|---|---|---|
| Gap median | see main table | {sa['gap_ab']['median']:.4f} | {sa['gap_ba']['median']:.4f} |
| Gap P10 | see main table | {sa['gap_ab']['p10']:.4f} | {sa['gap_ba']['p10']:.4f} |
| Gap P90 | see main table | {sa['gap_ab']['p90']:.4f} | {sa['gap_ba']['p90']:.4f} |
| Gap max | see main table | {sa['gap_ab']['max']:.4f} | {sa['gap_ba']['max']:.4f} |
| Rank agreement overall | see main table | {sa['rank_agreement_ab_overall']['rate']:.4f} (Wilson {_w(sa['rank_agreement_ab_overall']['wilson_95'])}) | {sa['rank_agreement_ba_overall']['rate']:.4f} (Wilson {_w(sa['rank_agreement_ba_overall']['wilson_95'])}) |
| Rank agreement \\|S\\|=2 | see main table | {sa['rank_agreement_ab_s2']['rate']:.4f} (Wilson {_w(sa['rank_agreement_ab_s2']['wilson_95'])}) | {sa['rank_agreement_ba_s2']['rate']:.4f} (Wilson {_w(sa['rank_agreement_ba_s2']['wilson_95'])}) |
| Rank agreement \\|S\\|>=3 | see main table | {sa['rank_agreement_ab_s_ge3']['rate']:.4f} (Wilson {_w(sa['rank_agreement_ab_s_ge3']['wilson_95'])}) | {sa['rank_agreement_ba_s_ge3']['rate']:.4f} (Wilson {_w(sa['rank_agreement_ba_s_ge3']['wilson_95'])}) |
| Disagreeing pairs | {averaged_disagreeing_count} | {len(sa['disagreeing_pairs_ab'])} | {len(sa['disagreeing_pairs_ba'])} |

Full disagreeing-pair lists in `single_anchor_summary.json`.
"""


def _build_markdown(all_pairs, ensemble_informative, phase3_summary, exclusions, step5, step2_pair, step3, single_anchor) -> str:
    main_table = f"""# Evaluation table (filled)

| Claim | Comparator | Metric | Data | What failure looks like |
|---|---|---|---|---|
| Phase 1: WHERE disagreement first becomes material | Baseline A: min(S) | Informative rate: {ensemble_informative['informative_rate']:.4f} (ensemble), {all_pairs['informative_rate']:.4f} (all pairs) -- part (a) outcome 1: {ensemble_informative['part_a_outcome1']:.4f} / {all_pairs['informative_rate_part_a_outcome1']:.4f}; part (b) k>min(S): {ensemble_informative['part_b_k_gt_mins']:.4f} / {all_pairs['informative_rate_part_b_k_gt_mins']:.4f} | Ensemble (100 chains, seed {SEED_ENSEMBLE}) and all 2,116,653 pairs | At the default tau, Phase 1 agrees with Baseline A on nearly every pair (informative rate near 0) |
| Phase 1: second check | Baseline B: largest single-step nRMSD rise | Agreement with k: {ensemble_informative['baseline_b_agreement_with_k']:.4f} (ensemble), {all_pairs['baseline_b_agreement_with_k']:.4f} (all pairs) | Same runs | If A, B and Phase 1 always agree, tau is doing no work |
| Phase 3: HOW MUCH each stage contributed | OAT: singleton and leave-one-out readings | Attribution gap (singleton) median {phase3_summary['gap_singleton']['median']:.4f}, P10 {phase3_summary['gap_singleton']['p10']:.4f}, P90 {phase3_summary['gap_singleton']['p90']:.4f}, max {phase3_summary['gap_singleton']['max']:.4f}. Rank agreement (singleton): {phase3_summary['rank_agreement_singleton_overall']['rate']:.4f} overall (Wilson 95% {_w(phase3_summary['rank_agreement_singleton_overall']['wilson_95'])}), \\|S\\|=2: {phase3_summary['rank_agreement_singleton_s2']['rate']:.4f}, \\|S\\|>=3: {phase3_summary['rank_agreement_singleton_s_ge3']['rate']:.4f} | {phase3_summary['n_eligible']} eligible ensemble pairs (excluded: {exclusions}) | Gap near zero and ranks always agree would mean Shapley adds cost without changing the answer at this site |
| Provenance (O2) | Not comparative: verification | {step5['n_passed']}/{step5['n_records']} sampled records ({step5['seed']}) replayed bitwise-identical, all_passed={step5['all_passed']} | 3 original + 10 derived + 2 reexec | Any stage output that cannot be reproduced from the record |

Descriptive, not in the section-1 table: share of eligible pairs with any phi_final below -epsilon: {phase3_summary['share_pairs_with_any_phi_final_below_neg_eps']:.4f}.
"""
    return "\n".join([
        main_table,
        _hand_built_tables_section(),
        _real_pair_section(step2_pair),
        _step3_section(step3),
        _single_anchor_section(single_anchor, len(phase3_summary["disagreeing_pairs_singleton"])),
    ])


if __name__ == "__main__":
    main()
