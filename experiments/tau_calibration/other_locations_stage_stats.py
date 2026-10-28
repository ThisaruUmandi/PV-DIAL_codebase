"""Per-site detail behind tau_other_locations.py: for one weather file, the
nRMSD of every pair of the n sampled chains at every stage, the largest and
the mean per stage, the sampled chains, the file's sha256, and the pairs that
are outcome 1 / k = min(S) at the run's tau -- so two sites can be compared
pair by pair.

Uses tau_other_locations' own context, sampling (seed 0) and Phase 1 calls
unchanged; it only keeps what that script's summary.json drops. One site per
process, so the sites can run side by side.

Usage (from the repo root):
    PVDIAL_OFFSET_H=0.5 PVDIAL_TAU=0.013 python3 experiments/tau_calibration/other_locations_stage_stats.py [--n 1000] <csv>
Writes to outputs/other_locations_stage_stats_offset_<h>h/<csv stem>/.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
from n34_calibration import sample_chains
from run_settings import TAU, output_dir, require_tau, run_record
from tau_calibration import STAGE_ORDER
from tau_other_locations import SEED, build_context, confirm_all_chains_pass
from tau_ensemble_timing import run_all_pipelines

from pvdials.config import load_defaults
from pvdials.dla.phase1 import _differing_stages, run_phase1

OUTPUT_DIR = output_dir(Path(__file__).parent / "outputs" / "other_locations_stage_stats")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = sys.argv[1:]
    n = 1000
    if args[:1] == ["--n"]:
        n, args = int(args[1]), args[2:]
    if len(args) != 1:
        raise SystemExit(__doc__)
    path = Path(args[0])
    require_tau()
    defaults = load_defaults()
    out = OUTPUT_DIR / path.stem
    out.mkdir(parents=True, exist_ok=True)

    experiment, site = build_context(path, defaults)
    configs_by_label = {c.label: c for c in experiment.configs}
    sampled = sample_chains([c.label for c in experiment.configs], n, SEED)
    results = run_all_pipelines([configs_by_label[l] for l in sampled], experiment.shared_cec, experiment.shared_adr, experiment.defaults)
    confirm_all_chains_pass(sampled, results)

    pairs = list(itertools.combinations(sampled, 2))
    nrmsd = np.empty((len(pairs), len(STAGE_ORDER)))
    min_s = np.empty(len(pairs), dtype=np.int8)
    t0 = time.perf_counter()
    for i, (a, b) in enumerate(pairs):
        r = run_phase1(configs_by_label[a], results[a], configs_by_label[b], results[b], experiment.daylight, tau_value=0.0)
        nrmsd[i] = [r.metrics[s].nrmsd for s in STAGE_ORDER]
        min_s[i] = min(_differing_stages(configs_by_label[a], configs_by_label[b])).value - 1
        if (i + 1) % 50_000 == 0:
            print(f"  progress: {i + 1:,}/{len(pairs):,} pairs  elapsed={(time.perf_counter() - t0) / 60:.1f} min", flush=True)

    over = nrmsd > TAU
    outcome1 = ~over.any(axis=1)
    k = np.where(outcome1, -1, over.argmax(axis=1))
    k_is_min_s = k == min_s
    np.save(out / f"nrmsd_n{n}.npy", nrmsd)
    np.save(out / f"min_s_idx_n{n}.npy", min_s)
    stats = {
        "file": path.name,
        "weather_file_sha256": sha256_of(path),
        "run_record": run_record(experiment.ctx),
        "seed": SEED,
        "n_chains": n,
        "sampled_chains_sha256": hashlib.sha256("\n".join(sampled).encode()).hexdigest(),
        "sampled_chains_first5": sampled[:5],
        "n_pairs": len(pairs),
        "nan_pairs": int(np.isnan(nrmsd).any(axis=1).sum()),
        "stage_order": [s.name for s in STAGE_ORDER],
        "max_nrmsd_per_stage": nrmsd.max(axis=0).tolist(),
        "mean_nrmsd_per_stage": nrmsd.mean(axis=0).tolist(),
        f"share_outcome1_at_{TAU:g}": float(outcome1.mean()),
        f"share_k_eq_minS_at_{TAU:g}": float(k_is_min_s.mean()),
        "outcome1_pairs_sha256": hashlib.sha256(np.packbits(outcome1).tobytes()).hexdigest(),
        "k_eq_minS_pairs_sha256": hashlib.sha256(np.packbits(k_is_min_s).tobytes()).hexdigest(),
    }
    (out / "stage_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
