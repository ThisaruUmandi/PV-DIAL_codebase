"""Step 1 · Data & site, laid out as in the Data mock-up.

Widgets hold what the user typed; every change goes through state.request_change, so an
edit made after Continue shows the clear warning first (F2.5). The checks and the saving
are in services.py.
"""

from __future__ import annotations

import re
from html import escape

import streamlit as st

from app import components, services, state, wording
from pvdials.analysis import AnalysisError
from pvdials.dla.metrics import resolve_tau
from pvdials.physics.hardware import CEC, CEC_INVERTER, list_inverter_names, list_module_names

DEFAULT_MODULE = "Canadian_Solar_Inc__CS6K_300MS"
DEFAULT_INVERTER = "ABB__PVI_6000_OUTD_S_US_A__208V_"
DEFAULT_ALBEDO = 0.2
DEFAULT_GEOMETRY = "open_rack"
DEFAULT_CONSTRUCTION = "glass_polymer"

# the fields each group of inputs holds (widget key = "w1_" + field)
GROUPS = {
    "name": ("name",),
    "offset": ("offset_choice", "offset_reason"),
    "site": ("latitude", "longitude", "elevation", "tilt", "azimuth", "albedo", "geometry", "construction"),
    "hardware": ("module", "inverter", "modules_per_string", "strings_per_inverter", "module_height_m"),
}
ALL_FIELDS = tuple(f for fields in GROUPS.values() for f in fields)
WIDGET_DEFAULTS = {
    "name": "",
    "offset_choice": "header",
    "offset_reason": "",
    "latitude": None,
    "longitude": None,
    "elevation": None,
    "tilt": None,
    "azimuth": None,
    "albedo": DEFAULT_ALBEDO,
    "geometry": DEFAULT_GEOMETRY,
    "construction": DEFAULT_CONSTRUCTION,
    "module": DEFAULT_MODULE,
    "inverter": DEFAULT_INVERTER,
    "modules_per_string": None,
    "strings_per_inverter": None,
    "module_height_m": None,
}


def _key(field: str) -> str:
    return f"w1_{field}"


@st.cache_data(show_spinner=False)
def _module_names() -> list[str]:
    return list_module_names(CEC)


@st.cache_data(show_spinner=False)
def _inverter_names() -> list[str]:
    return list_inverter_names(CEC_INVERTER)


# --- State plumbing -------------------------------------------------------------------------------


def init_widgets(ss) -> None:
    """Give every widget its value. Streamlit forgets a widget's state while another page
    is showing, so a widget that is missing takes the value it had at the end of the last
    render (kept in w1_prev, which is not a widget), or its starting value on the first visit."""
    ss.setdefault("upload_n", 0)
    ss.setdefault("w1_prev", {})
    for field, default in WIDGET_DEFAULTS.items():
        key = _key(field)
        if key not in ss:
            ss[key] = ss["w1_prev"].get(key, default)


def apply_file_defaults(ss, ingest: services.Ingest) -> None:
    """A different file was adopted: take the site from it and start the offset at the
    file's own value. Widgets are set here, before they are drawn."""
    for field in ("latitude", "longitude", "elevation"):
        ss[_key(field)] = ingest.site_found.get(field)
    ss[_key("offset_choice")] = "header"
    ss[_key("offset_reason")] = ""
    if not ss.get(_key("name")):
        ss[_key("name")] = re.sub(r"\.csv$", "", ingest.name, flags=re.IGNORECASE)


def sync(ss) -> None:
    """Make ss['ingest'] describe the committed weather file."""
    weather = ss.get("weather")
    if not weather:
        ss["ingest"] = None
        return
    current = ss.get("ingest")
    if current is not None and current.sha256 == weather["sha256"]:
        return
    fresh = ss.pop("_ingest_new", None)
    if fresh is None or fresh.sha256 != weather["sha256"]:
        fresh = services.ingest_stored(weather["stored_path"], weather["name"])
    ss["ingest"] = fresh
    apply_file_defaults(ss, fresh)
    ss["upload_n"] += 1


def collect_form(ss) -> services.Form:
    """Everything the widgets hold, as a Form."""
    ingest = ss.get("ingest")
    sources = {}
    if ingest is not None:
        sources = {f: "From CSV" for f in ingest.site_found}
    geometry, construction = ss[_key("geometry")], ss[_key("construction")]
    return services.Form(
        name=ss[_key("name")] or "",
        latitude=ss[_key("latitude")],
        longitude=ss[_key("longitude")],
        elevation=ss[_key("elevation")],
        site_sources=sources,
        offset_choice=ss[_key("offset_choice")],
        offset_reason=ss[_key("offset_reason")] or "",
        tilt=ss[_key("tilt")],
        azimuth=ss[_key("azimuth")],
        albedo=ss[_key("albedo")],
        mounting_geometry=None if geometry == DEFAULT_GEOMETRY else geometry,
        mounting_construction=None if construction == DEFAULT_CONSTRUCTION else construction,
        module=ss[_key("module")],
        inverter=ss[_key("inverter")],
        modules_per_string=ss[_key("modules_per_string")],
        strings_per_inverter=ss[_key("strings_per_inverter")],
        module_height_m=ss[_key("module_height_m")],
    )


