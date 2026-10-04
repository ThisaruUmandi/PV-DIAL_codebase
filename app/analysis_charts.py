"""Altair charts for page 4. Each one is drawn from the same numbers as the table beside it, and none relies
on colour alone: a heavy outline and the words 'over τ' carry the meaning in the heatmap, and bars over τ also
carry an outline."""

from __future__ import annotations

import altair as alt
import pandas as pd

from app import wording
from app.analysis_logic import PHI_UNIT, PairView, Phase2View, Phase3View, fmt_nrmsd, fmt_watts

_INK = "#1F2328"
_TEAL = "#1F5F6B"
_PALE = "#EEF3F3"
_MONO = "IBM Plex Mono"
_AXIS = {"labelFont": _MONO, "labelColor": "#5B6168", "titleColor": "#3E444A"}


def heat_frame(views: list[PairView]) -> pd.DataFrame:
    """One row per pair and stage: the number as text and whether it is over τ. The heatmap, its outline
    layer and the table beside it all read these values."""
    rows = []
    for view in views:
        for index, stage in enumerate(view.nrmsd):
            value = view.nrmsd[stage]
            rows.append(
                {
                    "pair": view.label,
                    "stage": wording.P4_HEAT_AXIS[index],
                    "nrmsd": value,
                    "text": fmt_nrmsd(value),
                    "over": stage in view.over,
                    "over_text": wording.P4_OVER_TAU if stage in view.over else "",
                }
            )
    return pd.DataFrame(rows)


def heatmap(views: list[PairView]) -> alt.Chart:
    frame = heat_frame(views)
    pairs = [view.label for view in views]
    x = alt.X("stage:N", title=None, scale=alt.Scale(domain=list(wording.P4_HEAT_AXIS)),
              axis=alt.Axis(orient="top", labelAngle=0, labelFont="IBM Plex Sans", labelColor=_INK, labelPadding=6,
                            labelOverlap=False, labelLimit=0, labelFontSize=10))
    y = alt.Y("pair:N", title=None, scale=alt.Scale(domain=pairs),
              axis=alt.Axis(labelFont="IBM Plex Sans", labelColor=_INK, labelPadding=6))
    computed = frame.dropna(subset=["nrmsd"])
    top = float(computed["nrmsd"].max()) if len(computed) else 1.0
    base = alt.Chart(computed).encode(x=x, y=y)
    cells = base.mark_rect(stroke="#FFFFFF", strokeWidth=1).encode(
        color=alt.Color("nrmsd:Q", scale=alt.Scale(domain=[0, top], range=[_PALE, _TEAL]), legend=None)
    )
    ink = alt.condition(alt.datum.nrmsd > 0.55 * top, alt.value("#FFFFFF"), alt.value(_INK))
    values = base.mark_text(font=_MONO, fontSize=13, dy=-5).encode(text="text:N", color=ink)
    over = base.transform_filter(alt.datum.over).mark_text(font="IBM Plex Sans", fontSize=11, dy=11, fontWeight="bold").encode(
        text="over_text:N", color=ink
    )
    outline = (
        alt.Chart(computed[computed["over"]])
        .mark_rect(fill=None, stroke=_INK, strokeWidth=3.5)
        .encode(x=x, y=y)
    )
    layers = [cells, values, over, outline]
    missing = frame[frame["nrmsd"].isna()]
    if len(missing):
        layers.append(
            alt.Chart(missing).mark_text(font="IBM Plex Sans", fontSize=11, color="#5B6168").encode(
                x=x, y=y, text=alt.value(wording.P4_NA)
            )
        )
    return alt.layer(*layers).properties(height=60 * len(pairs) + 24).configure(background="#FFFFFF").configure_view(stroke=None)


def stage_bars_frame(rows: list[dict], tau: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "stage": wording.P4_HEAT_AXIS[index],
                "nrmsd": row["nrmsd"],
                "text": row["text"],
                "over": row["over"],
                "tau": tau,
            }
            for index, row in enumerate(rows)
        ]
    )


