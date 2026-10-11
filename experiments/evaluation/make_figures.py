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
import matplotlib.ticker  # noqa: F401
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


# ---------------------------------------------------------------------------
# Figures 4-12 (added). Plain-English wording for readers who use English as a
# second language; no code names or symbols in any figure. Each figure prints
# every plotted value with the file and key it came from, then a caption.
# Run only these (leaves figures 1-3 untouched):
#   python3 -m experiments.evaluation.make_figures --extra-only
# ---------------------------------------------------------------------------

import re  # noqa: E402

from experiments.evaluation.baselines import baseline_a_stage, baseline_b_stage  # noqa: E402
from experiments.evaluation.comparators import shapley_values  # noqa: E402
from pvdials.types import Stage  # noqa: E402

BLUE = "#0072B2"  # PV-DIAL, in every figure
ORANGE = "#E69F00"  # the comparison method, in every figure
DARK_GREY = "0.25"  # reference lines

COLOMBO_RESULTS = BASE / "step2" / "colombo" / "results.json"
COLOMBO_ID = "47db8644412e47f088fbc560c43c4b15"

FULL_NAME = {
    "DECOMPOSITION": "Decomposition",
    "TRANSPOSITION": "Transposition",
    "TEMPERATURE": "Temperature",
    "DC": "DC",
    "AC": "AC",
}
STAGE_KEYS = list(FULL_NAME)
STAGE_LABELS = [FULL_NAME[k] for k in STAGE_KEYS]

# Section 5, rows 10-24 of pv-dial-hand-check.md (Phase 2 hand calculation),
# six decimals as written there. The file is not in the repo; these are the
# "By hand" column exactly as supplied.
HAND_MEAN = [0.110194, 0.005079, 0.139547, 0.015883, 0.015773]
HAND_MAX = [0.139635, 0.006528, 0.194589, 0.022484, 0.022310]
HAND_DELTA = [0.110194, -0.105115, 0.134468, -0.123664, -0.000110]


def _src(label: str, value, file: str, key: str) -> None:
    print(f"    {label}: {value:.6f}  <- {file} :: {key}" if isinstance(value, float) else f"    {label}: {value}  <- {file} :: {key}", flush=True)


def _caption(number: int, text: str) -> None:
    print(f"  Caption {number}: {text}", flush=True)


def _colombo() -> dict:
    d = _load(COLOMBO_RESULTS)
    assert d["analysis_id"] == COLOMBO_ID, f"{COLOMBO_RESULTS} is not the Colombo run {COLOMBO_ID}"
    return d


def _by_stage(entries: list, field: str = "stage") -> dict:
    return {e[field]: e["value"] for e in entries}


def _label_bars(ax, bars, fmt: str, fontsize: int = 7) -> None:
    for bar in bars:
        h = bar.get_height()
        va, offset = ("bottom", 2) if h >= 0 else ("top", -2)
        ax.annotate(fmt.format(h), (bar.get_x() + bar.get_width() / 2, h), xytext=(0, offset),
                    textcoords="offset points", ha="center", va=va, fontsize=fontsize,
                    bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.85))


def _style_axes(ax, ylabel: str, title: str) -> None:
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=10)
    ax.grid(True, color="0.9", linewidth=0.5, axis="y")
    ax.set_axisbelow(True)


def _save(fig, name: str, tight: bool = False) -> None:
    fig.savefig(FIGURES_DIR / name, dpi=300, **({"bbox_inches": "tight", "pad_inches": 0.2} if tight else {}))
    plt.close(fig)
    print(f"    saved {FIGURES_DIR / name}", flush=True)


def figure4_phase1_vs_baseline_a_all_pairs() -> None:
    print("Figure 4: PV-DIAL against Baseline A, all pairs", flush=True)
    f = "step4/all_pairs_baseline_check.json"
    d = _load(BASE / "step4" / "all_pairs_baseline_check.json")
    shares = [d["k_eq_min_s_share"], d["outcome1_share"], d["informative_rate_part_b_k_gt_mins"]]
    labels = ["Same stage as\nBaseline A", "No stage above\nthe threshold", "PV-DIAL names\na later stage"]
    _src("Same stage as Baseline A", shares[0], f, "k_eq_min_s_share")
    _src("No stage above the threshold", shares[1], f, "outcome1_share")
    _src("PV-DIAL names a later stage", shares[2], f, "informative_rate_part_b_k_gt_mins")
    _src("Number of pairs", d["n_pairs"], f, "n_pairs")
    _src("Threshold", d["tau"], f, "tau")
    assert abs(sum(shares) - 1.0) < 1e-9, "the three shares must add to 1"

    with plt.rc_context({"hatch.linewidth": 1.0}):
        fig, ax = plt.subplots(figsize=(7, 4.5), dpi=300)
        bars = ax.bar(labels, [s * 100 for s in shares], color=BLUE, edgecolor=DARK_GREY, linewidth=0.8, width=0.6)
        bars[1].set_hatch("//")
        bars[2].set_hatch("xx")
        _label_bars(ax, bars, "{:.1f} %", fontsize=9)
        ax.set_ylim(0, 60)
        _style_axes(ax, "Share of all 2,116,653 pairs (%)",
                    "How PV-DIAL's answer compares with Baseline A\n(all pairs, threshold 0.093)")
        fig.tight_layout()
        _save(fig, "fig04_phase1_vs_baseline_a_all_pairs.png")
    _caption(4, "In 45.8 % of all pairs PV-DIAL names the same stage as Baseline A, and in the other 54.2 % it either finds no stage above the threshold (30.3 %) or names a later stage (23.9 %).")


def figure5_colombo_pair_three_methods() -> None:
    print("Figure 5: Colombo pair A-B, three methods", flush=True)
    f = "step2/colombo/results.json"
    r = _colombo()
    p1 = r["phase1"]["A-B"]
    nrmsd = {m["stage"]: m["nrmsd"] for m in p1["metrics"]}
    tau = p1["tau"]["value"]
    for i, k in enumerate(STAGE_KEYS):
        _src(f"Disagreement, {FULL_NAME[k]}", nrmsd[k], f, f"phase1.A-B.metrics[{i}].nrmsd")
    _src("Threshold", tau, f, "phase1.A-B.tau.value")
    pv = p1["k"]
    differing = frozenset(Stage[n] for n in p1["differing_stages"])
    base_a = baseline_a_stage(differing).name
    base_b = baseline_b_stage({Stage[k]: v for k, v in nrmsd.items()}).name
    _src("PV-DIAL names", FULL_NAME[pv], f, "phase1.A-B.k")
    _src("Baseline A names", FULL_NAME[base_a], f, "phase1.A-B.differing_stages -> baselines.baseline_a_stage")
    _src("Baseline B names", FULL_NAME[base_b], f, "phase1.A-B.metrics[].nrmsd -> baselines.baseline_b_stage")

    fig, ax = plt.subplots(figsize=(8, 4.8), dpi=300)
    x = np.arange(5)
    y = [nrmsd[k] for k in STAGE_KEYS]
    ax.plot(x, y, color=DARK_GREY, linewidth=1.6, marker="o", markersize=3, label="Disagreement (nRMSD)")
    ax.axhline(tau, color=DARK_GREY, linewidth=1.2, linestyle="--", label=f"Threshold ({tau})")
    methods = [
        ("PV-DIAL", pv, dict(marker="o", color=BLUE, markeredgecolor=DARK_GREY)),
        ("Baseline A (first stage where the models differ)", base_a,
         dict(marker="s", color=ORANGE, markeredgecolor=DARK_GREY)),
        ("Baseline B (stage with the biggest rise)", base_b,
         dict(marker="^", color="white", markeredgecolor=ORANGE, markeredgewidth=2)),
    ]
    on_stage: dict[str, list] = {}
    for m in methods:
        on_stage.setdefault(m[1], []).append(m)
    for stage_key, group in on_stage.items():
        i = STAGE_KEYS.index(stage_key)
        for j, (label, _, style) in enumerate(group):
            shift = (j - (len(group) - 1) / 2) * 0.16  # side by side when stages are shared
            ax.plot([i + shift], [nrmsd[stage_key] + 0.014], linestyle="none", markersize=11, label=label, **style)
    ax.set_xticks(x)
    ax.set_xticklabels(STAGE_LABELS)
    ax.set_ylim(0, 0.24)
    _style_axes(ax, "Disagreement (nRMSD)", "Which stage each method names: Colombo pair A-B")
    ax.legend(loc="upper right", frameon=False, fontsize=7.5)
    fig.tight_layout()
    _save(fig, "fig05_colombo_ab_three_methods.png")
    _caption(5, "For Colombo pair A-B, PV-DIAL and Baseline A both name Decomposition, while Baseline B names Temperature, the stage with the biggest rise.")


