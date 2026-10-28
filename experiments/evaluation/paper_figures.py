"""The paper's greyscale figures, redrawn from the saved results:

  Fig. 2  stage named by each method, all pairs        paper_fig2_stage_named.png
  Fig. 3  Phase 2 against the hand calculation          paper_fig3_hand_check_table.png
  Fig. 4  Shapley vs OAT vs LOO, median across pairs    paper_fig4_shapley_oat_loo.png

The originals (fig2_stage_named_gray.png, fig4_hand_calc_table_gray.png and
fig3_shapley_oat_loo_gray.png, 27/10) were drawn by code that was never in the
repo. These reproduce them from the results files with the same data, text,
styling and layout to within a few pixels -- not byte-identical, since the
original code's exact layout details are unknown.

Every number in a title, label or bar comes from the results files. At a
non-zero PVDIAL_OFFSET_H (run_settings), reads that offset's folders and writes
to paper_figures_offset_<h>h/; the 0 h figures are untouched.

Run standalone: python3 -m experiments.evaluation.paper_figures
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from experiments.evaluation.make_figures import (  # noqa: E402
    BASE,
    FULL_NAME,
    HAND_FILE,
    STAGE_KEYS,
    _by_stage,
    _colombo,
    _hand_values,
    _load,
    _ran,
    _skip,
    _step,
)
from experiments.tau_calibration.run_settings import output_dir, require_tau  # noqa: E402

OUT_DIR = output_dir(BASE / "paper_figures")
TOOL = "PV-DIALS"  # the tool's name in the paper
ZERO_H_CACHE = (BASE.parents[1] / "tau_calibration" / "outputs" / "trivial_plateau_amendment" / "exhaustive_cache")

RC = {
    "font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 10, "axes.titlesize": 11,
    "axes.labelsize": 10, "ytick.labelsize": 10,
    "axes.grid": True, "axes.grid.axis": "y", "axes.axisbelow": True, "grid.color": "#D9D9D9", "grid.linewidth": 0.5,
}
DARK, MID = "#262626", "#999999"  # first and second series; the third is white, hatched
HATCH = "////"


def _save(fig, name: str) -> None:
    fig.savefig(OUT_DIR / name, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"    saved {OUT_DIR / name}", flush=True)


def _stage_counts(all_pairs: dict) -> dict:
    """step4 stores the per-stage counts; the 0 h all-pairs file predates
    them, so there they are derived from the 0 h R1 cache at its own tau."""
    if "stage_counts" in all_pairs:
        return all_pairs["stage_counts"]
    from experiments.evaluation.step4_ensemble import stage_counts

    counts = stage_counts(np.load(ZERO_H_CACHE / "nrmsd_matrix_n2058_exhaustive.npy"),
                          np.load(ZERO_H_CACHE / "min_s_idx_n2058_exhaustive.npy"), all_pairs["tau"])
    assert counts["phase1_none"] == round(all_pairs["outcome1_share"] * all_pairs["n_pairs"]), "0 h cache and all-pairs file disagree"
    return counts


def fig2_stage_named() -> None:
    print("Paper Fig. 2: stage named by each method, all pairs", flush=True)
    d = _load(_step("step4") / "all_pairs_baseline_check.json")
    counts, n = _stage_counts(d), d["n_pairs"]
    assert counts["stage_order"] == STAGE_KEYS
    series = [
        (f"{TOOL} (Phase 1)", counts["phase1"] + [counts["phase1_none"]], dict(color=DARK)),
        ("Baseline A (first differing stage)", counts["baseline_a"] + [0], dict(color=MID)),
        ("Baseline B (largest rise)", counts["baseline_b"] + [0], dict(color="white", hatch=HATCH)),
    ]
    with plt.rc_context({**RC, "xtick.labelsize": 9, "legend.fontsize": 8.5}):
        fig, ax = plt.subplots(figsize=(7.5, 4.0))
        x = np.arange(6)
        w = 0.27
        for j, (label, values, style) in enumerate(series):
            shares = [v / n * 100 for v in values]
            print(f"    {label}: {[round(s, 1) for s in shares]}  <- step4/all_pairs_baseline_check.json :: stage_counts", flush=True)
            ax.bar(x + (j - 1) * w, shares, w, edgecolor="black", linewidth=0.8, label=label, **style)
            for xi, share in zip(x + (j - 1) * w, shares):
                ax.text(xi, share + 1.2, f"{round(share, 1):g}", ha="center", va="bottom", fontsize=8.5)
        ax.set_ylim(0, 100)
        ax.set_xticks(x)
        ax.set_xticklabels([FULL_NAME[k] for k in STAGE_KEYS] + ["No stage\nover the threshold"])
        ax.set_ylabel("Share of all pairs (%)")
        ax.set_title(f"Stage named by each method ({n:,} pairs, τ = {d['tau']:g})")
        ax.legend(loc="upper right")
        fig.tight_layout()
        _save(fig, "paper_fig2_stage_named.png")


def fig3_hand_check_table() -> None:
    print("Paper Fig. 3: Phase 2 against the hand calculation", flush=True)
    r = _colombo()
    hand = _hand_values()
    if not _ran(r["phase2"]) or hand is None:
        return _skip("paper Fig. 3", "Phase 2 did not run" if not _ran(r["phase2"]) else f"no hand values in {HAND_FILE} yet")
    rows = []
    for prefix, key, by_hand in (("Average disagreement, ", "mean_nrmsd", hand[0]),
                                 ("Highest disagreement, ", "max_nrmsd", hand[1]),
                                 ("Change from previous stage, ", "delta", hand[2])):
        values = _by_stage(r["phase2"][key])
        for i, k in enumerate(STAGE_KEYS):
            pv = round(values[k], 6)
            diff = abs(pv - by_hand[i])
            match = "Yes" if diff < 1e-9 else ("Yes (rounding)" if diff <= 1.0000001e-6 else "No")
            rows.append([prefix + FULL_NAME[k], f"{pv:.6f}", f"{by_hand[i]:.6f}", match])
    fig, ax = plt.subplots(figsize=(8.0, 5.1))
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=["Quantity", TOOL, "By hand", "Match"], loc="upper center",
                     cellLoc="center", colWidths=[0.46, 0.18, 0.18, 0.18])
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.32)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("0.6")
        if row == 0:
            cell.set_facecolor("0.83")
            cell.set_text_props(fontweight="bold")
        elif row % 2 == 0:
            cell.set_facecolor("0.95")
    ax.set_title(f"{TOOL} against hand calculation: Colombo run, disagreement across stages", fontsize=11, pad=20)
    _save(fig, "paper_fig3_hand_check_table.png")


def fig4_shapley_oat_loo() -> None:
    print("Paper Fig. 4: Shapley vs OAT vs LOO, sum of stage values / total AC RMSD", flush=True)
    records = [json.loads(line) for line in open(_step("step4") / "phase3_results.jsonl") if line.strip()]
    ratios = [np.array([sum(r[key][s] for s in r["S"]) / r["rmsd_ab"] for r in records])
              for key in ("phi_final", "singleton", "loo")]
    med = [float(np.median(a)) for a in ratios]
    lo = [float(np.percentile(a, 10)) for a in ratios]
    hi = [float(np.percentile(a, 90)) for a in ratios]
    for name, m, l, h in zip(("Shapley", "OAT", "LOO"), med, lo, hi):
        print(f"    {name}: median {m:.4f}, 10th-90th percentile {l:.4f}-{h:.4f}  <- step4/phase3_results.jsonl", flush=True)
    with plt.rc_context({**RC, "xtick.labelsize": 10}):
        fig, ax = plt.subplots(figsize=(5.9, 4.18))
        x = np.arange(3)
        for xi, m, style in zip(x, med, (dict(color=DARK), dict(color=MID), dict(color="white", hatch=HATCH))):
            ax.bar(xi, m, 0.6, edgecolor="black", linewidth=0.8, **style)
        ax.errorbar(x, med, yerr=[np.subtract(med, lo), np.subtract(hi, med)], fmt="none", ecolor="black",
                    elinewidth=1.2, capsize=8, capthick=1.2)
        ax.axhline(1.0, color="black", linewidth=1.2, linestyle="--", zorder=3)
        for xi, m, colour, boxed in zip(x, med, ("white", "black", "black"), (False, False, True)):
            ax.text(xi, 0.08, f"{m:.2f}", ha="center", va="bottom", fontsize=12, fontweight="bold", color=colour,
                    bbox=dict(facecolor="white", edgecolor="none", pad=1.5) if boxed else None)
        ax.text(0.025, 0.975, "whiskers: 10th–90th percentile", transform=ax.transAxes, ha="left", va="top",
                fontsize=8, color="#333333")
        ax.text(2.42, 1.03, "adds up\nto the total", ha="left", va="bottom", fontsize=8.5, color="#333333")
        ax.set_xlim(-0.5, 2.75)
        ax.set_ylim(0, max(2.1, max(hi) * 1.1))
        ax.set_xticks(x)
        ax.set_xticklabels([f"Shapley\n({TOOL})", "One-at-a-time\n(OAT)", "Leave-one-out\n(LOO)"])
        ax.set_ylabel("Sum of stage values ÷ total AC RMSD")
        ax.set_title(f"Shapley vs OAT vs LOO: median across {len(records):,} pairs")
        fig.tight_layout()
        _save(fig, "paper_fig4_shapley_oat_loo.png")


def main() -> None:
    require_tau()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig2_stage_named()
    fig3_hand_check_table()
    fig4_shapley_oat_loo()


if __name__ == "__main__":
    main()