def _edited(field: str) -> None:
    """A widget changed: ask the state to apply it (or hold it until confirmed)."""
    ss = st.session_state
    group = next(g for g, fields in GROUPS.items() if field in fields)
    new = {f: ss[_key(f)] for f in GROUPS[group]}
    old_widget = ss["w1_prev"].get(_key(field))
    state.request_change(ss, group, new, widget_key=_key(field), old_widget=old_widget)


def _uploaded() -> None:
    ss = st.session_state
    file = ss.get(f"w1_upload_{ss['upload_n']}")
    if file is None:
        return
    ingest = services.ingest_upload(file.getvalue(), file.name)
    ss["upload_problem"] = None
    if not ingest.usable:
        ss["upload_problem"] = ingest.problem
        ss["upload_n"] += 1
        return
    weather = ss.get("weather")
    if weather and weather["sha256"] == ingest.sha256:
        ss["upload_n"] += 1
        return
    ss["_ingest_new"] = ingest
    new = {"name": ingest.name, "sha256": ingest.sha256, "stored_path": ingest.stored_path}
    state.request_change(ss, "weather", new, reset_uploader=True)


# --- Pieces of the page ------------------------------------------------------------------------------


def _tier_lines(ingest: services.Ingest, tier4) -> list[tuple[int, services.ValidationResult]]:
    tiers = list(ingest.tiers.items())
    if tier4 is not None:
        tiers.append((4, tier4))
    return tiers


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def _summary_strip(ingest: services.Ingest, form: services.Form) -> None:
    """After upload the drop zone gives way to this: file name, rows, what the checks said, SHA."""
    step = wording.D_STEP_HOURLY if ingest.hourly else wording.D_STEP_OTHER
    meta = " · ".join(
        (wording.D_STRIP_FILE_ROWS.format(rows=ingest.rows), step, ingest.source_label)
    )

    missing = [c for c in services.REQUIRED_COLUMNS if ingest.columns.get(c) is None]
    if missing:
        columns = components.message_html("bad", wording.D_MSG_COLUMNS_BAD.format(names=services._display_names(missing)), False)
    elif ingest.columns.get("pressure") is None:
        columns = components.message_html("warn", wording.D_MSG_COLUMNS_NO_SP, False)
    else:
        columns = components.message_html("ok", wording.D_MSG_COLUMNS_OK, False)

    tier4 = services.tier4_result(ingest, form)
    passed, problems, warnings = services.tier_summary(dict(_tier_lines(ingest, tier4)))
    if not passed:
        tiers = components.message_html("bad", wording.D_MSG_TIERS_BAD.format(n=problems, s=_plural(problems)), False)
    elif warnings:
        tiers = components.message_html("warn", wording.D_MSG_TIERS_WARN.format(n=warnings, s=_plural(warnings)), False)
    elif tier4 is None:
        tiers = components.message_html("ok", wording.D_MSG_TIERS_WAIT, False)
    else:
        tiers = components.message_html("ok", wording.D_MSG_TIERS_OK.format(n=0, s="s"), False)

    st.html(
        '<div class="pv-filestrip">'
        f'<div class="pv-filestrip-head">{components.icon("file", 20)}<div>'
        f'<div class="pv-filestrip-name">{escape(ingest.name)}</div>'
        f'<div class="pv-muted">{escape(meta)}</div></div></div>'
        f"{columns}{tiers}"
        f'<div class="pv-sha"><span class="pv-sha-label" title="{escape(wording.HELP_FILE_SHA)}">'
        f"{escape(wording.LABEL_FILE_SHA)}</span><code>{escape(ingest.sha256)}</code></div></div>"
    )


