"""CLI: python -m pvdials <command>.

Prints the readable summary; all computation lives in analysis.py (pure
functions, reused by Streamlit later) -- this module's only job is argument
parsing, printing, and calling those functions.
"""

from __future__ import annotations

import argparse
import sys

from pvdials.analysis import (
    ALL_STAGES,
    AnalysisError,
    Phase3NotComputable,
    failed_check_names,
    run_analysis,
    write_outputs,
)
from pvdials.dla.phase1 import OUTCOME_COMPENSATING_DIFFERENCES, OUTCOME_DISAGREEMENT_FOUND
from pvdials.provenance.analyses import list_analyses
from pvdials.provenance.db import get_connection, is_reachable, run_schema

_OUTCOME_TEXT = {
    1: "nothing to diagnose (no stage exceeds tau)",
    OUTCOME_DISAGREEMENT_FOUND: "disagreement found",
    OUTCOME_COMPENSATING_DIFFERENCES: "upstream disagreement with final-output agreement (compensating differences)",
}


def _print_summary(run) -> None:
    print(f"\nAnalysis: {run.name}  (id={run.analysis_id})")

    print("\n=== Validation ===")
    v = run.load_result.validation
    print(f"  Tier 1-3: passed={v.passed}  problems={v.problems}  warnings={v.warnings}")
    t4 = run.site_result.tier4
    print(f"  Tier 4:   passed={t4.passed}  counts={t4.counts}")
    print("  Offset preset comparison:")
    for c in run.site_result.offset_report:
        print(f"    {c.label:12s} value_h={c.value_h:.4f}  "
              f"ghi>0&sun_down={c.ghi_positive_sun_down:5d}  ghi=0&sun_up={c.ghi_zero_sun_up:5d}")

    print("\n=== Pipelines ===")
    for label in run.pipelines.configs:
        failed = failed_check_names(run.pipelines.checks[label])
        yield_kwh = run.pipelines.annual_yield_kwh[label]
        print(f"  {label}: checks_passed={not failed}  annual_ac_energy={yield_kwh:.3f} kWh")
        if failed:
            print(f"    Failed checks: {', '.join(failed)}")
            for name in failed:
                vr = run.pipelines.checks[label][name]
                for problem in vr.problems:
                    print(f"      - {problem}")

    print("\n=== Phase 1 (disagreement check) ===")
    for (a, b), p1 in run.phase1_results.items():
        if isinstance(p1, str):
            print(f"  {a}-{b}: {p1}")
            continue
        outcome_text = _OUTCOME_TEXT.get(p1.outcome, str(p1.outcome))
        print(f"  {a}-{b}: outcome={p1.outcome} ({outcome_text})  k={p1.k}")
        for stage in ALL_STAGES:
            m = p1.metrics[stage]
            if m.not_computable_reason is not None:
                print(f"    {stage.name:<14} NOT COMPUTABLE: {m.not_computable_reason} (n_pooled={m.n_pooled})")
            else:
                print(f"    {stage.name:<14} nrmsd={m.nrmsd:.4f}  (n_pooled={m.n_pooled})")

    print("\n=== Phase 2 (propagation profile) ===")
    if run.phase2_result is None:
        print("  not run — no pair exceeds tau")
    else:
        for stage in ALL_STAGES:
            print(f"  {stage.name:<14} mean_nrmsd={run.phase2_result.mean_nrmsd[stage]:.4f}  "
                  f"max_nrmsd={run.phase2_result.max_nrmsd[stage]:.4f}")

    print("\n=== Phase 3 (Shapley attribution) ===")
    for (a, b), result in run.phase3_results.items():
        print(f"  {a}-{b}:")
        if isinstance(result, str):
            print(f"    {result}")
        elif isinstance(result, Phase3NotComputable):
            print(f"    {result.reason}")
        else:
            print(f"    RMSD={result.rmsd_ab:.4f}  efficiency check: "
                  f"sum(phi_final)={sum(result.phi_final.values()):.6f}")
            for stage in ALL_STAGES:
                share = result.share[stage]
                share_str = f"{share:.1%}" if share is not None else "n/a"
                print(f"      {stage.name:<14} phi_final={result.phi_final[stage]:>9.4f}  share={share_str}")

    print("\n=== Guided re-execution (O4) ===")
    if run.reexec_result is None:
        print("  not configured")
    else:
        r = run.reexec_result
        print(f"  Pair {r.pair}  config={r.config.label}  run_id={run.analysis_id}")
        print(f"  Disclaimer: {r.disclaimer!r}")
        print(f"  Annual yield: {r.annual_yield_kwh:.3f} kWh")


def cmd_run(args: argparse.Namespace) -> int:
    try:
        run = run_analysis(args.yaml_path)
    except AnalysisError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    _print_summary(run)
    write_outputs(run, args.out)
    print(f"\nWrote results.json, stage_outputs.csv, provenance.json to {args.out}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    if not is_reachable():
        print("FAILED: Postgres is unreachable.", file=sys.stderr)
        return 1
    analyses = list_analyses()
    if not analyses:
        print("No saved analyses.")
        return 0
    print(f"{'id':<34} {'name':<20} {'status':<14} {'created_at'}")
    for a in analyses:
        print(f"{a['id']:<34} {a['name']:<20} {a['status']:<14} {a['created_at']}")
    return 0


def cmd_db_init(_args: argparse.Namespace) -> int:
    if not is_reachable():
        print("FAILED: Postgres is unreachable (DATABASE_URL not set or the service isn't running).", file=sys.stderr)
        return 1
    with get_connection() as conn:
        run_schema(conn)
    print("Schema created/up to date.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m pvdials")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="run one analysis.yaml end to end")
    run_parser.add_argument("yaml_path")
    run_parser.add_argument("--out", required=True, help="output folder, e.g. outputs/my_run/")
    run_parser.set_defaults(func=cmd_run)

    list_parser = sub.add_parser("list", help="list saved analyses")
    list_parser.set_defaults(func=cmd_list)

    db_parser = sub.add_parser("db", help="database maintenance")
    db_sub = db_parser.add_subparsers(dest="db_command", required=True)
    db_init_parser = db_sub.add_parser("init", help="create/update the schema")
    db_init_parser.set_defaults(func=cmd_db_init)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
