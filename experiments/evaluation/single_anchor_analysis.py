"""Single-anchor OAT readings (v_XY({i}), v_YX({i})), beside the averaged
ones already in phase3_summary.json: attribution gap and rank agreement
computed from each anchor's own v table and its own phi_ab/phi_ba, not the
averaged w/phi_final -- reads only phase3_results_v2.jsonl.

Run standalone: python3 -m experiments.evaluation.single_anchor_analysis
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.evaluation.comparators import attribution_gap, rank_agreement, wilson_interval

BASE = Path(__file__).resolve().parent / "outputs" / "step4"


def _finite(x) -> bool:
    return x is not None and x == x and abs(x) != float("inf")


def main() -> None:
    records = [json.loads(l) for l in open(BASE / "phase3_results_v2.jsonl") if l.strip()]
    print(f"{len(records)} eligible pairs loaded.")

    per_pair = []
    for r in records:
        stages = r["S"]
        singleton_ab = {s: r["v_ab"][s] for s in stages}
        singleton_ba = {s: r["v_ba"][s] for s in stages}
        full = r["w_full"]  # == v_ab(S) == v_ba(S) == rmsd_ab, confirmed identical by construction
        phi_ab = {s: r["phi_ab"][s] for s in stages}
        phi_ba = {s: r["phi_ba"][s] for s in stages}

        gap_ab = attribution_gap(singleton_ab, full)
        gap_ba = attribution_gap(singleton_ba, full)
        rank_ab = rank_agreement(phi_ab, singleton_ab)
        rank_ba = rank_agreement(phi_ba, singleton_ba)

        per_pair.append({
            "pair": r["pair"], "S": stages,
            "singleton_ab": singleton_ab, "singleton_ba": singleton_ba,
            "gap_ab": gap_ab, "gap_ba": gap_ba,
            "rank_agreement_ab": rank_ab, "rank_agreement_ba": rank_ba,
        })

    def pctl(vals, q):
        return float(np.percentile(vals, q)) if vals else None

    def gap_stats(key):
        vals = [p[key] for p in per_pair if _finite(p[key])]
        return {"median": pctl(vals, 50), "p10": pctl(vals, 10), "p90": pctl(vals, 90),
                "max": max(vals) if vals else None}

    def agreement_stats(subset, key):
        n = len(subset)
        agree = sum(1 for p in subset if p[key] == "agree")
        rate = agree / n if n else None
        return {"n": n, "agree": agree, "rate": rate, "wilson_95": wilson_interval(agree, n) if n else (None, None)}

    s2 = [p for p in per_pair if len(p["S"]) == 2]
    ge3 = [p for p in per_pair if len(p["S"]) >= 3]

    disagreeing_ab = [p for p in per_pair if p["rank_agreement_ab"] == "disagree"]
    disagreeing_ba = [p for p in per_pair if p["rank_agreement_ba"] == "disagree"]

    summary = {
        "n_eligible": len(per_pair),
        "gap_ab": gap_stats("gap_ab"),
        "gap_ba": gap_stats("gap_ba"),
        "rank_agreement_ab_overall": agreement_stats(per_pair, "rank_agreement_ab"),
        "rank_agreement_ab_s2": agreement_stats(s2, "rank_agreement_ab"),
        "rank_agreement_ab_s_ge3": agreement_stats(ge3, "rank_agreement_ab"),
        "rank_agreement_ba_overall": agreement_stats(per_pair, "rank_agreement_ba"),
        "rank_agreement_ba_s2": agreement_stats(s2, "rank_agreement_ba"),
        "rank_agreement_ba_s_ge3": agreement_stats(ge3, "rank_agreement_ba"),
        "disagreeing_pairs_ab": [
            {"pair": p["pair"], "S": p["S"], "phi_ab": r["phi_ab"], "singleton_ab": p["singleton_ab"]}
            for p, r in zip(per_pair, records) if p["rank_agreement_ab"] == "disagree"
        ],
        "disagreeing_pairs_ba": [
            {"pair": p["pair"], "S": p["S"], "phi_ba": r["phi_ba"], "singleton_ba": p["singleton_ba"]}
            for p, r in zip(per_pair, records) if p["rank_agreement_ba"] == "disagree"
        ],
    }
    (BASE / "single_anchor_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"gap_ab: {summary['gap_ab']}")
    print(f"gap_ba: {summary['gap_ba']}")
    print(f"rank_agreement_ab overall: {summary['rank_agreement_ab_overall']}")
    print(f"rank_agreement_ba overall: {summary['rank_agreement_ba_overall']}")
    print(f"disagreeing (ab): {len(disagreeing_ab)}, disagreeing (ba): {len(disagreeing_ba)}")
    print("Wrote single_anchor_summary.json")


if __name__ == "__main__":
    main()