def _file_card(ss, ingest, form) -> None:
    components.card_title(wording.D_CARD_FILE, wording.D_CARD_FILE_SUB)
    components.field_label(wording.D_NAME_LABEL, "required", hint=wording.D_NAME_HELP)
    st.text_input(
        wording.D_NAME_LABEL, key=_key("name"), label_visibility="collapsed",
        on_change=_edited, args=("name",),
    )
    components.field_label(wording.D_FILE_LABEL, "required")
    if ss.get("upload_problem"):
        components.message("bad", ss["upload_problem"])

    if ingest is None:
        with st.container(key="drop"):
            st.file_uploader(
                wording.D_UPLOAD_LABEL, type=["csv"], key=f"w1_upload_{ss['upload_n']}", on_change=_uploaded,
                label_visibility="collapsed",
            )
        st.html(f'<p class="pv-note-line">{escape(wording.D_DROP_NOTE)}</p>')
        return

    _summary_strip(ingest, form)
    with st.container(key="replace"):
        st.file_uploader(
            wording.D_REPLACE_FILE, type=["csv"], key=f"w1_upload_{ss['upload_n']}", on_change=_uploaded,
            label_visibility="collapsed",
        )
    tier4 = services.tier4_result(ingest, form)
    with st.expander(wording.D_CHECK_DETAILS):
        for number, result in _tier_lines(ingest, tier4):
            st.html(f'<div class="pv-tier-title">{escape(wording.D_TIER_NAMES[number])}</div>')
            lines = [*result.problems, *result.warnings, *result.notes]
            if not lines:
                st.caption(wording.D_NO_FINDINGS)
            for line in lines:
                st.markdown(f"- {line}")


def _offset_card(ss, ingest, form) -> None:
    components.card_title(wording.D_CARD_OFFSET, wording.D_CARD_OFFSET_SUB)
    if ingest is None:
        components.message("todo", wording.D_NEED_FILE.capitalize() + ".", False)
        return
    header = ingest.header_offset
    absent = header is None or header.source == "assumed_absent_from_header"
    intro = wording.D_OFFSET_INTRO_ABSENT if absent else wording.D_OFFSET_INTRO.format(value=header.value_h)
    st.html(f'<p class="pv-muted pv-tight" style="margin:0">{escape(intro)}</p>')

    labels = services.offset_labels(ingest)
    counts = services.offset_counts(ingest, form)
    if counts is None:
        components.message("todo", wording.D_OFFSET_NEEDS_SITE, False)
    else:
        by_label = {c.label: c for c in counts}
        head = "".join(f'<div class="pv-th">{escape(h)}</div>' for h in wording.D_OFFSET_COLS)
        rows = ""
        for choice in services.OFFSET_CHOICES:
            c = by_label[choice]
            selected = " pv-row-selected" if choice == form.offset_choice else ""
            rows += (
                f'<div class="pv-td{selected}">{escape(labels[choice])}</div>'
                f'<div class="pv-td pv-mono{selected}">{c.ghi_positive_sun_down}</div>'
                f'<div class="pv-td pv-mono{selected}">{c.ghi_zero_sun_up}</div>'
            )
        st.html(f'<div class="pv-offset-table">{head}{rows}</div>')

    components.field_label(wording.D_OFFSET_CHOICE, "default" if form.offset_choice == "header" else None,
                           hint=wording.HELP_OFFSET)
    st.radio(
        wording.D_OFFSET_CHOICE, services.OFFSET_CHOICES, format_func=labels.get, key=_key("offset_choice"),
        horizontal=True, label_visibility="collapsed", on_change=_edited, args=("offset_choice",),
    )
    needs_reason = form.offset_choice != "header"
    components.field_label(
        wording.D_OFFSET_REASON, "required" if needs_reason else "optional", hint=wording.D_OFFSET_REASON_HELP
    )
    st.text_input(
        wording.D_OFFSET_REASON, key=_key("offset_reason"), label_visibility="collapsed",
        on_change=_edited, args=("offset_reason",),
    )


def _number(
    field: str, label: str, tag: str | None, locked: bool = False, hint: str | None = None,
    stacked: bool = True, **kwargs,
) -> None:
    components.field_label(label, tag, hint, stacked=stacked)
    st.number_input(
        label, key=_key(field), value=None, disabled=locked, label_visibility="collapsed",
        on_change=_edited, args=(field,), **kwargs,
    )


