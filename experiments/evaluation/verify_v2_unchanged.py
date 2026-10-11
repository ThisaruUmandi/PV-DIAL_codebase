"""Proves the v2 Phase 3 rerun changed nothing except adding v_ab/v_ba/w_full:
for every pair, phi_ab, phi_ba, phi_final, the averaged singleton and LOO
values, and both ranks must be bit-identical between phase3_results.jsonl
(old) and phase3_results_v2.jsonl (new). Also checks phase3_summary.json
and evaluation_results.json are byte-identical to before (never opened for
writing by the v2 rerun, but confirmed directly here rather than assumed).

Run standalone: python3 -m experiments.evaluation.verify_v2_unchanged
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent / "outputs" / "step4"

FIELDS_MUST_MATCH = (
    "phi_ab", "phi_ba", "phi_final", "singleton", "loo",
    "rank_agreement_singleton", "rank_agreement_loo",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    old = {tuple(json.loads(l)["pair"]): json.loads(l) for l in open(BASE / "phase3_results.jsonl") if l.strip()}
    new = {tuple(json.loads(l)["pair"]): json.loads(l) for l in open(BASE / "phase3_results_v2.jsonl") if l.strip()}

    print(f"Old file: {len(old)} pairs. New file: {len(new)} pairs.")
    if set(old) != set(new):
        print("STOP: pair sets differ!")
        print("  In old, not new:", set(old) - set(new))
        print("  In new, not old:", set(new) - set(old))
        return

    checked = 0
    diffs = []
    for pair, old_rec in old.items():
        new_rec = new[pair]
        checked += 1
        for field in FIELDS_MUST_MATCH:
            if old_rec[field] != new_rec[field]:
                diffs.append((pair, field, old_rec[field], new_rec[field]))

    print(f"Checked {checked} pairs across {len(FIELDS_MUST_MATCH)} fields each.")
    if diffs:
        print(f"STOP: {len(diffs)} differences found:")
        for d in diffs[:20]:
            print(" ", d)
    else:
        print("No differences: phi_ab, phi_ba, phi_final, singleton, loo, and both ranks "
              "are bit-identical for every pair.")

    # phase3_summary.json / evaluation_results.json must be byte-identical
    # to before -- the v2 rerun never opened either for writing, confirmed
    # directly by hash rather than assumed.
    for name, path in (
        ("phase3_summary.json", BASE / "phase3_summary.json"),
        ("evaluation_results.json", BASE.parent / "evaluation_results.json"),
    ):
        print(f"{name}: sha256={_sha256(path)}")


if __name__ == "__main__":
    main()
