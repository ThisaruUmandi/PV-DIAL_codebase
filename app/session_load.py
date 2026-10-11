"""Put a saved analysis into the session: Continue (and a browser refresh), Open (read-only) and the
copy that Duplicate makes.

Everything is read from the stored row. Nothing here writes, runs a pipeline or calls run_analysis:
the live objects a step needs (Phase 1, Phase 3, a substitution) are rebuilt later, by that step, only
when its button needs them. The analysis id and the provenance record ids never change.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import config_logic, past_logic, run_logic, services, state, wording
from app.screens import config_pipelines, data_site
from pvdials.analysis import AnalysisError
from pvdials.provenance.analyses import load_analysis

ID_PATTERN = re.compile(r"[0-9a-f]{32}")  # what the app and the command line make: uuid4().hex
_SECTIONS = ("inputs", "phase1", "phase2", "phase3", "reexec", "pipelines", "run_info")


class LoadError(Exception):
    """A saved analysis could not be put into the session; the text is plain words for the page."""


@dataclass(frozen=True)
class Landing:
    page: str  # a key of components.PAGES
    message: str | None = None


def valid_id(value: object) -> bool:
    """Only what the app itself makes can reach a query: 32 lower-case hex characters."""
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def _row(analysis_id: str) -> dict[str, Any]:
    row = load_analysis(analysis_id) if isinstance(analysis_id, str) else None
    if row is None or not isinstance(row.get("inputs"), dict):
        raise LoadError(wording.PAST_NOT_FOUND)
    return row


def _held(row: dict[str, Any]) -> list[str]:
    return [section for section in _SECTIONS if row.get(section) is not None]


def progress_of(row: dict[str, Any]) -> past_logic.Progress:
    return past_logic.progress(row["status"], _held(row), row.get("phase1"), row.get("phase2"), row.get("phase3"))


# --- What the pages 1 and 2 widgets hold --------------------------------------------------------------------------


def offset_choice(offset: dict[str, Any]) -> str:
    """The choice on page 1: as stored, or (rows saved by the command line) read from the stored offset."""
    stored = offset.get("choice")
    if stored in services.OFFSET_CHOICES:
        return stored
    if offset.get("source") not in (None, "user_entered"):
        return "header"
    return {0.0: "hour_start", 0.5: "hour_centre"}.get(offset.get("value_h"), "header")


def form_values(inputs: dict[str, Any], ingest: services.Ingest | None) -> dict[str, Any]:
    """Page 1's widget values from the stored inputs. A value the row never stored stays at the field's
    starting value (empty where the field starts empty)."""
    site = inputs.get("site") or {}
    hardware = inputs.get("hardware") or {}
    offset = inputs.get("time_offset") or {}
    location = inputs.get("location") or {}
    found = ingest.site_found if ingest is not None else {}

    def place(name: str):
        return location[name] if location.get(name) is not None else found.get(name)

    stored = {
        "name": inputs.get("name"),
        "offset_choice": offset_choice(offset),
        "offset_reason": offset.get("reason"),
        "latitude": place("latitude"),
        "longitude": place("longitude"),
        "elevation": place("elevation"),
        "tilt": site.get("tilt_deg"),
        "azimuth": site.get("azimuth_deg"),
        "albedo": site.get("albedo"),
        "geometry": site.get("mounting_geometry"),
        "construction": site.get("mounting_construction"),
        "module": hardware.get("module_name"),
        "inverter": hardware.get("inverter_name"),
        "modules_per_string": hardware.get("modules_per_string"),
        "strings_per_inverter": hardware.get("strings_per_inverter"),
        "module_height_m": site.get("module_height_m"),
    }
    return {
        f"w1_{field}": stored[field] if stored[field] is not None else data_site.WIDGET_DEFAULTS[field]
        for field in data_site.ALL_FIELDS
    }


def config_values(inputs: dict[str, Any]) -> dict[str, Any]:
    """Page 2's widget values: the three pipelines' models and τ, as stored."""
    values = {
        config_pipelines._key(label, stage): (inputs["pipelines"][label] or {}).get(stage)
        for label in config_logic.LABELS
        for stage in config_logic.STAGES
    }
    values[config_pipelines.TAU_KEY] = float(inputs["tau"]["value"])
    return values


# --- Weather file -------------------------------------------------------------------------------------------------


def weather_name(inputs: dict[str, Any]) -> str:
    weather = inputs.get("weather") if isinstance(inputs.get("weather"), dict) else {}
    return weather.get("name") or Path(str(inputs.get("weather_file") or "")).name


def weather_file_present(inputs: dict[str, Any]) -> bool:
    return bool(inputs.get("weather_file")) and Path(run_logic.weather_path(inputs)).exists()


def expected_sha(inputs: dict[str, Any]) -> str | None:
    weather = inputs.get("weather")
    return weather.get("sha256") if isinstance(weather, dict) else None


# --- Continue -----------------------------------------------------------------------------------------------------


def _staged(row: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """The session values for this row. They are built apart from the session and applied only when the
    whole load has worked, so a load that fails leaves the session as it was."""
    return {"analysis_id": row["id"], "name": row["name"], "inputs": inputs, "location": inputs.get("location")}


def _apply(ss: MutableMapping, staged: dict[str, Any]) -> None:
    state.new_analysis(ss)
    ss.update(staged)


def restore(
    ss: MutableMapping, analysis_id: str, progress: Callable[[str], None] | None = None, file_path: str | None = None
) -> Landing:
    """Load a stored analysis for Continue (also used when a page is refreshed): inputs, widgets, saved
    phases and the flags, at the step where it stopped. Raises LoadError with a plain message.

    file_path: the weather file uploaded again after it was found missing; the analysis then reads it from
    there (same content, checked by resume_after_upload) instead of from the path it was saved with."""
    say = progress or (lambda _text: None)
    row = _row(analysis_id)
    inputs = copy.deepcopy(row["inputs"])
    if file_path:
        inputs["weather_file"] = file_path
        if isinstance(inputs.get("weather"), dict):
            inputs["weather"]["stored_path"] = file_path
    reached = progress_of(row)
    step = reached.step if reached.kind == past_logic.STOPPED else 4
    if not past_logic.inputs_present(step, list(inputs)):
        raise LoadError(wording.PAST_CANNOT_CONTINUE)

    say(wording.PAST_PROGRESS_LOAD)
    staged = _staged(row, inputs)

    if not weather_file_present(inputs):
        # nothing else can be shown until the file is back; step 1 says which one
        name = weather_name(inputs)
        staged["w1_prev"] = form_values(inputs, None)
        staged["awaiting_file"] = {"analysis_id": analysis_id, "name": name, "sha256": expected_sha(inputs)}
        message = wording.PAST_FILE_MISSING.format(name=name) if name else wording.PAST_FILE_NOT_RECORDED
        staged["upload_problem"] = message
        _apply(ss, staged)
        return Landing("1", message)

    path = Path(run_logic.weather_path(inputs))
    ingest = services.ingest_upload(path.read_bytes(), weather_name(inputs))
    if not ingest.usable:
        raise LoadError(wording.PAST_LOAD_FAILED.format(detail=(ingest.problem or "").rstrip(".")))
    staged["ingest"] = ingest
    staged["weather"] = {"name": ingest.name, "sha256": ingest.sha256, "stored_path": ingest.stored_path}
    staged["w1_prev"] = form_values(inputs, ingest)

    if step >= 2:
        staged["data_valid"] = True
    if step >= 3:
        staged["config_valid"] = True
        staged["config"] = {label: dict(inputs["pipelines"][label]) for label in config_logic.LABELS}
        staged["tau"] = dict(inputs["tau"])
        staged["w2_prev"] = config_values(inputs)
    if step >= 4:
        _restore_results(staged, row, inputs, say)
    _apply(ss, staged)
    return Landing(str(step))


def _restore_results(ss: dict, row: dict[str, Any], inputs: dict[str, Any], say: Callable[[str], None]) -> None:
    """Step 4: the stored run and the saved phases. The live pipelines are not rebuilt here."""
    say(wording.PAST_PROGRESS_RUN)
    try:
        run = run_logic.reopen(row["id"], inputs)
    except (AnalysisError, KeyError, ValueError) as exc:
        raise LoadError(wording.PAST_LOAD_FAILED.format(detail=str(exc).rstrip("."))) from exc
    ss["run"] = run
    ss["run_done"] = True
    ss["pipelines_summary"] = run.pipelines_summary
    ss["run_info"] = run.run_info
    if row.get("phase1"):
        ss["phase1"], ss["phase2"], ss["phase3"] = row["phase1"], row.get("phase2"), row.get("phase3")
        ss["phase1_done"] = True
        ss["has_k"] = any(e.get("status") == "ran" and e.get("k") for e in row["phase1"].values() if isinstance(e, dict))
        ss["reexec_confirmed"] = row.get("reexec") is not None


def resume_after_upload(ss: MutableMapping, ingest: services.Ingest) -> str | None:
    """The file the analysis was waiting for is back. Returns None when it can carry on (the caller then
    calls restore again, which finds the file), or a plain message when the file is not the one it was run on."""
    waiting = ss.get("awaiting_file")
    if not waiting:
        return None
    if waiting["sha256"] is not None:
        same = ingest.sha256 == waiting["sha256"]
    else:
        same = ingest.name == waiting["name"]
    return None if same else wording.PAST_FILE_WRONG.format(name=waiting["name"])


# --- Open (read-only) ----------------------------------------------------------------------------------------------


def open_readonly(ss: MutableMapping, analysis_id: str) -> Landing:
    """Show a saved analysis on the Report, read-only: the stored sections go into the session for the
    sidebar and the summary line; nothing can be run or changed from here and nothing is written."""
    row = _row(analysis_id)
    phase1 = row.get("phase1")
    if not phase1:
        raise LoadError(wording.PAST_LOAD_FAILED.format(detail="it was saved without a Phase 1"))
    inputs = copy.deepcopy(row["inputs"])
    staged = _staged(row, inputs)
    weather = inputs.get("weather") if isinstance(inputs.get("weather"), dict) else {}
    pipelines = inputs.get("pipelines")
    staged.update(
        readonly=True,
        weather={"name": weather_name(inputs), "sha256": weather.get("sha256"), "stored_path": weather.get("stored_path")},
        data_valid=True, config_valid=True, run_done=True, phase1_done=True,
        run_info=row.get("run_info"),
        phase1=phase1, phase2=row.get("phase2"), phase3=row.get("phase3"),
        has_k=any(e.get("status") == "ran" and e.get("k") for e in phase1.values() if isinstance(e, dict)),
        reexec_confirmed=row.get("reexec") is not None,
    )
    if isinstance(pipelines, dict) and all(isinstance(pipelines.get(label), dict) for label in config_logic.LABELS):
        staged["config"] = {label: dict(pipelines[label]) for label in config_logic.LABELS}
    if isinstance(inputs.get("tau"), dict):
        staged["tau"] = dict(inputs["tau"])
    _apply(ss, staged)
    return Landing("6")