def stage_bars(rows: list[dict], tau: float, tau_label: str) -> alt.Chart:
    """nRMSD per stage for one pair, with τ as a vertical line. Bars over τ are outlined."""
    frame = stage_bars_frame(rows, tau).dropna(subset=["nrmsd"])
    domain = list(wording.P4_HEAT_AXIS)
    y = alt.Y("stage:N", title=None, scale=alt.Scale(domain=domain),
              axis=alt.Axis(labelFont="IBM Plex Sans", labelColor=_INK))
    x = alt.X("nrmsd:Q", title="nRMSD (unitless)", axis=alt.Axis(grid=True, **_AXIS))
    bars = (
        alt.Chart(frame)
        .mark_bar(color=_TEAL, size=18)
        .encode(
            y=y, x=x,
            stroke=alt.condition(alt.datum.over, alt.value(_INK), alt.value("transparent")),
            strokeWidth=alt.condition(alt.datum.over, alt.value(3), alt.value(0)),
        )
    )
    labels = alt.Chart(frame).mark_text(align="left", dx=6, font=_MONO, fontSize=12, color=_INK).encode(
        y=y, x=x, text="text:N"
    )
    rule = alt.Chart(pd.DataFrame({"tau": [tau], "label": [tau_label]})).mark_rule(
        color=_INK, strokeWidth=2, strokeDash=[5, 3]
    ).encode(x="tau:Q")
    tag = alt.Chart(pd.DataFrame({"tau": [tau], "label": [f"τ = {tau_label}"]})).mark_text(
        align="left", dx=4, dy=-4, baseline="bottom", font=_MONO, fontSize=11, color=_INK
    ).encode(x="tau:Q", text="label:N", y=alt.value(0))
    return (
        alt.layer(bars, rule, labels, tag).properties(height=34 * len(domain) + 40)
        .configure(background="#FFFFFF").configure_view(stroke="#E6E1D7")
        .configure_axis(gridColor="#EEEAE2", domainColor="#C9C3B7", tickColor="#C9C3B7")
    )


# Each pair has its own colour, dash and marker, different from the pipeline look on page 3 (A, B, C).
_PAIR_STYLE = {
    "A-B": ("#2B5D8A", [1, 0], "diamond"),
    "A-C": ("#8A4F7D", [10, 5], "cross"),
    "B-C": ("#5B6168", [12, 3, 2, 3], "triangle-down"),
}


def propagation_frame(view: Phase2View) -> pd.DataFrame:
    """One row per pair and stage: what the line chart draws, and what the table under it prints."""
    return pd.DataFrame(
        [
            {
                "pair": wording.P4_PAIR.format(a=key[0], b=key[2]),
                "stage": wording.P4_HEAT_AXIS[index],
                "nrmsd": view.pairs[key][stage],
                "text": fmt_nrmsd(view.pairs[key][stage]),
            }
            for key in view.pair_labels
            for index, stage in enumerate(view.pairs[key])
        ]
    )


def propagation_chart(view: Phase2View, tau: float, tau_label: str) -> alt.Chart:
    """nRMSD by stage, one line per pair (colour, dash and marker all differ), with τ as a horizontal line."""
    frame = propagation_frame(view)
    names = [wording.P4_PAIR.format(a=key[0], b=key[2]) for key in view.pair_labels]
    scale = {
        "color": alt.Scale(domain=names, range=[_PAIR_STYLE[k][0] for k in view.pair_labels]),
        "dash": alt.Scale(domain=names, range=[_PAIR_STYLE[k][1] for k in view.pair_labels]),
        "shape": alt.Scale(domain=names, range=[_PAIR_STYLE[k][2] for k in view.pair_labels]),
    }
    x = alt.X("stage:N", title=None, scale=alt.Scale(domain=list(wording.P4_HEAT_AXIS)),
              axis=alt.Axis(labelAngle=0, labelFont="IBM Plex Sans", labelColor=_INK, labelOverlap=False, labelFontSize=11))
    y = alt.Y("nrmsd:Q", title="nRMSD (unitless)", axis=alt.Axis(grid=True, **_AXIS))
    legend = alt.Legend(title=None, symbolType="stroke", symbolStrokeWidth=3, labelColor="#3E444A")
    line = alt.Chart(frame).mark_line(strokeWidth=2.5).encode(
        x=x, y=y, color=alt.Color("pair:N", scale=scale["color"], legend=legend),
        strokeDash=alt.StrokeDash("pair:N", scale=scale["dash"], legend=None),
    )
    points = alt.Chart(frame).mark_point(filled=True, size=70, opacity=1).encode(
        x=x, y=y, color=alt.Color("pair:N", scale=scale["color"], legend=None),
        shape=alt.Shape("pair:N", scale=scale["shape"], legend=None),
    )
    rule = alt.Chart(pd.DataFrame({"tau": [tau]})).mark_rule(color=_INK, strokeWidth=2, strokeDash=[5, 3]).encode(y="tau:Q")
    tag = alt.Chart(pd.DataFrame({"tau": [tau], "label": [f"τ = {tau_label}"]})).mark_text(
        align="center", dy=-8, font=_MONO, fontSize=11, color=_INK
    ).encode(y="tau:Q", text="label:N", x=alt.datum(wording.P4_HEAT_AXIS[1]))
    return (
        alt.layer(line, points, rule, tag).properties(height=300)
        .configure(background="#FFFFFF").configure_view(stroke="#E6E1D7")
        .configure_axis(gridColor="#EEEAE2", domainColor="#C9C3B7", tickColor="#C9C3B7")
    )


