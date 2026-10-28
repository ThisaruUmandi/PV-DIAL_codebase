"""Annual AC energy of all 2,058 chains, and how far apart two chains' annual
energies are, over all 2,116,653 pairs and over the pairs of each Phase 1
outcome at the run's tau.

Reads the R1 cache for the pair order and the nRMSD values (never rewrites it)
and reruns the 2,058 pipelines for annual energy only -- no Phase 1, 2 or 3.
The pair order is itertools.combinations over the cache's label order, the
same as R1 and step4.

Energy of a chain: guided_reexecution.annual_yield_kwh (the integral the
worked example and the report use). A pair's difference is
|E_a - E_b| in kWh and, in %, of the mean of the two energies.

Run: PVDIAL_OFFSET_H=0.5 PVDIAL_TAU=0.013 python3 -m experiments.evaluation.annual_energy_by_outcome
Writes to outputs/annual_energy_offset_<h>h/ (a non-zero offset is required).
"""

from __future__ import annotations

import itertools
import json
import time
from pathlib import Path

import numpy as np

from pvdials.guided_reexecution import annual_yield_kwh
from pvdials.physics.pipeline import run_pipeline
from pvdials.warning_filter import ChandrupatlaWarningFilter

from experiments.evaluation.chain_population import build_configs
from experiments.evaluation.step0_measure_phase3 import _shared
from experiments.evaluation.step4_ensemble import CACHE_DIR
from experiments.evaluation.weather_source import verify_thesis_weather_file
from experiments.tau_calibration.run_settings import OFFSET_H, TAU, output_dir, require_tau, run_defaults, run_record

OUT_DIR = output_dir(Path(__file__).resolve().parent / "outputs" / "annual_energy")
R5_RESULTS = output_dir(Path(__file__).resolve().parent / "outputs" / "step2") / "colombo" / "results.json"
OUTCOMES = {1: "outcome 1 (nothing over tau)", 2: "outcome 2 (disagreement found)", 3: "outcome 3 (compensating differences)"}


def _stats(diff_kwh: np.ndarray, diff_pct: np.ndarray) -> dict:
    def block(x):
        return {"min": float(x.min()), "median": float(np.median(x)), "max": float(x.max()),
                "p5": float(np.percentile(x, 5)), "p95": float(np.percentile(x, 95))}
    return {"n_pairs": int(len(diff_kwh)), "kwh": block(diff_kwh), "percent_of_mean": block(diff_pct)}


def main() -> None:
    if OFFSET_H == 0.0:
        raise SystemExit("STOP: this writes only to an offset folder -- set PVDIAL_OFFSET_H.")
    require_tau()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    weather_info = verify_thesis_weather_file()

    labels = (CACHE_DIR / "labels_n2058_exhaustive.txt").read_text().splitlines()
    shared_cec, shared_adr, _ = _shared()
    configs = build_configs(shared_cec.module, shared_cec.mounting)
    assert [c.label for c in configs] == labels, "chain order differs from the R1 cache"
    defaults = run_defaults()

    print(f"Running {len(configs)} pipelines for annual energy at {OFFSET_H:g} h ...", flush=True)
    t0 = time.perf_counter()
    energy = np.empty(len(configs))
    with ChandrupatlaWarningFilter() as wf:
        for i, config in enumerate(configs):
            shared = shared_adr if config.ac_model == "adr" else shared_cec
            energy[i] = annual_yield_kwh(run_pipeline(config, shared, defaults))
    print(f"Done in {time.perf_counter() - t0:.1f} s ({wf.count} known scipy warnings suppressed)", flush=True)

    # Cross-check: the three worked-example chains' energies from R5 appear among the 2,058.
    r5 = json.loads(R5_RESULTS.read_text())
    r5_check = {label: float(np.abs(energy - p["annual_yield_kwh"]).min()) for label, p in r5["pipelines"].items()}
    print("Smallest |difference| between each R5 energy and any chain (kWh):", r5_check, flush=True)
    assert max(r5_check.values()) < 1e-6, "R5's annual energies are not among the rerun chains"

    n = len(labels)
    idx_a, idx_b = np.triu_indices(n, k=1)  # row-major (i<j): the itertools.combinations order
    assert len(idx_a) == len(np.load(CACHE_DIR / "min_s_idx_n2058_exhaustive.npy"))
    assert next(itertools.combinations(range(n), 2)) == (int(idx_a[0]), int(idx_b[0]))
    diff_kwh = np.abs(energy[idx_a] - energy[idx_b])
    diff_pct = diff_kwh / ((energy[idx_a] + energy[idx_b]) / 2) * 100

    nrmsd = np.load(CACHE_DIR / "nrmsd_matrix_n2058_exhaustive.npy")
    over = nrmsd > TAU
    outcome = np.where(~over.any(axis=1), 1, np.where(nrmsd[:, 4] > TAU, 2, 3))

    summary = {
        "run_record": run_record(_shared_ctx()),
        "weather_file": weather_info,
        "tau": TAU,
        "pct_definition": "|E_a - E_b| / mean(E_a, E_b) * 100",
        "chain_energy_kwh": {"min": float(energy.min()), "median": float(np.median(energy)), "max": float(energy.max())},
        "r5_cross_check_kwh": r5_check,
        "all_pairs": _stats(diff_kwh, diff_pct),
        "by_outcome": {OUTCOMES[o]: _stats(diff_kwh[outcome == o], diff_pct[outcome == o]) for o in (1, 2, 3)},
    }
    (OUT_DIR / "annual_energy_summary.json").write_text(json.dumps(summary, indent=2))
    with open(OUT_DIR / "chain_annual_energy_kwh.csv", "w") as f:
        f.write("label,annual_energy_kwh\n")
        f.writelines(f"{label},{e!r}\n" for label, e in zip(labels, energy))
    print(json.dumps({k: summary[k] for k in ("all_pairs",)}, indent=2))
    print(json.dumps(summary["by_outcome"][OUTCOMES[3]], indent=2))
    print(f"Wrote {OUT_DIR}")


def _shared_ctx():
    return _shared()[0].ctx


if __name__ == "__main__":
    main()
