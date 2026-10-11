"""The analysis rows shared by Past analyses and Home's recent list, and the actions on them.

Each action button is bound, when the row is drawn, to the analysis shown in that row: the id goes into the
button's own arguments, so a click acts on the row that was on screen even if the list has changed since
(a new search, a new analysis saved). Buttons are keyed by position and never look an analysis up by it.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app import components, past_logic, session_load, wording

PENDING = "past_action"


def request(action: str, analysis_id: str, name: str) -> None:
    """A row's button was pressed: remember which analysis and what to do. The work runs at the top of the page."""
    st.session_state[PENDING] = {"action": action, "id": analysis_id, "name": name}


def run_pending(ss) -> None:
    """Do the action a row button asked for: open read-only, continue, or duplicate, then go to its page."""
    pending = ss.pop(PENDING, None)
    if not pending:
        return
    landing = None
    with st.status(wording.PAST_PROGRESS_LOAD, expanded=True) as box:

        def say(text: str) -> None:
            box.update(label=text)
            st.write(text)

        try:
            if pending["action"] == past_logic.OPEN:
                landing = session_load.open_readonly(ss, pending["id"])
            elif pending["action"] == past_logic.CONTINUE:
                landing = session_load.restore(ss, pending["id"], say)
            else:
                new_id, new_name = past_logic.duplicate(pending["id"], pending["name"])
                landing = session_load.restore(ss, new_id, say)
                ss["flash"] = wording.PAST_DUPLICATED.format(name=new_name)
        except session_load.LoadError as exc:
            box.update(label=wording.PAST_PROGRESS_LOAD, state="complete")
            ss["past_problem"] = str(exc)
            return
        box.update(label=wording.PAST_PROGRESS_LOAD, state="complete", expanded=False)
    ss.pop("past_problem", None)
    if landing is not None:
        st.switch_page(components.PAGES[landing.page])


_LABELS = {
    past_logic.OPEN: wording.PAST_OPEN,
    past_logic.CONTINUE: wording.PAST_CONTINUE,
    past_logic.DUPLICATE: wording.PAST_DUPLICATE,
}


def _name_cell(row: past_logic.PastRow) -> str:
    return (
        f'<div class="pv-row-name">{escape(row.name)}</div>'
        f'<div class="pv-row-file">{escape(wording.PAST_FILE_LINE.format(file=row.file))}</div>'
    )


def _saved_cell(row: past_logic.PastRow) -> str:
    """The saved time in the Report's form ('05 Oct 2026 19:10 UTC'); in a narrow column the date and the time
    wrap as two units, never in the middle of either."""
    date, clock = " ".join(row.saved.split(" ")[:3]), " ".join(row.saved.split(" ")[3:])
    return f'<span class="pv-nobreak">{escape(date)}</span> <span class="pv-nobreak">{escape(clock)}</span>'


def _outcome_cell(row: past_logic.PastRow) -> str:
    muted = " pv-muted" if row.outcome == wording.PAST_NOT_RUN_YET else ""
    return f'<div class="pv-row-mono{muted}">{escape(row.outcome)}</div>'


def _status_cell(row: past_logic.PastRow) -> str:
    note = f'<div class="pv-row-file">{escape(row.note)}</div>' if row.note else ""
    return f'<div class="pv-row-status">{escape(row.status)}</div>{note}'


def header(widths: list[float], headers: tuple[str, ...], key: str) -> None:
    with st.container(key=key):
        columns = st.columns(widths, gap="small")
        for index, (column, text) in enumerate(zip(columns, headers, strict=True)):
            last = " pv-th-last" if index == len(headers) - 1 else ""
            column.html(f'<div class="pv-th-cell{last}">{escape(text)}</div>')


def render_rows(rows: list[past_logic.PastRow], widths: list[float], prefix: str, with_duplicate: bool) -> None:
    """One keyed row per analysis. Home passes with_duplicate=False: each row offers only the action its
    state allows (Open or Continue)."""
    for index, row in enumerate(rows):
        with st.container(key=f"{prefix}_row_{index}"):
            name, saved, outcome, status, actions = st.columns(widths, gap="small")
            name.html(_name_cell(row))
            saved.html(f'<div class="pv-row-mono">{_saved_cell(row)}</div>')
            outcome.html(_outcome_cell(row))
            status.html(_status_cell(row))
            with actions:
                shown = list(row.actions) if with_duplicate else [a for a in row.actions if a != past_logic.DUPLICATE]
                for action in shown:
                    st.button(
                        _LABELS[action], key=f"{prefix}_{action}_{index}",
                        type="primary" if with_duplicate and action != past_logic.DUPLICATE else "secondary",
                        on_click=request, args=(action, row.id, row.name),
                    )