def waterfall_frame(view: Phase3View) -> pd.DataFrame:
    """The waterfall's own data: each stage bar runs from where the last one ended to that point plus its φ
    final, so a negative φ gives a bar that goes down; the last bar is RMSD(A,B) as stored."""
    a, b = view.pair
    rows, running = [], 0.0
    for row in view.rows:
        start, end = running, running + row.phi_final
        rows.append(
            {
                "stage": row.label.split(" · ", 1)[1],
                "start": start, "end": end, "value": row.phi_final,
                "text": wording.P4_P3_BAR_SAME if row.same_model else fmt_watts(row.phi_final),
                "kind": "stage",
            }
        )
        running = end
    total = wording.P4_P3_TOTAL_BAR.format(a=a, b=b)
    rows.append({"stage": total, "start": 0.0, "end": view.rmsd_ab, "value": view.rmsd_ab, "text": fmt_watts(view.rmsd_ab), "kind": "total"})
    return pd.DataFrame(rows)


def waterfall(view: Phase3View) -> alt.Chart:
    """Stage bars that step up or down, then a dark bar for RMSD(A,B). Every bar prints its signed value."""
    frame = waterfall_frame(view)
    order = list(frame["stage"])
    x = alt.X("stage:N", title=None, scale=alt.Scale(domain=order),
              axis=alt.Axis(labelAngle=0, labelFont="IBM Plex Sans", labelColor=_INK, labelOverlap=False, labelFontSize=11))
    low = min(0.0, float(frame[["start", "end"]].min().min()))
    high = max(0.0, float(frame[["start", "end"]].max().max()))
    room = (high - low) * 0.14 or 1.0  # space for the value printed on the tallest and the lowest bar
    y = alt.Y(
        "start:Q", title=wording.P4_P3_AXIS.format(unit=PHI_UNIT),
        scale=alt.Scale(domain=[low - (room if low < 0 else 0.0), high + room], nice=False),
        axis=alt.Axis(grid=True, **_AXIS),
    )
    bars = alt.Chart(frame).mark_bar(size=46).encode(
        x=x, y=y, y2="end:Q",
        color=alt.condition(alt.datum.kind == "total", alt.value(_INK), alt.value(_TEAL)),
    )
    above = alt.Chart(frame).transform_filter(alt.datum.value >= 0).mark_text(
        font=_MONO, fontSize=12, color=_INK, baseline="bottom", dy=-4
    ).encode(x=x, y="end:Q", text="text:N")
    below = alt.Chart(frame).transform_filter(alt.datum.value < 0).mark_text(
        font=_MONO, fontSize=12, color=_INK, baseline="top", dy=4
    ).encode(x=x, y="end:Q", text="text:N")
    zero = alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(color="#C9C3B7").encode(y="zero:Q")
    return (
        alt.layer(zero, bars, above, below).properties(height=280)
        .configure(background="#FFFFFF").configure_view(stroke="#E6E1D7")
        .configure_axis(gridColor="#EEEAE2", domainColor="#C9C3B7", tickColor="#C9C3B7")
    )


__all__ = [
    "heat_frame",
    "heatmap",
    "propagation_chart",
    "propagation_frame",
    "stage_bars",
    "stage_bars_frame",
    "waterfall",
    "waterfall_frame",
]
