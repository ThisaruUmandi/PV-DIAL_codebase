"""Evaluation KT Step 6 figures. Reads only saved Steps 2-5 outputs, no
reruns. Grayscale-readable by construction (single-hue lines/bars, a
sequential grey heatmap with every cell annotated by its own count, so
nothing depends on color perception at all) -- no verdict wording anywhere
in a title/label/caption.

Run standalone: python3 -m experiments.evaluation.make_figures
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BASE = Path(__file__).resolve().parent / "outputs"
FIGURES_DIR = BASE / "figures"
CACHE_DIR = Path(__file__).resolve().parents[1] / "tau_calibration" / "outputs" / "trivial_plateau_amendment" / "exhaustive_cache"

STAGE_NAMES = ["DECOMP", "TRANSP", "TEMP", "DC", "AC"]


def _load(path: Path):
    return json.loads(path.read_text())


def figure_tau_curve() -> None:
    d = _load(BASE / "step4" / "tau_band_curve.json")
    grid = np.array(d["tau_grid"])
    band = d["stable_band"]
    outcome1 = np.array(d["outcome1_share_by_tau"])
    k_eq_mins = np.array(d["k_eq_min_s_share_by_tau"])

    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=300)
    ax.axvspan(band[0], band[1], color="0.85", zorder=0, label=f"stable band [{band[0]}, {band[1]}]")
    ax.plot(grid, outcome1, color="0.15", linewidth=1.6, label="outcome 1 share")
    ax.plot(grid, k_eq_mins, color="0.15", linewidth=1.6, linestyle="--", label="k = min(S) share")
    ax.axvline(0.093, color="0.4", linewidth=1.0, linestyle=":", label="default tau = 0.093")
    ax.set_xlabel("tau")
    ax.set_ylabel("share of pairs")
    ax.set_title("All-pairs Baseline A figures across the tau grid")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="upper right", frameon=False, fontsize=8)
    ax.grid(True, color="0.9", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "tau_curve.png", dpi=300)
    plt.close(fig)


def figure_gap_histograms() -> None:
    records = [json.loads(l) for l in open(BASE / "step4" / "phase3_results.jsonl") if l.strip()]
    gap_singleton = [r["gap_singleton"] for r in records if _finite(r["gap_singleton"])]
    gap_loo = [r["gap_loo"] for r in records if _finite(r["gap_loo"])]

    fig, axes = plt.subplots(1, 2, figsize=(9, 4), dpi=300)
    for ax, data, title in ((axes[0], gap_singleton, "Attribution gap (singleton)"),
                             (axes[1], gap_loo, "Attribution gap (leave-one-out)")):
        ax.hist(data, bins=40, color="0.35", edgecolor="0.15", linewidth=0.5)
        ax.set_xlabel("gap")
        ax.set_ylabel("count of eligible pairs")
        ax.set_title(title)
        ax.grid(True, color="0.9", linewidth=0.5, axis="y")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "gap_histograms.png", dpi=300)
    plt.close(fig)


def _finite(x) -> bool:
    return x is not None and x == x and abs(x) != float("inf")


def figure_k_times_b_heatmap() -> None:
    d = _load(BASE / "step4" / "all_pairs_baseline_check.json")
    table = np.array(d["k_times_b_table"])

    fig, ax = plt.subplots(figsize=(5.5, 5), dpi=300)
    im = ax.imshow(table, cmap="Greys", aspect="equal")
    ax.set_xticks(range(5))
    ax.set_yticks(range(5))
    ax.set_xticklabels(STAGE_NAMES)
    ax.set_yticklabels(STAGE_NAMES)
    ax.set_xlabel("Baseline B")
    ax.set_ylabel("k (Phase 1)")
    ax.set_title("All-pairs k x Baseline B (counts)")
    vmax = table.max()
    for i in range(5):
        for j in range(5):
            value = table[i, j]
            color = "white" if value > vmax * 0.5 else "black"
            ax.text(j, i, f"{value:,}", ha="center", va="center", color=color, fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="pair count")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "k_times_b_heatmap.png", dpi=300)
    plt.close(fig)


def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    figure_tau_curve()
    figure_gap_histograms()
    figure_k_times_b_heatmap()
    print(f"Wrote 3 figures to {FIGURES_DIR}")


if __name__ == "__main__":
    main()
