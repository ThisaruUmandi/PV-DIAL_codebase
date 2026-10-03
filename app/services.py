"""Page-1 logic without Streamlit: read an uploaded file, report on it, check the
form, and save the analysis through the same functions the command line uses.

Nothing here prints or draws; pages call these and show the results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app import wording
from pvdials.analysis import (
    AnalysisConfig,
    AnalysisError,
    LoadResult,
    SiteStepResult,
    build_inputs_dict,
    location_block,
    step_hardware,
    step_site_and_offset,
    weather_block,
)
from pvdials.config import ROOT, load_defaults
from pvdials.data.column_mapper import (
    TAG_ASSUMED_ABSENT,
    TAG_USER_ENTERED,
    TimeOffset,
    detect_columns,
    detect_site_metadata,
    detect_time_offset,
)
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import (
    UploadedFile,
    UploadError,
    file_sha256,
    load_uploaded_csv,
    store_upload,
)
from pvdials.data.validate import (
    ValidationResult,
    run_all_validations,
    validate_full_year_if_applicable,
    validate_physical_consistency,
    validate_physical_ranges,
    validate_structure,
)
from pvdials.dla.metrics import Tau, resolve_tau
from pvdials.physics.site import OffsetCandidate, build_site_context, offset_consistency_report
from pvdials.provenance.analyses import save_analysis

REQUIRED_COLUMNS = ("ghi", "temp_air", "wind_speed")
OFFSET_CHOICES = ("header", "hour_start", "hour_centre")


# --- Reading an uploaded file -------------------------------------------------------------


@dataclass
class Ingest:
    """What was learned from one uploaded file. `problem` is set (in plain words) when
    the file cannot be used at all; otherwise `load_result` is ready."""

    name: str
    sha256: str
    stored_path: str
    problem: str | None = None
    load_result: LoadResult | None = None
    rows: int = 0
    source_label: str = wording.D_SOURCE_OTHER
    hourly: bool = True
    columns: dict[str, str | None] = field(default_factory=dict)  # canonical -> file's column, None if absent
    missing_required: list[str] = field(default_factory=list)
    tiers: dict[int, ValidationResult] = field(default_factory=dict)  # tiers 1-3 (tier 4 needs the site)
    header_offset: TimeOffset | None = None
    site_found: dict[str, float] = field(default_factory=dict)
    site_missing: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.problem is None and self.load_result is not None


def _display_names(canonical: list[str]) -> str:
    return ", ".join(wording.D_COLUMN_NAMES.get(c, c) for c in canonical)


def ingest_upload(content: bytes, filename: str, root: str | Path | None = None) -> Ingest:
    """Keep the upload in the upload store, read it and check tiers 1-3."""
    path, sha = store_upload(content, root=root)
    ingest = Ingest(name=filename, sha256=sha, stored_path=str(path))
    try:
        uploaded: UploadedFile = load_uploaded_csv(path)
    except UploadError as exc:
        ingest.problem = wording.D_UPLOAD_UNREADABLE.format(detail=str(exc).rstrip("."))
        return ingest

    mapping = detect_columns(uploaded.table)
    ingest.columns = {
        canonical: mapping.found.get(canonical) for canonical in (*REQUIRED_COLUMNS, "pressure")
    }
    ingest.missing_required = list(mapping.missing)
    if mapping.missing:
        ingest.problem = wording.D_UPLOAD_COLUMNS.format(names=_display_names(mapping.missing))
        return ingest

    try:
        weather = preprocess(uploaded.table, mapping).df
    except Exception as exc:  # noqa: BLE001 - any failure to clean the table is shown as 'unreadable'
        ingest.problem = wording.D_UPLOAD_UNREADABLE.format(detail=str(exc).rstrip("."))
        return ingest

    ingest.load_result = LoadResult(uploaded=uploaded, weather=weather, validation=run_all_validations(weather))
    ingest.rows = len(weather)
    ingest.source_label = (
        wording.D_SOURCE_PVGIS if "pvgis" in content.decode("utf-8", "ignore").lower() else wording.D_SOURCE_OTHER
    )
    steps = weather.index.to_series().diff().dropna()
    ingest.hourly = bool((steps == steps.iloc[0]).all() and steps.iloc[0].total_seconds() == 3600) if len(steps) else True
    ingest.tiers = {
        1: validate_structure(weather),
        2: validate_physical_ranges(weather),
        3: validate_full_year_if_applicable(weather),
    }
    ingest.header_offset = detect_time_offset(uploaded.preamble)
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    ingest.site_found = dict(site.values)
    ingest.site_missing = list(site.missing)
    return ingest


def ingest_stored(stored_path: str, filename: str) -> Ingest:
    """Rebuild the report on a file already in the upload store."""
    return ingest_upload(Path(stored_path).read_bytes(), filename, root=Path(stored_path).parent)


def tier_summary(tiers: dict[int, ValidationResult]) -> tuple[bool, int, int]:
    """(all passed, problem count, warning count) over the tiers given."""
    problems = sum(len(r.problems) for r in tiers.values())
    warnings = sum(len(r.warnings) for r in tiers.values())
    return all(r.passed for r in tiers.values()), problems, warnings


# --- The form ------------------------------------------------------------------------------


@dataclass
class Form:
    """Everything page 1 collects. None means 'not entered'."""

    name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    elevation: float | None = None
    site_sources: dict[str, str] = field(default_factory=dict)
    offset_choice: str = "header"
    offset_reason: str = ""
    tilt: float | None = None
    azimuth: float | None = None
    albedo: float | None = 0.2
    mounting_geometry: str | None = None  # None = the pre-filled default
    mounting_construction: str | None = None
    module: str | None = None
    inverter: str | None = None
    modules_per_string: int | None = None
    strings_per_inverter: int | None = None
    module_height_m: float | None = None


def offset_for(form: Form, ingest: Ingest) -> TimeOffset:
    """The offset to use, with its true source: the file's own value keeps its file
    source; anything else is the user's, with the reason they gave."""
    header = ingest.header_offset
    assert header is not None
    if form.offset_choice == "header":
        return TimeOffset(header.value_h, header.source, header.notice)
    value = 0.0 if form.offset_choice == "hour_start" else 0.5
    return TimeOffset(value, TAG_USER_ENTERED, override_reason=form.offset_reason.strip() or None)


