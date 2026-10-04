"""Altair charts for page 4. Each one is drawn from the same numbers as the table beside it, and none relies
on colour alone: a heavy outline and the words 'over τ' carry the meaning in the heatmap, and bars over τ also
carry an outline."""

from __future__ import annotations

import altair as alt
import pandas as pd

from app import wording
from app.analysis_logic import PairView, fmt_nrmsd

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


__all__ = ["heat_frame", "heatmap", "stage_bars", "stage_bars_frame"]
