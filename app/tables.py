"""HTML tables shared by page 4, the Report page and the downloadable report, so one number is written by one
function wherever it appears. Every cell is escaped here; callers insert the result as it is."""

from __future__ import annotations

from html import escape

from app import analysis_logic, components, wording


def tip(text: str, hint: str) -> str:
    """A word with its plain-words hint (a tooltip on the page, a title attribute in the file)."""
    return f'<span class="pv-tip" title="{escape(hint)}">{escape(text)}</span>'


def heat_table_html(views) -> str:
    """The pair × stage nRMSD values (the table beside the map): the over-τ tag before the number, one line,
    every number right-aligned, so the values survive without the chart."""
    head = "".join(f"<th class='pv-num'>{escape(view.label)}</th>" for view in views)
    rows = []
    for index, stage in enumerate(analysis_logic.STAGES):
        cells = []
        for view in views:
            value = view.nrmsd[stage]
            if value is None:
                cells.append(f'<td class="pv-na">{escape(wording.P4_NA)}</td>')
                continue
            mark = components.over_tau_mark() if stage in view.over else ""
            cells.append(
                f'<td class="pv-num pv-nowrap">{mark}<span class="pv-mono">{analysis_logic.fmt_nrmsd(value)}</span></td>'
            )
        rows.append(f"<tr><td>{escape(wording.P4_HEAT_AXIS[index])}</td>{''.join(cells)}</tr>")
    return (
        '<table class="pv-stage-table"><thead><tr>'
        f'<th>{escape(wording.P4_COL_STAGE)}</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


def phase2_table_html(view, rows) -> str:
    """Stage × the three pairs, then mean, max and Δ (the Phase 2 table), with its one-line note."""
    pair_heads = "".join(
        f"<th class='pv-num'>{escape(wording.P4_PAIR.format(a=k[0], b=k[2]))}</th>" for k in view.pair_labels
    )
    body = "".join(
        f"<tr><td>{escape(row['label'])}</td>"
        + "".join(
            f"<td class='pv-num pv-mono'>{escape(text)}</td>"
            for text in (*row["pairs"], row["mean"], row["max"], row["delta"])
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<table class="pv-stage-table"><thead><tr>'
        f"<th>{escape(wording.P4_P2_STAGE)}</th>{pair_heads}"
        f"<th class='pv-num'>{escape(wording.P4_P2_COL_MEAN)}</th><th class='pv-num'>{escape(wording.P4_P2_COL_MAX)}</th>"
        f"<th class='pv-num'>{escape(wording.P4_P2_COL_DELTA)}</th></tr></thead><tbody>{body}</tbody></table>"
        f'<p class="pv-note-line" style="margin-top:8px">{escape(wording.P4_P2_NOTE)}</p>'
    )


def _phase3_row_cells(view, row, columns) -> str:
    if row.same_model:  # the stored value stays 0.0; the page says why there is nothing to show
        return (
            f"<tr><td>{escape(row.label)}</td>"
            f"<td colspan='{columns}' class='pv-same'>{escape(wording.SAME_MODEL)}</td></tr>"
        )
    return ""


def phase3_table_html(view, hint_phi: str = wording.HELP_PHI) -> str:
    """The Phase 3 table of page 4: φ A→B, φ B→A, φ final and share, stage by stage."""
    a, b = view.pair
    unit = analysis_logic.PHI_UNIT
    head = (
        f"<th>{escape(wording.P4_COL_STAGE)}</th>"
        f"<th class='pv-num'>{tip(wording.P4_P3_COL_PHI.format(a=a, b=b, unit=unit), hint_phi)}</th>"
        f"<th class='pv-num'>{tip(wording.P4_P3_COL_PHI.format(a=b, b=a, unit=unit), hint_phi)}</th>"
        f"<th class='pv-num'>{tip(wording.P4_P3_COL_PHI_FINAL.format(unit=unit), hint_phi)}</th>"
        f"<th class='pv-num'>{tip(wording.P4_P3_COL_SHARE, wording.HELP_SHARE)}</th>"
    )
    body = []
    for row in view.rows:
        same = _phase3_row_cells(view, row, 4)
        if same:
            body.append(same)
            continue
        share = analysis_logic.fmt_share(row.share) if view.share_defined else wording.P4_P3_SHARE_UNDEFINED
        cells = (
            analysis_logic.fmt_watts(row.phi_ab), analysis_logic.fmt_watts(row.phi_ba),
            analysis_logic.fmt_watts(row.phi_final), share,
        )
        body.append(
            f"<tr><td>{escape(row.label)}</td>"
            + "".join(f"<td class='pv-num pv-mono'>{escape(text)}</td>" for text in cells)
            + "</tr>"
        )
    return f'<table class="pv-stage-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def phase3_report_table_html(view) -> str:
    """The Report's Phase 3 table: φ final and share by stage (the numbers behind the share bars and the
    build-up chart). There is no φ A→B or φ B→A column here and no signed-φ column."""
    unit = analysis_logic.PHI_UNIT
    head = (
        f"<th>{escape(wording.P4_COL_STAGE)}</th>"
        f"<th class='pv-num'>{tip(wording.P4_P3_COL_PHI_FINAL.format(unit=unit), wording.HELP_PHI)}</th>"
        f"<th class='pv-num'>{tip(wording.P4_P3_COL_SHARE, wording.HELP_SHARE)}</th>"
    )
    body = []
    for row in view.rows:
        same = _phase3_row_cells(view, row, 2)
        if same:
            body.append(same)
            continue
        share = analysis_logic.fmt_share(row.share) if view.share_defined else wording.P4_P3_SHARE_UNDEFINED
        body.append(
            f"<tr><td>{escape(row.label)}</td><td class='pv-num pv-mono'>{escape(analysis_logic.fmt_watts(row.phi_final))}</td>"
            f"<td class='pv-num pv-mono'>{escape(share)}</td></tr>"
        )
    return f'<table class="pv-stage-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def efficiency_text(view) -> tuple[str, bool]:
    """The efficiency line (both numbers) and whether the stages add up to RMSD(A,B)."""
    a, b = view.pair
    total, rmsd, agrees = analysis_logic.efficiency(view)
    unit = analysis_logic.PHI_UNIT
    text = wording.P4_P3_EFF.format(
        total=analysis_logic.fmt_watts(total), a=a, b=b, rmsd=analysis_logic.fmt_watts(rmsd), unit=unit
    )
    if not agrees:
        text += " " + wording.P4_P3_EFF_DIFF.format(diff=analysis_logic.fmt_watts(abs(total - rmsd)), unit=unit)
    return text, agrees