def offset_labels(ingest: Ingest) -> dict[str, str]:
    header = ingest.header_offset
    header_label = (
        wording.D_OFFSET_HEADER_ABSENT
        if header is None or header.source == TAG_ASSUMED_ABSENT
        else wording.D_OFFSET_HEADER.format(value=header.value_h)
    )
    return {
        "header": header_label,
        "hour_start": wording.D_OFFSET_START,
        "hour_centre": wording.D_OFFSET_CENTRE,
    }


def _number_ok(value: float | None, low: float, high: float) -> bool:
    return value is not None and low <= value <= high


def blockers(form: Form, ingest: Ingest | None, tier4_ready: bool = True) -> list[str]:
    """Plain-words reasons Continue is not available yet; empty when it is."""
    reasons: list[str] = []
    if not form.name.strip():
        reasons.append(wording.D_NEED_NAME)
    if ingest is None:
        reasons.append(wording.D_NEED_FILE)
        return reasons
    if not ingest.usable:
        reasons.append(ingest.problem or wording.D_NEED_FILE)
        return reasons
    failed = [wording.D_TIER_NAMES[t] for t, r in ingest.tiers.items() if not r.passed]
    if failed:
        reasons.append(wording.D_NEED_TIERS.format(tiers=", ".join(failed)))
    if not _number_ok(form.latitude, -90, 90):
        reasons.append(wording.D_NEED_LAT)
    if not _number_ok(form.longitude, -180, 180):
        reasons.append(wording.D_NEED_LON)
    if form.offset_choice != "header" and not form.offset_reason.strip():
        reasons.append(wording.D_NEED_REASON)
    if not _number_ok(form.tilt, 0, 90):
        reasons.append(wording.D_NEED_TILT)
    if not _number_ok(form.azimuth, 0, 360):
        reasons.append(wording.D_NEED_AZIMUTH)
    if not _number_ok(form.albedo, 0, 1):
        reasons.append(wording.D_NEED_ALBEDO)
    if not form.module:
        reasons.append(wording.D_NEED_MODULE)
    if not form.inverter:
        reasons.append(wording.D_NEED_INVERTER)
    if not form.modules_per_string or form.modules_per_string < 1:
        reasons.append(wording.D_NEED_MODULES)
    if not form.strings_per_inverter or form.strings_per_inverter < 1:
        reasons.append(wording.D_NEED_STRINGS)
    if form.module_height_m is None or form.module_height_m <= 0:
        reasons.append(wording.D_NEED_HEIGHT)
    return reasons


def offset_counts(ingest: Ingest, form: Form) -> tuple[OffsetCandidate, ...] | None:
    """Day/night mismatch counts for the three offset choices, or None until the
    coordinates are valid. Solar position is computed once per call: callers cache."""
    if not (_number_ok(form.latitude, -90, 90) and _number_ok(form.longitude, -180, 180)):
        return None
    site = _site_metadata(form, ingest)
    header_h = ingest.header_offset.value_h if ingest.header_offset else 0.0
    return offset_consistency_report(
        ingest.load_result.weather,
        site,
        {"header": header_h, "hour_start": 0.0, "hour_centre": 0.5},
        load_defaults(),
    )