def figure6_tau_curve_zoom() -> None:
    print("Figure 6: threshold curve, 0 to 0.3", flush=True)
    f = "step4/tau_band_curve.json"
    d = _load(BASE / "step4" / "tau_band_curve.json")
    grid = np.array(d["tau_grid"])
    band = d["stable_band"]
    outcome1 = np.array(d["outcome1_share_by_tau"])
    same_a = np.array(d["k_eq_min_s_share_by_tau"])
    sel = grid <= 0.3
    _src("Stable range", f"{band[0]} to {band[1]}", f, "stable_band")
    _src("Points plotted (threshold 0 to 0.3)", int(sel.sum()), f, "tau_grid")
    for t in (0.092, 0.094):
        i = int(np.argmin(abs(grid - t)))
        _src(f"Share with no stage above the threshold at {grid[i]:.3f}", float(outcome1[i]), f, f"outcome1_share_by_tau[{i}]")
        _src(f"Share naming the same stage as Baseline A at {grid[i]:.3f}", float(same_a[i]), f, f"k_eq_min_s_share_by_tau[{i}]")

    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=300)
    ax.axvspan(band[0], band[1], facecolor="0.9", edgecolor="0.6", hatch="//", zorder=0,
               label=f"Stable range ({band[0]} to {band[1]})")
    ax.plot(grid[sel], outcome1[sel], color=BLUE, linewidth=1.8, label="No stage above the threshold")
    ax.plot(grid[sel], same_a[sel], color=BLUE, linewidth=1.8, linestyle="--",
            label="PV-DIAL names the same stage as Baseline A")
    ax.axvline(0.093, color=DARK_GREY, linewidth=1.2, linestyle=":", label="Threshold (0.093)")
    ax.set_xlim(0, 0.3)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Threshold")
    _style_axes(ax, "Share of all pairs", "All pairs: how the answers change with the threshold (0 to 0.3)")
    ax.legend(loc="center right", frameon=False, fontsize=8)
    ax.grid(True, color="0.9", linewidth=0.5)
    fig.tight_layout()
    _save(fig, "fig06_threshold_curve_0_to_0.3.png")
    _caption(6, "Between thresholds 0.088 and 0.098 the two shares stay almost flat, so the default threshold of 0.093 sits inside a stable range.")


def figure7_phase2_mean_max() -> None:
    print("Figure 7: Phase 2 average and highest disagreement per stage", flush=True)
    f = "step2/colombo/results.json"
    r = _colombo()
    mean = [_by_stage(r["phase2"]["mean_nrmsd"])[k] for k in STAGE_KEYS]
    mx = [_by_stage(r["phase2"]["max_nrmsd"])[k] for k in STAGE_KEYS]
    tau = r["phase1"]["A-B"]["tau"]["value"]
    for i, k in enumerate(STAGE_KEYS):
        _src(f"Average, {FULL_NAME[k]}", mean[i], f, f"phase2.mean_nrmsd[{i}].value")
        _src(f"Highest, {FULL_NAME[k]}", mx[i], f, f"phase2.max_nrmsd[{i}].value")
    _src("Threshold", tau, f, "phase1.A-B.tau.value")

    with plt.rc_context({"hatch.linewidth": 1.0}):
        fig, ax = plt.subplots(figsize=(8, 4.8), dpi=300)
        x = np.arange(5)
        w = 0.38
        b1 = ax.bar(x - w / 2, mean, w, color=BLUE, edgecolor=DARK_GREY, linewidth=0.8, label="Average of the three pairs")
        b2 = ax.bar(x + w / 2, mx, w, color=BLUE, edgecolor=DARK_GREY, linewidth=0.8, hatch="//",
                    label="Highest of the three pairs")
        _label_bars(ax, b1, "{:.3f}")
        _label_bars(ax, b2, "{:.3f}")
        ax.axhline(tau, color=DARK_GREY, linewidth=1.2, linestyle="--", label=f"Threshold ({tau})")
        ax.set_xticks(x)
        ax.set_xticklabels(STAGE_LABELS)
        ax.set_ylim(0, 0.23)
        _style_axes(ax, "Disagreement (nRMSD)", "Average and highest disagreement at each stage: Colombo run")
        ax.legend(loc="upper right", frameon=False, fontsize=8)
        fig.tight_layout()
        _save(fig, "fig07_phase2_mean_and_max.png")
    _caption(7, "In the Colombo run, disagreement is largest at Temperature and Decomposition, and only those two stages reach the threshold.")


def figure8_phase2_delta() -> None:
    print("Figure 8: Phase 2 change from the previous stage", flush=True)
    f = "step2/colombo/results.json"
    r = _colombo()
    delta = [_by_stage(r["phase2"]["delta"])[k] for k in STAGE_KEYS]
    for i, k in enumerate(STAGE_KEYS):
        _src(f"Change, {FULL_NAME[k]}", delta[i], f, f"phase2.delta[{i}].value")

    with plt.rc_context({"hatch.linewidth": 1.0}):
        fig, ax = plt.subplots(figsize=(8, 5.2), dpi=300)
        bars = ax.bar(STAGE_LABELS, delta, color=BLUE, edgecolor=DARK_GREY, linewidth=0.8, width=0.6)
        for bar, v in zip(bars, delta):
            if v < 0:
                bar.set_hatch("//")  # negative bars hatched so the sign shows in black and white
        _label_bars(ax, bars, "{:+.4f}", fontsize=8)
        ax.axhline(0, color=DARK_GREY, linewidth=1.2)
        ax.set_ylim(-0.16, 0.17)
        _style_axes(ax, "Change in average disagreement",
                    "How the average disagreement changes from one stage to the next: Colombo run")
        fig.tight_layout(rect=(0, 0.06, 1, 1))
        fig.text(0.5, 0.02, "Each stage is measured on its own scale, so a negative bar does not mean disagreement was removed.",
                 ha="center", fontsize=8.5)
        _save(fig, "fig08_phase2_change_per_stage.png")
    _caption(8, "The average disagreement rises at Decomposition and Temperature and falls at Transposition and DC, but the stages use different scales, so the bars are not directly comparable.")


