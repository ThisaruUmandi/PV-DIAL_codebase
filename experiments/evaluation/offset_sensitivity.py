"""Time-offset sensitivity: rerun R5 (worked example) and R3 (100-chain
sample) at the PVGIS header offset (0.5 h) and compare with the reported
0.0 h results.

Reuses the evaluation code unchanged; only the TimeOffset value differs.
In-memory only: Phase 3 runs with record=False, nothing touches the DB.
Sanity check: Phase 1 at 0.0 h must reproduce ensemble_phase1.json exactly.

Writes outputs/offset_sensitivity/: summary.json, phase1_pairs.json (every
R3 pair's Phase 1 result at both offsets) and, unless --phase1-only,
phase3_top_stage.json (top Shapley stage per pair at both offsets).

Run standalone: python3 -m experiments.evaluation.offset_sensitivity [--phase1-only]
"""

from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

from experiments.evaluation.chain_population import build_configs, default_hardware
from experiments.evaluation.comparators import argmax_with_ties
from experiments.evaluation.step0_measure_phase3 import _shared
from experiments.evaluation.step4_ensemble import _differing_stages_from_configs
from experiments.evaluation.weather_source import verify_thesis_weather_file
from pvdials.config import load_defaults
from pvdials.dla.phase1 import run_phase1
from pvdials.dla.phase3 import Phase3NotComputable, run_phase3
from pvdials.physics.pipeline import run_pipeline
from pvdials.physics.shared_inputs import shared_inputs_for
from pvdials.warning_filter import ChandrupatlaWarningFilter

# Always the reported 0 h outputs, whatever PVDIAL_OFFSET_H is set to.
STEP4 = Path(__file__).resolve().parent / "outputs" / "step4"
OUT_DIR = STEP4.parent / "offset_sensitivity"
TAU = 0.093
OFFSETS = (0.0, 0.5)
R5 = {"A": "chain-0005", "B": "chain-0695", "C": "chain-1125"}  # Colombo pipelines A, B, C


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build(offset_h, labels, configs, defaults):
    """step0's own _shared(), at the given offset."""
    shared_cec, shared_adr, daylight = _shared(offset_h)
    results = {
        label: run_pipeline(configs[label], shared_inputs_for(configs[label], shared_cec, shared_adr), defaults)
        for label in labels
    }
    return (shared_cec, shared_adr, daylight), results


def phase1(pair, configs, results, daylight, defaults) -> dict:
    a, b = pair
    r = run_phase1(configs[a], results[a], configs[b], results[b], daylight, tau_value=TAU, defaults=defaults)
    if isinstance(r, str):
        return {"not_computable": r}
    s = _differing_stages_from_configs(configs[a], configs[b])
    return {
        "outcome": r.outcome,
        "k": r.k.name if r.k else None,
        "min_s": min(s).name,
        "nrmsd": {stage.name: m.nrmsd for stage, m in r.metrics.items()},
    }


def category(r: dict) -> str:
    if r["outcome"] == 1:
        return "outcome1"
    return "k_eq_min_s" if r["k"] == r["min_s"] else "k_later"


def top_stage(phi: dict, stages) -> str:
    tied, _ = argmax_with_ties({s: phi[s] for s in stages})
    return tied[0] if len(tied) == 1 else "tie:" + "+".join(sorted(tied))


def phase3_top(pair, configs, results, env, defaults):
    a, b = pair
    shared_cec, shared_adr, daylight = env
    r3 = run_phase3(configs[a], results[a], configs[b], results[b], shared_cec=shared_cec,
                    shared_adr=shared_adr, daylight=daylight, defaults=defaults, record=False)
    if isinstance(r3, (str, Phase3NotComputable)):
        return None
    stages = _differing_stages_from_configs(configs[a], configs[b])
    return top_stage({s.name: r3.phi_final[s] for s in stages}, [s.name for s in stages])


def shares(rows: list[dict]) -> dict:
    n = len(rows)
    counts = collections.Counter(category(r) for r in rows)
    return {c: counts[c] / n for c in ("outcome1", "k_eq_min_s", "k_later")} | {
        "outcome3": sum(r["outcome"] == 3 for r in rows) / n
    }