def tier4_result(ingest: Ingest, form: Form) -> ValidationResult | None:
    """Tier 4 (day and night consistency) for the chosen offset, or None until the
    coordinates are valid. It needs the sun's position, so it waits for the site."""
    if not (_number_ok(form.latitude, -90, 90) and _number_ok(form.longitude, -180, 180)):
        return None
    ctx = build_site_context(
        ingest.load_result.weather, _site_metadata(form, ingest), offset_for(form, ingest), load_defaults()
    )
    return validate_physical_consistency(
        ingest.load_result.weather, ctx.solpos["zenith"], ctx.zenith_start, ctx.zenith_end
    )


def _site_metadata(form: Form, ingest: Ingest):
    site = detect_site_metadata(ingest.load_result.uploaded.preamble, ingest.load_result.uploaded.table)
    for name, value in (("latitude", form.latitude), ("longitude", form.longitude), ("elevation", form.elevation)):
        if value is None:
            continue
        if site.sources.get(name) == "From CSV" and site.values.get(name) == value:
            continue
        site.set_user_value(name, value)
    return site


# --- Saving ------------------------------------------------------------------------------------


@dataclass
class Committed:
    analysis_id: str
    site_result: SiteStepResult
    inputs: dict


def build_config(form: Form, ingest: Ingest) -> AnalysisConfig:
    """An AnalysisConfig for page 1: the pipelines are chosen on page 2, so none yet."""
    offset = offset_for(form, ingest)
    return AnalysisConfig(
        name=form.name.strip(),
        weather_file=ingest.stored_path,
        offset_value_h=offset.value_h,
        offset_reason=offset.override_reason or "",
        tilt_deg=float(form.tilt),
        azimuth_deg=float(form.azimuth),
        albedo=None if form.albedo == 0.2 else form.albedo,
        mounting_geometry=form.mounting_geometry,
        mounting_construction=form.mounting_construction,
        module_height_m=float(form.module_height_m),
        module_name=str(form.module),
        inverter_name=str(form.inverter),
        modules_per_string=int(form.modules_per_string),
        strings_per_inverter=int(form.strings_per_inverter),
        pipelines={},
        reexecution=None,
    )


def commit_page1(
    form: Form, ingest: Ingest, analysis_id: str | None = None, tau: Tau | None = None
) -> Committed:
    """Run the site step and the hardware lookup, then save the analysis as 'load_done'
    and 'site_done' with the same save function and inputs shape as the command line.
    Raises AnalysisError with a message the page shows in plain words."""
    defaults = load_defaults()
    tau = tau or resolve_tau(None, defaults)
    config = build_config(form, ingest)
    offset = offset_for(form, ingest)
    site = _site_metadata(form, ingest)

    site_result = step_site_and_offset(ingest.load_result, config, defaults, tau, offset=offset, site=site)
    step_hardware(ingest.load_result, site_result, config, defaults)  # the hardware must load

    analysis_id = analysis_id or uuid.uuid4().hex
    stored = str(Path(ingest.stored_path).resolve().relative_to(ROOT)) if Path(ingest.stored_path).resolve().is_relative_to(ROOT) else ingest.stored_path
    inputs = build_inputs_dict(config, tau, offset_source=offset.source)
    inputs["weather_file"] = stored
    inputs["time_offset"]["choice"] = form.offset_choice
    inputs["weather"] = weather_block(ingest.stored_path, ingest.load_result, stored_path=stored)
    inputs["weather"]["name"] = ingest.name
    save_analysis(analysis_id, config.name, "load_done", inputs)
    inputs["location"] = location_block(site_result.ctx)
    save_analysis(analysis_id, config.name, "site_done", inputs)
    return Committed(analysis_id=analysis_id, site_result=site_result, inputs=inputs)


def plain_failure(exc: Exception) -> str:
    text = str(exc)
    if "failed:" in text:
        text = text.split("failed:", 1)[1].strip()
    return wording.D_SETUP_FAILED.format(detail=text.rstrip("."))


__all__ = [
    "OFFSET_CHOICES",
    "AnalysisError",
    "Committed",
    "Form",
    "Ingest",
    "blockers",
    "build_config",
    "commit_page1",
    "file_sha256",
    "ingest_stored",
    "ingest_upload",
    "offset_counts",
    "offset_for",
    "offset_labels",
    "plain_failure",
    "tier4_result",
    "tier_summary",
]