def figure9_phase2_hand_check_table() -> None:
    print("Figure 9: PV-DIAL against hand calculation, Phase 2", flush=True)
    f = "step2/colombo/results.json"
    r = _colombo()
    names = [("Average disagreement, ", "mean_nrmsd", HAND_MEAN), ("Highest disagreement, ", "max_nrmsd", HAND_MAX),
             ("Change from previous stage, ", "delta", HAND_DELTA)]
    rows, beyond_5dp = [], []
    for prefix, key, hand in names:
        vals = _by_stage(r["phase2"][key])
        for i, k in enumerate(STAGE_KEYS):
            pv = round(vals[k], 6)
            diff = abs(pv - hand[i])
            match = "Yes" if diff < 1e-9 else ("Yes (rounding)" if diff <= 1.0000001e-6 else "No")
            if diff >= 5e-6:  # more than half a unit in the 5th decimal place
                beyond_5dp.append((prefix + FULL_NAME[k], vals[k], hand[i]))
            _src(f"{prefix}{FULL_NAME[k]}: PV-DIAL / by hand / match", f"{pv:+.6f} / {hand[i]:+.6f} / {match}", f, f"phase2.{key}[{i}].value")
            rows.append([prefix + FULL_NAME[k], f"{pv:.6f}", f"{hand[i]:.6f}", match])
    if beyond_5dp:
        print("    ROWS THAT DIFFER BEYOND 5 DECIMAL PLACES:", flush=True)
        for q, a, b in beyond_5dp:
            print(f"      {q}: PV-DIAL {a:.8f} vs by hand {b:.6f}", flush=True)
    else:
        print("    Rows that differ beyond 5 decimal places: none (all 15 agree to 5 decimal places)", flush=True)

    fig, ax = plt.subplots(figsize=(8.5, 5.4), dpi=300)
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=["Quantity", "PV-DIAL", "By hand", "Match"], loc="upper center",
                     cellLoc="center", colWidths=[0.46, 0.16, 0.16, 0.22])
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.35)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("0.6")
        if row == 0:
            cell.set_facecolor("0.85")
            cell.set_text_props(fontweight="bold")
        elif (row - 1) // 5 % 2 == 1:
            cell.set_facecolor("0.96")
    ax.set_title("PV-DIAL against hand calculation: Colombo run, disagreement across stages", fontsize=10, pad=8)
    _save(fig, "fig09_phase2_hand_check_table.png", tight=True)
    _caption(9, "All 15 Phase 2 values from PV-DIAL agree with the hand calculation; two differ by 0.000001, which comes from rounding the inputs.")


def _oat_vs_pvdial(stage_keys: list, oat: list, pv: list, real_total: float, title: str, filename: str) -> None:
    labels = [FULL_NAME[k] for k in stage_keys] + ["Sum of stages"]
    oat_all = list(oat) + [sum(oat)]
    pv_all = list(pv) + [sum(pv)]
    with plt.rc_context({"hatch.linewidth": 1.0}):
        fig, ax = plt.subplots(figsize=(8, 5), dpi=300)
        x = np.arange(len(labels))
        w = 0.38
        b1 = ax.bar(x - w / 2, oat_all, w, color=ORANGE, edgecolor=DARK_GREY, linewidth=0.8, hatch="//",
                    label="One-at-a-time (OAT)")
        b2 = ax.bar(x + w / 2, pv_all, w, color=BLUE, edgecolor=DARK_GREY, linewidth=0.8, label="PV-DIAL")
        _label_bars(ax, b1, "{:.1f}", fontsize=8)
        _label_bars(ax, b2, "{:.1f}", fontsize=8)
        ax.axhline(real_total, color=DARK_GREY, linewidth=1.3, linestyle="--", label="Real total")
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylim(0, max(oat_all + pv_all + [real_total]) * 1.18)
        _style_axes(ax, "Difference in AC output (RMSD)", title)
        ax.legend(loc="upper left", frameon=False, fontsize=8)
        fig.tight_layout()
        _save(fig, filename)


def figure10_one_pair_oat_vs_pvdial() -> None:
    print("Figure 10: chain-0001 vs chain-0011, OAT against PV-DIAL (averaged game)", flush=True)
    f = "step2/two_stage_pair_v_tables.json"
    d = _load(BASE / "step2" / "two_stage_pair_v_tables.json")
    assert d["pair"] == ["chain-0001", "chain-0011"]
    stages = [Stage[n] for n in d["S"]]
    w = d["w_averaged"]
    v = {frozenset(): 0.0}
    for s in stages:
        v[frozenset({s})] = w[f"v({{{s.name}}})"]
    v[frozenset(stages)] = w["v({" + ",".join(s.name for s in stages) + "})"]
    real_total = v[frozenset(stages)]
    oat = [v[frozenset({s})] for s in stages]
    phi = shapley_values(v, tuple(stages))
    pv = [phi[s] for s in stages]
    # Cross-check against the numbers already printed in evaluation_table.md
    md = (BASE / "evaluation_table.md").read_text()
    m = re.search(r"phi_TEMPERATURE = (\d+\.\d+), phi_DC = (\d+\.\d+)", md)
    assert m and abs(phi[Stage.TEMPERATURE] - float(m.group(1))) < 1e-6 and abs(phi[Stage.DC] - float(m.group(2))) < 1e-6
    for s, o, p in zip(stages, oat, pv):
        _src(f"OAT, {FULL_NAME[s.name]}", o, f, f"w_averaged.v({{{s.name}}})")
        _src(f"PV-DIAL, {FULL_NAME[s.name]}", p, "evaluation_table.md", f"phi_{s.name} (recomputed here from {f} :: w_averaged)")
    _src("Real total", real_total, f, "w_averaged.v({" + ",".join(s.name for s in stages) + "})")
    print("    NOTE: this pair is not in phase3_results.jsonl or the ensemble, so no production phi_final is saved for it. "
          "The PV-DIAL bars use the independent Shapley function applied to the saved averaged table "
          "(the same function matched production phi_final to 6.7e-14 on Colombo pairs A-B and A-C).", flush=True)
    _oat_vs_pvdial([s.name for s in stages], oat, pv, real_total,
                   "One pair, stage by stage: one-at-a-time against PV-DIAL\n(chain-0001 against chain-0011, average of both directions)",
                   "fig10_oat_vs_pvdial_chain0001_chain0011.png")
    _caption(10, "For this pair the one-at-a-time values add up to 25.9, almost twice the real total of 13.7, while the PV-DIAL values add up to the real total.")