def _site_card(ss, ingest) -> None:
    components.card_title(wording.D_CARD_SITE, wording.D_CARD_SITE_SUB)
    found = ingest.site_found if ingest is not None else {}
    c1, c2, c3 = st.columns(3)
    for column, field, label, bounds, optional in (
        (c1, "latitude", wording.D_LAT, (-90.0, 90.0), False),
        (c2, "longitude", wording.D_LON, (-180.0, 180.0), False),
        (c3, "elevation", wording.D_ELEV, (-500.0, 9000.0), True),
    ):
        from_file = field in found
        with column:
            _number(
                field, label, "file" if from_file else ("optional" if optional else "required"), from_file,
                hint=wording.D_FROM_FILE_HELP if from_file else None,
                min_value=bounds[0], max_value=bounds[1], format="%g",
            )
    c1, c2, c3 = st.columns(3)
    with c1:
        _number("tilt", wording.D_TILT, "required", min_value=0.0, max_value=90.0, format="%g")
    with c2:
        _number("azimuth", wording.D_AZIMUTH, "required", min_value=0.0, max_value=360.0, format="%g")
    with c3:
        components.field_label(
            wording.D_ALBEDO_LABEL, "default" if ss[_key("albedo")] == DEFAULT_ALBEDO else None, stacked=True
        )
        st.number_input(
            wording.D_ALBEDO_LABEL, key=_key("albedo"), min_value=0.0, max_value=1.0, format="%g", step=0.05,
            label_visibility="collapsed", on_change=_edited, args=("albedo",),
        )
    c1, c2 = st.columns(2)
    with c1:
        components.field_label(wording.D_GEOMETRY, "default" if ss[_key("geometry")] == DEFAULT_GEOMETRY else None)
        st.selectbox(
            wording.D_GEOMETRY, list(wording.D_GEOMETRY_NAMES), key=_key("geometry"),
            format_func=wording.D_GEOMETRY_NAMES.get, label_visibility="collapsed", on_change=_edited,
            args=("geometry",),
        )
    with c2:
        components.field_label(
            wording.D_CONSTRUCTION, "default" if ss[_key("construction")] == DEFAULT_CONSTRUCTION else None
        )
        st.selectbox(
            wording.D_CONSTRUCTION, list(wording.D_CONSTRUCTION_NAMES), key=_key("construction"),
            format_func=wording.D_CONSTRUCTION_NAMES.get, label_visibility="collapsed", on_change=_edited,
            args=("construction",),
        )
    components.field_label(wording.D_MODULE, "default" if ss[_key("module")] == DEFAULT_MODULE else None)
    st.selectbox(
        wording.D_MODULE, _module_names(), key=_key("module"), label_visibility="collapsed",
        on_change=_edited, args=("module",),
    )
    components.field_label(wording.D_INVERTER, "default" if ss[_key("inverter")] == DEFAULT_INVERTER else None)
    st.selectbox(
        wording.D_INVERTER, _inverter_names(), key=_key("inverter"), label_visibility="collapsed",
        on_change=_edited, args=("inverter",),
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        _number("modules_per_string", wording.D_MODULES_PER_STRING, "required", min_value=1, max_value=1000, step=1)
    with c2:
        _number("strings_per_inverter", wording.D_STRINGS, "required", min_value=1, max_value=1000, step=1)
    with c3:
        _number("module_height_m", wording.D_MODULE_HEIGHT, "required", min_value=0.0, max_value=100.0, format="%g")


def _continue(ss, form, ingest) -> None:
    try:
        tau = resolve_tau(ss["tau"]["value"], _defaults()) if isinstance(ss.get("tau"), dict) else None
        done = services.commit_page1(form, ingest, ss.get("analysis_id"), tau=tau)
    except (AnalysisError, ValueError, KeyError) as exc:
        components.show_problem(services.plain_failure(exc))
        return
    ss["analysis_id"] = done.analysis_id
    ss["name"] = form.name.strip()
    ss["location"] = done.inputs["location"]
    ss["inputs"] = done.inputs  # page 2 chooses its pool from the module and mounting saved here
    ss["data_valid"] = True
    ss["flash"] = wording.D_SAVED_FLASH
    st.switch_page(components.PAGES["2"])


def _defaults() -> dict:
    from pvdials.config import load_defaults

    return load_defaults()


def render() -> None:
    ss = st.session_state
    init_widgets(ss)
    sync(ss)
    components.step_header(1)

    ingest = ss.get("ingest")
    pending = bool(ss.get("pending"))
    form = collect_form(ss)

    left, right = st.columns(2)
    with left:
        with st.container(key="card_file"):
            _file_card(ss, ingest, form)
        with st.container(key="card_offset"):
            _offset_card(ss, ingest, form)
    with right, st.container(key="card_site"):
        _site_card(ss, ingest)

    checks = services.checklist(form, ingest)
    ready = all(check.done for check in checks)
    with st.container(key="continue_row"):
        list_col, button_col = st.columns([3, 2])
        with list_col:
            components.checklist(
                [
                    (c.done, c.label, wording.D_STILL_NEEDED.format(names=", ".join(c.needs)) if c.needs else "")
                    for c in checks
                ],
                wording.D_CHECKLIST_TITLE, wording.D_CHECKLIST_READY,
            )
        with button_col:
            if st.button(wording.D_CONTINUE, type="primary", disabled=not ready or pending, key="w1_continue"):
                _continue(ss, form, ingest)

    ss["w1_prev"] = {_key(f): ss[_key(f)] for f in ALL_FIELDS}