def main(phase1_only: bool) -> None:
    verify_thesis_weather_file()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    defaults = load_defaults()
    configs = {c.label: c for c in build_configs(*default_hardware())}
    chains = json.loads((STEP4 / "chains.json").read_text())["chains"]
    stored = {tuple(r["pair"]): r for r in json.loads((STEP4 / "ensemble_phase1.json").read_text())["pairs"]}
    stored_p3 = {tuple(r["pair"]): r for r in map(json.loads, open(STEP4 / "phase3_results_v2.jsonl")) if r}
    labels = sorted(set(chains) | set(R5.values()))
    pairs = list(stored)

    with ChandrupatlaWarningFilter():
        env, res, p1 = {}, {}, {}
        for off in OFFSETS:
            env[off], res[off] = build(off, labels, configs, defaults)
            p1[off] = {p: phase1(p, configs, res[off], env[off][2], defaults) for p in pairs}
            log(f"offset {off} h: physics + Phase 1 on {len(pairs)} pairs done")

        mismatch = sum(p1[0.0][p].get("k") != stored[p].get("k") or p1[0.0][p].get("outcome") != stored[p].get("outcome")
                       for p in pairs)
        log(f"sanity: 0.0 h Phase 1 vs stored ensemble_phase1.json mismatches = {mismatch}")
        assert mismatch == 0, "0.0 h rerun does not reproduce the stored R3 Phase 1 -- stopping"

        r5 = {}
        for x, y in (("A", "B"), ("A", "C"), ("B", "C")):
            pair = (R5[x], R5[y])
            row = {}
            for off in OFFSETS:
                q = phase1(pair, configs, res[off], env[off][2], defaults)
                q["top_shapley"] = phase3_top(pair, configs, res[off], env[off], defaults) if q["outcome"] != 1 else None
                row[str(off)] = q
            r5[f"{x}-{y}"] = row
            log(f"R5 {x}-{y}: k {row['0.0']['k']} -> {row['0.5']['k']}, "
                f"top Shapley {row['0.0']['top_shapley']} -> {row['0.5']['top_shapley']}")

        valid = [p for p in pairs if all("not_computable" not in p1[off][p] for off in OFFSETS)]
        sh = {str(off): shares([p1[off][p] for p in valid]) for off in OFFSETS}
        transitions = collections.Counter(f"{category(p1[0.0][p])} -> {category(p1[0.5][p])}" for p in valid)
        k_transitions = collections.Counter(f"{p1[0.0][p]['k']} -> {p1[0.5][p]['k']}"
                                            for p in valid if p1[0.0][p]["k"] != p1[0.5][p]["k"])
        (OUT_DIR / "phase1_pairs.json").write_text(json.dumps(
            [{"pair": list(p), **{str(off): p1[off][p] for off in OFFSETS}} for p in pairs]))

        summary = {
            "tau": TAU,
            "r5": r5,
            "r3_phase1": {
                "pairs": len(valid),
                "k_changed": sum(p1[0.0][p]["k"] != p1[0.5][p]["k"] for p in valid),
                "shares": sh,
                "max_share_change_pp": max(abs(sh["0.5"][c] - sh["0.0"][c]) * 100 for c in sh["0.0"]),
                "category_transitions": dict(transitions.most_common()),
                "k_transitions": dict(k_transitions.most_common()),
            },
        }

        if not phase1_only:
            eligible = [p for p in stored_p3 if p1[0.5][p]["outcome"] != 1]
            log(f"Phase 3 at 0.5 h on {len(eligible)} of {len(stored_p3)} pairs ...")
            rows, t0 = [], time.time()
            for i, p in enumerate(eligible, 1):
                new = phase3_top(p, configs, res[0.5], env[0.5], defaults)
                if new is not None:
                    rows.append({"pair": list(p), "top_0.0": top_stage(stored_p3[p]["phi_final"], stored_p3[p]["S"]),
                                 "top_0.5": new})
                if i % 100 == 0:
                    log(f"  {i}/{len(eligible)}  ({(time.time() - t0) / 60:.1f} min)")
            changed = [r for r in rows if r["top_0.0"] != r["top_0.5"]]
            (OUT_DIR / "phase3_top_stage.json").write_text(json.dumps(rows))
            summary["r3_phase3"] = {
                "stored_pairs": len(stored_p3), "eligible_at_0.5": len(eligible), "compared": len(rows),
                "top_changed": len(changed),
                "top_transitions": dict(collections.Counter(f"{r['top_0.0']} -> {r['top_0.5']}" for r in changed).most_common()),
            }

    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=1))
    log(json.dumps({k: v for k, v in summary.items() if k != "r5"}, indent=1))


if __name__ == "__main__":
    main(phase1_only="--phase1-only" in sys.argv)