def figure11_colombo_ac_oat_vs_pvdial() -> None:
    print("Figure 11: Colombo pair A-C, OAT against PV-DIAL", flush=True)
    f = "step2/colombo/results.json"
    r = _colombo()
    p3 = r["phase3"]["A-C"]
    differing = r["phase1"]["A-C"]["differing_stages"]
    stage_keys = [k for k in STAGE_KEYS if k in differing]
    vab = {e["coalition"]: e["value"] for e in p3["v_ab"]}
    vba = {e["coalition"]: e["value"] for e in p3["v_ba"]}
    phi = _by_stage(p3["phi_final"])
    real_total = p3["rmsd_ab"]
    oat, pv = [], []
    for k in stage_keys:
        a, b = vab[k], vba[k]
        oat.append((a + b) / 2)
        pv.append(phi[k])
        _src(f"OAT, {FULL_NAME[k]} (mean of the two directions)", (a + b) / 2, f, f"phase3.A-C.v_ab[{k}] and v_ba[{k}]")
        _src(f"PV-DIAL, {FULL_NAME[k]}", phi[k], f, "phase3.A-C.phi_final")
    _src("Real total", real_total, f, "phase3.A-C.rmsd_ab")
    print("    Stages shown: only those where the two pipelines use different models (phase1.A-C.differing_stages).", flush=True)
    _oat_vs_pvdial(stage_keys, oat, pv, real_total,
                   "Colombo pair A-C, stage by stage: one-at-a-time against PV-DIAL\n(average of both directions)",
                   "fig11_oat_vs_pvdial_colombo_ac.png")
    _caption(11, "For Colombo pair A-C both methods name Temperature as the largest stage, but the one-at-a-time values add up to 162.3, far above the real total of 95.4, while PV-DIAL adds up to it.")


def figure12_top_stage_agreement() -> None:
    print("Figure 12: how often OAT names the same top stage as PV-DIAL", flush=True)
    f = "step4/phase3_summary.json"
    d = _load(BASE / "step4" / "phase3_summary.json")
    items = [("One-at-a-time (OAT):\nsingle-stage reading", "rank_agreement_singleton_overall"),
             ("One-at-a-time (OAT):\nleave-one-out reading", "rank_agreement_loo_overall")]
    rates, lows, highs = [], [], []
    for _, key in items:
        e = d[key]
        assert e["n"] == 2863 == d["n_eligible"]
        rates.append(e["rate"] * 100)
        lows.append(e["wilson_95"][0] * 100)
        highs.append(e["wilson_95"][1] * 100)
        _src(f"{key} rate (agree {e['agree']} of {e['n']})", e["rate"], f, f"{key}.rate")
        _src(f"{key} interval", f"{e['wilson_95'][0]:.6f} to {e['wilson_95'][1]:.6f}", f, f"{key}.wilson_95")
    yerr = [[r - lo for r, lo in zip(rates, lows)], [hi - r for r, hi in zip(rates, highs)]]
    with plt.rc_context({"hatch.linewidth": 1.0}):
        fig, ax = plt.subplots(figsize=(6.5, 4.8), dpi=300)
        bars = ax.bar([i[0] for i in items], rates, color=ORANGE, edgecolor=DARK_GREY, linewidth=0.8, width=0.5,
                      yerr=yerr, capsize=6, error_kw=dict(ecolor=DARK_GREY, elinewidth=1.3))
        bars[1].set_hatch("//")
        for bar, r, hi in zip(bars, rates, highs):
            ax.annotate(f"{r:.1f} %", (bar.get_x() + bar.get_width() / 2, hi), xytext=(0, 4),
                        textcoords="offset points", ha="center", fontsize=9)
        ax.set_ylim(0, 105)
        _style_axes(ax, "Share of the 2,863 pairs (%)",
                    "How often one-at-a-time names the same top stage as PV-DIAL")
        fig.tight_layout()
        _save(fig, "fig12_oat_same_top_stage.png")
    _caption(12, "Across 2,863 pairs, one-at-a-time names the same top stage as PV-DIAL in 98.8 % of pairs with the single-stage reading and 95.1 % with the leave-one-out reading (bars show the 95 % interval).")


def main_extra() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Colombo results.json: {COLOMBO_RESULTS} (analysis_id {COLOMBO_ID})", flush=True)
    for fn in (figure4_phase1_vs_baseline_a_all_pairs, figure5_colombo_pair_three_methods, figure6_tau_curve_zoom,
               figure7_phase2_mean_max, figure8_phase2_delta, figure9_phase2_hand_check_table,
               figure10_one_pair_oat_vs_pvdial, figure11_colombo_ac_oat_vs_pvdial, figure12_top_stage_agreement):
        fn()
    print(f"Wrote 9 extra figures to {FIGURES_DIR}")


# ---------------------------------------------------------------------------
# Thesis-style set: 12 figures with one look (serif, solid fills, no hatching).
# Blue = PV-DIAL, orange = the comparison method, green = a third series.
# Reads saved outputs only. Files are thesis_NN_*.png; captions.md is written
# beside them. The 3 original greyscale files and the fig04-fig12 files above
# are not touched.
#   python3 -m experiments.evaluation.make_figures --thesis-only
# ---------------------------------------------------------------------------

T_BLUE, T_ORANGE, T_GREEN, T_REF = "#1F5F9E", "#E08A1E", "#2E8B57", "#444444"

