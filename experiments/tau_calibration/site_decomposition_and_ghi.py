"""Per site (Colombo, Galle, Kandy, Jaffna): median and maximum decomposition
nRMSD over the same 1,000 seed-0 chains, and the annual GHI of the weather
file. Read-only: the nRMSD come from other_locations_stage_stats.py's saved
arrays (Galle, Kandy, Jaffna) and the R1 cache (Colombo, restricted to the
same chains, plus all 2,058 for reference).

Annual GHI = sum of hourly GHI (W/m^2, one row per hour) / 1000, in kWh/m^2,
over the rows of the file after preprocessing -- the weather the runs used.

Usage (repo root): PVDIAL_OFFSET_H=0.5 python3 experiments/tau_calibration/site_decomposition_and_ghi.py
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
from n34_calibration import sample_chains
from run_settings import output_dir
from trivial_plateau_amendment_exhaustive import CACHE_DIR

from pvdials.data.column_mapper import detect_columns
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv

ROOT = Path(__file__).resolve().parents[2]
STATS = output_dir(Path(__file__).parent / "outputs" / "other_locations_stage_stats")
OUT = output_dir(Path(__file__).parent / "outputs" / "other_locations_stage_stats") / "decomposition_and_ghi.json"
N, SEED = 1000, 0
SITES = {
    "Colombo": "tmy_6.944_79.856_2005_2020.csv",
    "Galle": "tmy_6.034_80.216_2005_2023.csv",
    "Kandy": "tmy_7.296_80.636_2005_2023.csv",
    "Jaffna": "tmy_9.666_80.009_2005_2023.csv",
}


def annual_ghi_kwh_m2(path: Path) -> dict:
    weather = preprocess((u := load_uploaded_csv(path)).table, detect_columns(u.table)).df
    return {"rows": int(len(weather)), "annual_ghi_kwh_m2": float(weather["ghi"].sum() / 1000)}


def main() -> None:
    labels = (CACHE_DIR / "labels_n2058_exhaustive.txt").read_text().splitlines()
    n = len(labels)
    cache = np.load(CACHE_DIR / "nrmsd_matrix_n2058_exhaustive.npy")
    pos = sorted(labels.index(l) for l in sample_chains(labels, N, SEED))
    rows = np.array([i * n - i * (i + 1) // 2 + (j - i - 1) for i, j in itertools.combinations(pos, 2)])
    out = {}
    for site, csv in SITES.items():
        dec = cache[rows, 0] if site == "Colombo" else np.load(STATS / Path(csv).stem / f"nrmsd_n{N}.npy")[:, 0]
        out[site] = {"file": csv, "decomposition_nrmsd_median": float(np.median(dec)),
                     "decomposition_nrmsd_max": float(dec.max()), "n_pairs": int(len(dec)),
                     **annual_ghi_kwh_m2(ROOT / "data" / "weather" / csv)}
    out["Colombo"]["all_2058_chains"] = {"median": float(np.median(cache[:, 0])), "max": float(cache[:, 0].max()),
                                         "n_pairs": int(len(cache))}
    OUT.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