THESIS_RC = {
    "font.family": "serif",
    "font.serif": ["Times New Roman", "TeX Gyre Termes", "Liberation Serif", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 10, "axes.titlesize": 11, "axes.labelsize": 10,
    "xtick.labelsize": 10, "ytick.labelsize": 9, "legend.fontsize": 9,
    "axes.linewidth": 0.8, "axes.edgecolor": "#111111",
    "axes.axisbelow": True, "axes.grid": True, "axes.grid.axis": "y",
    "grid.color": "#D9D9D9", "grid.linewidth": 0.5,
    "legend.frameon": False, "savefig.dpi": 300, "savefig.bbox": "tight",
    "figure.figsize": (6.3, 3.9),
}

THESIS_CAPTIONS: dict[str, str] = {}


def _t_save(fig, name: str, caption: str) -> None:
    fig.savefig(FIGURES_DIR / name)
    plt.close(fig)
    THESIS_CAPTIONS[name] = caption
    print(f"    saved {FIGURES_DIR / name}", flush=True)
    print(f"  Caption: {caption}", flush=True)


def _t_labels(ax, xs, heights, fmt: str, line_y: float | None = None, line_lo: float | None = None) -> None:
    """8 pt black value label above each bar (below a negative bar). If a
    reference line would run through a label, the label is lifted above it.
    """
    lo, hi = ax.get_ylim()
    rng = hi - lo
    for x, h in zip(xs, heights):
        if h >= 0:
            y, va = h + 0.012 * rng, "bottom"
            if line_y is not None and y - 0.012 * rng <= line_y <= y + 0.06 * rng:
                y = line_y + 0.012 * rng
        else:
            y, va = h - 0.012 * rng, "top"
        ax.text(x, y, fmt.format(h), ha="center", va=va, fontsize=8, color="black")


def _t_ref(ax, y: float, label: str) -> None:
    ax.axhline(y, color=T_REF, linewidth=1, linestyle="--", label=label, zorder=2)


def thesis_tau_curve(xmax: float, number: int, title: str, filename: str, caption: str) -> None:
    print(f"Thesis figure {number}: threshold curve, x 0 to {xmax}", flush=True)
    f = "step4/tau_band_curve.json"
    d = _load(BASE / "step4" / "tau_band_curve.json")
    grid = np.array(d["tau_grid"])
    band = d["stable_band"]
    outcome1 = np.array(d["outcome1_share_by_tau"])
    same_a = np.array(d["k_eq_min_s_share_by_tau"])
    sel = grid <= xmax + 1e-12
    i93 = int(np.argmin(abs(grid - 0.093)))
    print(f"    {int(sel.sum())} points plotted from {f} :: tau_grid, outcome1_share_by_tau, k_eq_min_s_share_by_tau; stable_band = {band}", flush=True)
    _src("No stage exceeds tau at 0.092", float(outcome1[i93 - 1]) if grid[i93] > 0.0925 else float(outcome1[i93]), f, "outcome1_share_by_tau")
    _src(f"Same stage as Baseline A at {grid[i93]:.3f}", float(same_a[i93]), f, f"k_eq_min_s_share_by_tau[{i93}]")
    with plt.rc_context(THESIS_RC):
        fig, ax = plt.subplots()
        ax.axvspan(band[0], band[1], facecolor="#DDDDDD", edgecolor="none", zorder=0,
                   label=f"Stable range ({band[0]} to {band[1]})")
        ax.plot(grid[sel], outcome1[sel], color=T_BLUE, linewidth=1.8, label="No stage exceeds τ")
        ax.plot(grid[sel], same_a[sel], color=T_ORANGE, linewidth=1.8, linestyle="--", label="Same stage as Baseline A")
        ax.axvline(0.093, color=T_REF, linewidth=1, linestyle=":", label="Threshold (τ = 0.093)")
        ax.set_xlim(0, xmax)
        ax.set_ylim(0, 1)
        ax.set_xlabel("τ")
        ax.set_ylabel("Share of all pairs")
        ax.set_title(title)
        ax.legend(loc="center right")
        _t_save(fig, filename, caption)


def thesis_heatmap() -> None:
    print("Thesis figure 3: PV-DIAL (Phase 1) against Baseline B", flush=True)
    f = "step4/all_pairs_baseline_check.json"
    d = _load(BASE / "step4" / "all_pairs_baseline_check.json")
    table = np.array(d["k_times_b_table"])
    print(f"    {f} :: k_times_b_table (rows = stage named by PV-DIAL, columns = stage named by Baseline B, order {d['stage_order']})", flush=True)
    for i in range(5):
        print("    " + "  ".join(f"{int(v):>9,}" for v in table[i]), flush=True)
    with plt.rc_context(THESIS_RC):
        fig, ax = plt.subplots(figsize=(6.3, 4.6))
        ax.grid(False)
        # vmax above the largest count keeps the darkest cell light enough for black labels
        im = ax.imshow(table, cmap="Blues", vmin=0, vmax=table.max() * 1.6, aspect="auto")
        ax.set_xticks(range(5))
        ax.set_yticks(range(5))
        ax.set_xticklabels(STAGE_LABELS)
        ax.set_yticklabels(STAGE_LABELS)
        ax.set_xlabel("Stage named by Baseline B")
        ax.set_ylabel("Stage named by PV-DIAL (Phase 1)")
        for i in range(5):
            for j in range(5):
                ax.text(j, i, f"{int(table[i, j]):,}", ha="center", va="center", fontsize=8, color="black")
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        cb.set_label("Number of pairs")
        cb.formatter = matplotlib.ticker.FuncFormatter(lambda v, _: f"{int(v):,}")
        cb.update_ticks()
        cb.outline.set_linewidth(0.5)
        ax.set_title("PV-DIAL (Phase 1) against Baseline B (all pairs, τ = 0.093)")
        _t_save(fig, "thesis_03_phase1_vs_baseline_b_heatmap.png",
                "For every pair, the stage PV-DIAL names (rows) against the stage Baseline B names (columns). "
                "The two methods name the same stage for 80.6 % of pairs (the diagonal). The only other group is 286,013 pairs where PV-DIAL names Decomposition and Baseline B names Temperature.")


def thesis_phase1_bars() -> None:
    print("Thesis figure 4: Phase 1 relative to Baseline A, all pairs", flush=True)
    f = "step4/all_pairs_baseline_check.json"
    d = _load(BASE / "step4" / "all_pairs_baseline_check.json")
    shares = [d["k_eq_min_s_share"], d["outcome1_share"], d["informative_rate_part_b_k_gt_mins"]]
    _src("Same stage as Baseline A", shares[0], f, "k_eq_min_s_share")
    _src("No stage exceeds the threshold", shares[1], f, "outcome1_share")
    _src("Later stage than Baseline A", shares[2], f, "informative_rate_part_b_k_gt_mins")
    _src("Differs from Baseline A (sum of the last two)", shares[1] + shares[2], f, "informative_rate")
    _src("Number of pairs", d["n_pairs"], f, "n_pairs")
    heights = [v * 100 for v in shares]
    with plt.rc_context(THESIS_RC):
        fig, ax = plt.subplots()
        ax.set_ylim(0, 60)
        x = np.arange(3)
        ax.bar(x, heights, width=0.5, color=[T_ORANGE, T_GREEN, T_BLUE], linewidth=0)
        _t_labels(ax, x, heights, "{:.1f} %")
        top = 41
        ax.plot([1 - 0.25, 1 - 0.25, 2 + 0.25, 2 + 0.25], [top - 1.5, top, top, top - 1.5], color="#111111", linewidth=0.8)
        ax.text(1.5, top + 0.8, f"PV-DIAL differs from Baseline A: {(shares[1] + shares[2]) * 100:.1f} %",
                ha="center", va="bottom", fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels(["Same stage as\nBaseline A", "No stage exceeds\nthe threshold", "Later stage than\nBaseline A"])
        ax.set_ylabel("Share of all pairs (%)")
        ax.set_title("Phase 1 result relative to Baseline A (2,116,653 pairs, τ = 0.093)")
        _t_save(fig, "thesis_04_phase1_vs_baseline_a.png",
                "Of all 2,116,653 pairs, PV-DIAL names the same stage as Baseline A in 45.8 %. In the other 54.2 % it finds no stage above the threshold (30.3 %) or names a later stage (23.9 %).")


def thesis_colombo_pair() -> None:
    print("Thesis figure 5: Colombo pair A-B, stage named by each method", flush=True)
    f = "step2/colombo/results.json"
    r = _colombo()
    p1 = r["phase1"]["A-B"]
    nrmsd = {m["stage"]: m["nrmsd"] for m in p1["metrics"]}
    tau = p1["tau"]["value"]
    y = [nrmsd[k] for k in STAGE_KEYS]
    for i, k in enumerate(STAGE_KEYS):
        _src(f"nRMSD, {FULL_NAME[k]}", nrmsd[k], f, f"phase1.A-B.metrics[{i}].nrmsd")
    _src("Threshold", tau, f, "phase1.A-B.tau.value")
    pv = p1["k"]
    base_a = baseline_a_stage(frozenset(Stage[n] for n in p1["differing_stages"])).name
    base_b = baseline_b_stage({Stage[k]: v for k, v in nrmsd.items()}).name
    _src("PV-DIAL names", FULL_NAME[pv], f, "phase1.A-B.k")
    _src("Baseline A names", FULL_NAME[base_a], f, "phase1.A-B.differing_stages -> baselines.baseline_a_stage")
    _src("Baseline B names", FULL_NAME[base_b], f, "phase1.A-B.metrics[].nrmsd -> baselines.baseline_b_stage")
    assert pv == base_a, "figure label 'PV-DIAL and Baseline A' needs both methods on the same stage"
    ip, ib = STAGE_KEYS.index(pv), STAGE_KEYS.index(base_b)
    with plt.rc_context(THESIS_RC):
        fig, ax = plt.subplots()
        ax.set_ylim(0, 0.25)
        ax.set_xlim(-0.4, 4.4)
        ax.plot(range(5), y, color="#111111", linewidth=1.5, marker="o", markersize=4, label="nRMSD, pair A–B", zorder=3)
        _t_ref(ax, tau, "Threshold (τ = 0.093)")
        ax.plot([ip], [y[ip]], "o", color=T_BLUE, markersize=10, zorder=4)
        ax.plot([ib], [y[ib]], "o", color=T_ORANGE, markersize=10, zorder=4)
        leader = dict(arrowstyle="-", color="#111111", linewidth=0.6, shrinkA=0, shrinkB=6)
        ax.annotate("PV-DIAL and Baseline A", xy=(ip, y[ip]), xytext=(ip + 0.25, y[ip] + 0.075), ha="left", va="bottom", arrowprops=leader)
        ax.annotate("Baseline B (largest rise)", xy=(ib, y[ib]), xytext=(ib + 0.3, y[ib] + 0.06), ha="left", va="bottom", arrowprops=leader)
        ax.set_xticks(range(5))
        ax.set_xticklabels(STAGE_LABELS)
        ax.set_ylabel("nRMSD")
        ax.set_title("Stage identified by each method (Colombo pair A–B)")
        ax.legend(loc="center right")
        _t_save(fig, "thesis_05_colombo_ab_stage_named.png",
                "For Colombo pair A–B, PV-DIAL and Baseline A both name Decomposition, the first stage above the threshold. Baseline B names Temperature, where the single-step rise is largest.")


def _t_grouped_bars(stage_keys, a_vals, b_vals, a_label, b_label, a_color, b_color, ylabel, title, filename, caption,
                    ref_y=None, ref_label=None, fmt="{:.3f}", ylim=None, legend_loc="upper left", ref_in_legend_first=True,
                    xlabels=None) -> None:
    n = len(stage_keys)
    xs = np.arange(n)
    with plt.rc_context(THESIS_RC):
        fig, ax = plt.subplots()
        if ylim:
            ax.set_ylim(*ylim)
        ax.bar(xs - 0.18, a_vals, 0.36, color=a_color, linewidth=0, label=a_label)
        ax.bar(xs + 0.18, b_vals, 0.36, color=b_color, linewidth=0, label=b_label)
        if ref_y is not None:
            _t_ref(ax, ref_y, ref_label)
        _t_labels(ax, xs - 0.18, a_vals, fmt, line_y=ref_y)
        _t_labels(ax, xs + 0.18, b_vals, fmt, line_y=ref_y)
        ax.set_xticks(xs)
        ax.set_xticklabels(xlabels or [FULL_NAME[k] for k in stage_keys])
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(loc=legend_loc)
        _t_save(fig, filename, caption)


def thesis_phase2_mean_max() -> None:
    print("Thesis figure 6: Phase 2 mean and maximum nRMSD", flush=True)
    f = "step2/colombo/results.json"
    r = _colombo()
    mean = [_by_stage(r["phase2"]["mean_nrmsd"])[k] for k in STAGE_KEYS]
    mx = [_by_stage(r["phase2"]["max_nrmsd"])[k] for k in STAGE_KEYS]
    tau = r["phase1"]["A-B"]["tau"]["value"]
    for i, k in enumerate(STAGE_KEYS):
        _src(f"Mean, {FULL_NAME[k]}", mean[i], f, f"phase2.mean_nrmsd[{i}].value")
        _src(f"Maximum, {FULL_NAME[k]}", mx[i], f, f"phase2.max_nrmsd[{i}].value")
    _src("Threshold", tau, f, "phase1.A-B.tau.value")
    _t_grouped_bars(STAGE_KEYS, mean, mx, "Mean of the three pairs", "Maximum of the three pairs", T_BLUE, T_GREEN,
                    "nRMSD", "Mean and maximum nRMSD by stage (Colombo run)", "thesis_06_phase2_mean_max.png",
                    "For the Colombo run, the mean and the maximum of the three pairs' nRMSD at each stage. Only Decomposition and Temperature are above the threshold.",
                    ref_y=tau, ref_label="Threshold (τ = 0.093)", ylim=(0, 0.25), legend_loc="center right")


def thesis_phase2_change() -> None:
    print("Thesis figure 7: change in mean nRMSD between stages", flush=True)
    f = "step2/colombo/results.json"
    r = _colombo()
    delta = [_by_stage(r["phase2"]["delta"])[k] for k in STAGE_KEYS]
    for i, k in enumerate(STAGE_KEYS):
        _src(f"Change, {FULL_NAME[k]}", delta[i], f, f"phase2.delta[{i}].value")
    with plt.rc_context(THESIS_RC):
        fig, ax = plt.subplots()
        ax.set_ylim(-0.16, 0.17)
        xs = np.arange(5)
        ax.bar(xs, delta, width=0.5, color=T_BLUE, linewidth=0)
        ax.axhline(0, color=T_REF, linewidth=1, linestyle="--")
        _t_labels(ax, xs, delta, "{:+.4f}")
        ax.set_xticks(xs)
        ax.set_xticklabels(STAGE_LABELS)
        ax.set_ylabel("Change in mean nRMSD")
        ax.set_title("Change in mean nRMSD between stages (Colombo run)")
        _t_save(fig, "thesis_07_phase2_change.png",
                "The change in the mean nRMSD from one stage to the next in the Colombo run. "
                "Each stage is normalised by its own range, so a negative value does not mean disagreement was removed.")


def thesis_phase2_table() -> None:
    print("Thesis figure 8: Phase 2 table, PV-DIAL against hand calculation", flush=True)
    f = "step2/colombo/results.json"
    r = _colombo()
    groups = [("Mean nRMSD", "mean_nrmsd", HAND_MEAN), ("Maximum nRMSD", "max_nrmsd", HAND_MAX),
              ("Change from previous stage", "delta", HAND_DELTA)]
    rows = []  # (kind, cells)
    beyond = []
    for title, key, hand in groups:
        rows.append(("group", [title]))
        vals = _by_stage(r["phase2"][key])
        for i, k in enumerate(STAGE_KEYS):
            pv = round(vals[k], 6)
            diff = abs(pv - hand[i])
            match = "Yes" if diff < 1e-9 else ("Yes (rounding)" if diff <= 1.0000001e-6 else "No")
            if diff >= 5e-6:
                beyond.append((title, k, vals[k], hand[i]))
            _src(f"{title}, {FULL_NAME[k]}: PV-DIAL / by hand / match", f"{pv:.6f} / {hand[i]:.6f} / {match}", f, f"phase2.{key}[{i}].value")
            rows.append(("row", [FULL_NAME[k], f"{pv:.6f}", f"{hand[i]:.6f}", match]))
    print("    Rows differing beyond 5 decimal places: " + (str(beyond) if beyond else "none"), flush=True)
    n = len(rows) + 1
    with plt.rc_context(THESIS_RC):
        fig, ax = plt.subplots(figsize=(6.3, 4.9))
        ax.axis("off")
        ax.set_xlim(0, 1)
        ax.set_ylim(n, -0.2)
        cx_stage, cx_pv, cx_hand, cx_match = 0.0, 0.55, 0.74, 0.80
        ax.text(cx_stage, 0.5, "Stage", fontweight="bold", va="center")
        ax.text(cx_pv, 0.5, "PV-DIAL", fontweight="bold", va="center", ha="right")
        ax.text(cx_hand, 0.5, "By hand", fontweight="bold", va="center", ha="right")
        ax.text(cx_match, 0.5, "Match", fontweight="bold", va="center", ha="left")
        ax.hlines(0, 0, 1, color="#111111", linewidth=1.2)
        ax.hlines(1, 0, 1, color="#111111", linewidth=0.7)
        for i, (kind, cells) in enumerate(rows, start=1):
            yc = i + 0.5
            if kind == "group":
                ax.text(cx_stage, yc, cells[0], fontweight="bold", va="center")
            else:
                ax.text(cx_stage + 0.03, yc, cells[0], va="center")
                ax.text(cx_pv, yc, cells[1], va="center", ha="right")
                ax.text(cx_hand, yc, cells[2], va="center", ha="right")
                ax.text(cx_match, yc, cells[3], va="center", ha="left")
        ax.hlines(n, 0, 1, color="#111111", linewidth=1.2)
        ax.set_title("PV-DIAL against hand calculation (Colombo run, Phase 2)")
        _t_save(fig, "thesis_08_phase2_hand_check_table.png",
                "PV-DIAL's Phase 2 values for the Colombo run next to the same values worked out by hand. "
                "All 15 agree to 5 decimal places; two differ by 0.000001 because the hand calculation starts from rounded inputs.")


def _t_attribution(stage_keys, oat, pv, total, title, filename, caption) -> None:
    n = len(stage_keys)
    xs = np.arange(n)
    sum_x = n + 0.35
    oat_sum, pv_sum = sum(oat), sum(pv)
    top = max(oat + pv + [oat_sum, pv_sum, total]) * 1.25
    with plt.rc_context(THESIS_RC):
        fig, ax = plt.subplots()
        ax.set_ylim(0, top)
        ax.bar(xs - 0.18, pv, 0.36, color=T_BLUE, linewidth=0, label="PV-DIAL (Shapley)")
        ax.bar(xs + 0.18, oat, 0.36, color=T_ORANGE, linewidth=0, label="One-at-a-time (OAT)")
        ax.bar([sum_x - 0.18], [pv_sum], 0.36, color=T_BLUE, linewidth=0)
        ax.bar([sum_x + 0.18], [oat_sum], 0.36, color=T_ORANGE, linewidth=0)
        ax.axvline(n - 0.15, color="#AAAAAA", linewidth=0.6, zorder=1)
        _t_ref(ax, total, f"Measured total ({total:.2f})")
        _t_labels(ax, list(xs - 0.18) + [sum_x - 0.18], list(pv) + [pv_sum], "{:.1f}", line_y=total)
        _t_labels(ax, list(xs + 0.18) + [sum_x + 0.18], list(oat) + [oat_sum], "{:.1f}", line_y=total)
        ax.set_xticks(list(xs) + [sum_x])
        ax.set_xticklabels([FULL_NAME[k] for k in stage_keys] + ["Sum of stages"])
        ax.set_ylabel("Contribution to AC RMSD")
        ax.set_title(title)
        ax.legend(loc="upper left")
        _t_save(fig, filename, caption)


def thesis_attribution_pair() -> None:
    print("Thesis figure 9: chain-0001 against chain-0011", flush=True)
    f = "step2/two_stage_pair_v_tables.json"
    d = _load(BASE / "step2" / "two_stage_pair_v_tables.json")
    assert d["pair"] == ["chain-0001", "chain-0011"]
    stages = [Stage[n] for n in d["S"]]
    w = d["w_averaged"]
    v = {frozenset(): 0.0}
    for st in stages:
        v[frozenset({st})] = w[f"v({{{st.name}}})"]
    v[frozenset(stages)] = w["v({" + ",".join(st.name for st in stages) + "})"]
    total = v[frozenset(stages)]
    oat = [v[frozenset({st})] for st in stages]
    phi = shapley_values(v, tuple(stages))
    pv = [phi[st] for st in stages]
    md = (BASE / "evaluation_table.md").read_text()
    m = re.search(r"phi_TEMPERATURE = (\d+\.\d+), phi_DC = (\d+\.\d+)", md)
    assert m and abs(phi[Stage.TEMPERATURE] - float(m.group(1))) < 1e-6 and abs(phi[Stage.DC] - float(m.group(2))) < 1e-6
    for st, o, p in zip(stages, oat, pv):
        _src(f"OAT, {FULL_NAME[st.name]}", o, f, f"w_averaged.v({{{st.name}}})")
        _src(f"PV-DIAL, {FULL_NAME[st.name]}", p, "evaluation_table.md", f"phi_{st.name} (recomputed from {f} :: w_averaged)")
    _src("Measured total", total, f, "w_averaged.v({" + ",".join(st.name for st in stages) + "})")
    print("    NOTE: this pair is not in phase3_results.jsonl or the 100-chain ensemble; PV-DIAL bars are the independent Shapley function on the saved averaged table.", flush=True)
    _t_attribution([st.name for st in stages], oat, pv, total,
                   "Stage attribution for pair chain-0001 and chain-0011: PV-DIAL and OAT",
                   "thesis_09_attribution_chain0001_chain0011.png",
                   "For one pair of pool chains, the contribution of each stage to the AC RMSD under PV-DIAL and under one-at-a-time (OAT). "
                   "The PV-DIAL values add up to the measured total (13.69); the OAT values add up to 25.93, almost twice as much.")


def thesis_attribution_colombo() -> None:
    print("Thesis figure 10: Colombo pair A-C", flush=True)
    f = "step2/colombo/results.json"
    r = _colombo()
    p3 = r["phase3"]["A-C"]
    stage_keys = [k for k in STAGE_KEYS if k in r["phase1"]["A-C"]["differing_stages"]]
    vab = {e["coalition"]: e["value"] for e in p3["v_ab"]}
    vba = {e["coalition"]: e["value"] for e in p3["v_ba"]}
    phi = _by_stage(p3["phi_final"])
    oat = [(vab[k] + vba[k]) / 2 for k in stage_keys]
    pv = [phi[k] for k in stage_keys]
    total = p3["rmsd_ab"]
    for k, o, p in zip(stage_keys, oat, pv):
        _src(f"OAT, {FULL_NAME[k]} (mean of the two directions)", o, f, f"phase3.A-C.v_ab[{k}], v_ba[{k}]")
        _src(f"PV-DIAL, {FULL_NAME[k]}", p, f, "phase3.A-C.phi_final")
    _src("Measured total", total, f, "phase3.A-C.rmsd_ab")
    _t_attribution(stage_keys, oat, pv, total, "Stage attribution for Colombo pair A–C: PV-DIAL and OAT",
                   "thesis_10_attribution_colombo_ac.png",
                   "For Colombo pair A–C, the contribution of each stage to the AC RMSD under PV-DIAL and under one-at-a-time (OAT). "
                   "Both name Temperature as the largest stage, but the OAT values add up to 162.3, well above the measured total of 95.4 that the PV-DIAL values add up to.")


def thesis_gap_histograms() -> None:
    print("Thesis figure 11: attribution gap histograms", flush=True)
    f = "step4/phase3_results.jsonl"
    recs = [json.loads(l) for l in open(BASE / "step4" / "phase3_results.jsonl") if l.strip()]
    single = np.array([r["gap_singleton"] for r in recs if _finite(r["gap_singleton"])])
    loo = np.array([r["gap_loo"] for r in recs if _finite(r["gap_loo"])])
    sm = _load(BASE / "step4" / "phase3_summary.json")
    for label, arr, key in (("single-stage", single, "gap_singleton"), ("leave-one-out", loo, "gap_loo")):
        counts, _ = np.histogram(arr, bins=np.linspace(0, 1.8, 37))
        _src(f"Pairs, {label}", int(arr.size), f, key)
        _src(f"Median, {label}", float(np.median(arr)), f, f"{key} (median); step4/phase3_summary.json :: {key}.median = {sm[key]['median']:.6f}")
        print(f"    bin counts ({label}, 36 bins from 0 to 1.8): {counts.tolist()}", flush=True)
        assert abs(np.median(arr) - sm[key]["median"]) < 1e-9
    bins = np.linspace(0, 1.8, 37)
    with plt.rc_context(THESIS_RC):
        fig, axes = plt.subplots(1, 2, sharey=True, figsize=(6.3, 3.6))
        for ax, arr, color, name in ((axes[0], single, T_ORANGE, "OAT single-stage"), (axes[1], loo, T_GREEN, "OAT leave-one-out")):
            ax.hist(arr, bins=bins, color=color, edgecolor="white", linewidth=0.5)
            med = float(np.median(arr))
            ax.axvline(med, color=T_REF, linewidth=1, linestyle="--")
            ax.set_xlim(0, 1.8)
            ax.set_xlabel("Attribution gap")
            ax.set_title(name, fontsize=10)
            ax.text(med + 0.04, 0.97, f"Median {med:.2f}", transform=ax.get_xaxis_transform(), ha="left", va="top", fontsize=9)
        axes[0].set_ylim(0, 450)
        axes[0].set_ylabel("Number of pairs")
        fig.suptitle("Attribution gap of OAT (2,863 eligible pairs)", fontsize=11, y=1.0)
        fig.tight_layout()
        _t_save(fig, "thesis_11_oat_gap_histograms.png",
                "How far the one-at-a-time (OAT) values are from the measured total, for each of the 2,863 eligible pairs. "
                "A gap of 0 means the OAT values add up to the total. The median gap is 0.42 for the single-stage reading and 0.30 for the leave-one-out reading.")


def thesis_top_stage_agreement() -> None:
    print("Thesis figure 12: agreement on the leading stage", flush=True)
    f = "step4/phase3_summary.json"
    d = _load(BASE / "step4" / "phase3_summary.json")
    items = [("Single-stage reading", "rank_agreement_singleton_overall", T_ORANGE),
             ("Leave-one-out reading", "rank_agreement_loo_overall", T_GREEN)]
    with plt.rc_context(THESIS_RC):
        fig, ax = plt.subplots(figsize=(5.2, 3.9))
        for i, (label, key, color) in enumerate(items):
            e = d[key]
            assert e["n"] == 2863
            rate = e["rate"] * 100
            lo, hi = e["wilson_95"][0] * 100, e["wilson_95"][1] * 100
            _src(f"{label} rate (agree {e['agree']} of {e['n']})", e["rate"], f, f"{key}.rate")
            _src(f"{label} interval", f"{e['wilson_95'][0]:.6f} to {e['wilson_95'][1]:.6f}", f, f"{key}.wilson_95")
            ax.errorbar([i], [rate], yerr=[[rate - lo], [hi - rate]], fmt="o", color=color, ecolor=color, markersize=7,
                        elinewidth=1.5, capsize=5, capthick=1.5)
            ax.text(i + 0.12, rate, f"{rate:.1f} %", ha="left", va="center", fontsize=9)
        ax.set_xlim(-0.6, 1.6)
        ax.set_ylim(90, 100)
        ax.set_xticks([0, 1])
        ax.set_xticklabels([i[0] for i in items])
        ax.set_ylabel("Pairs with the same leading stage (%)")
        ax.set_title("Agreement between OAT and PV-DIAL on the leading stage")
        _t_save(fig, "thesis_12_top_stage_agreement.png",
                "How often one-at-a-time (OAT) names the same leading stage as PV-DIAL, over 2,863 pairs: 98.8 % with the single-stage reading and 95.1 % with the leave-one-out reading. "
                "Vertical lines show the 95 % Wilson interval.")


def main_thesis() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Colombo results.json: {COLOMBO_RESULTS} (analysis_id {COLOMBO_ID})", flush=True)
    thesis_tau_curve(1.0, 1, "Sensitivity of Phase 1 results to τ (all pairs)", "thesis_01_tau_sensitivity_full.png",
                     "Share of all pairs with no stage above τ (solid) and share where PV-DIAL names the same stage as Baseline A (dashed), for τ from 0 to 1. "
                     "The grey band marks the stable range, 0.088 to 0.098, and the dotted line marks the default τ of 0.093.")
    thesis_tau_curve(0.3, 2, "Sensitivity of Phase 1 results to τ (0 to 0.3)", "thesis_02_tau_sensitivity_0_to_0.3.png",
                     "The same curves as the previous figure, enlarged for τ from 0 to 0.3, where they change. Both stay nearly flat inside the stable range around the default τ of 0.093.")
    thesis_heatmap()
    thesis_phase1_bars()
    thesis_colombo_pair()
    thesis_phase2_mean_max()
    thesis_phase2_change()
    thesis_phase2_table()
    thesis_attribution_pair()
    thesis_attribution_colombo()
    thesis_gap_histograms()
    thesis_top_stage_agreement()
    lines = ["# Figure captions", ""]
    for name in sorted(THESIS_CAPTIONS):
        lines += [f"**{name}**", "", THESIS_CAPTIONS[name], ""]
    (FIGURES_DIR / "captions.md").write_text("\n".join(lines))
    print(f"Wrote {len(THESIS_CAPTIONS)} thesis figures and captions.md to {FIGURES_DIR}")


if __name__ == "__main__":
    import sys

    if "--thesis-only" in sys.argv:
        main_thesis()
    else:
        if "--extra-only" not in sys.argv:
            main()
        main_extra()
        main_thesis()
