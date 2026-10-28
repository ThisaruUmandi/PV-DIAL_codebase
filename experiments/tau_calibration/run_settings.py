"""Run-level settings shared by the evaluation batch scripts (runs R1-R7,
Round 6 run plan): the time offset applied to the weather file, the radiation
database the file came from, and the tau the runs apply.

The offset is read from PVDIAL_OFFSET_H and tau from PVDIAL_TAU; unset means
0.0 h and configs/run_defaults.yaml's tau, the settings every existing output
was produced with, so a plain rerun reproduces it unchanged. Any other offset
writes to its own "<folder>_offset_<h>h" output folders, so the 0 h outputs
are never overwritten, and every output file carries run_record() so each
run holds its own evidence of the offset and tau it applied.

R1 runs first at a new offset (it doesn't apply tau, it selects it, and
writes tau_selection.json); every later script calls require_tau(), which
refuses to run unless PVDIAL_TAU is the tau R1 selected at that offset.

One exception, the sensitivity run (PVDIAL_SENSITIVITY=1): step4's
all-pairs Phase 1 at a non-zero offset with the 0 h tau, so the effect of
the offset alone can be shown beside the main result. It is allowed only
with PVDIAL_TAU set to that 0 h tau, is marked in run_record(), and writes
to its own "<folder>_offset_<h>h_tau_<tau>" folders.

Lives in this folder, not experiments/evaluation/, because the scripts here
run standalone with only their own directory on sys.path; the evaluation
scripts, run with -m from the repo root, import it as
experiments.tau_calibration.run_settings.

    PVDIAL_OFFSET_H=0.5 caffeinate -i python3 -u experiments/tau_calibration/trivial_plateau_amendment_exhaustive.py
    PVDIAL_OFFSET_H=0.5 PVDIAL_TAU=<R1's tau> caffeinate -i python3 -u -m experiments.evaluation.<script>
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pvdials.config import load_defaults
from pvdials.data.column_mapper import TAG_USER_ENTERED, TimeOffset, detect_time_offset
from pvdials.dla.metrics import Tau

# Confirmed 28/10: a PVGIS 5.2 TMY download (PVGIS-ERA5, 2005-2020) for the
# Colombo coordinates is identical, row for row, to the thesis file.
RADIATION_DATABASE = "PVGIS-ERA5"
OFFSET_ENV = "PVDIAL_OFFSET_H"
OFFSET_H = float(os.environ.get(OFFSET_ENV, "0.0"))
OFFSET_SET = OFFSET_ENV in os.environ

TAU_ENV = "PVDIAL_TAU"
TAU_SOURCE_LABEL = f"run setting {TAU_ENV}"
TAU_SET = TAU_ENV in os.environ
ZERO_H_TAU = float(load_defaults()["dla"]["tau"])  # the tau every 0 h run applied
TAU = float(os.environ[TAU_ENV]) if TAU_SET else ZERO_H_TAU
# The 0 h stable band (exhaustive R1, 28/09) predates tau_selection.json.
ZERO_H_STABLE_BAND = (0.088, 0.098)

SENSITIVITY_ENV = "PVDIAL_SENSITIVITY"
SENSITIVITY = os.environ.get(SENSITIVITY_ENV) == "1"


def time_offset(preamble: list[str], offset_h: float = OFFSET_H) -> TimeOffset:
    """offset_h as the TimeOffset to build the site context with: the file's
    own header value when they agree, otherwise a user-entered override
    naming the header value. At 0.0 h this is exactly the override every
    existing run used ("header states 0.5 h; file day/night content aligns
    with 0 h").
    """
    header = detect_time_offset(preamble)
    if offset_h == header.value_h:
        return header
    reason = (
        f"header states {header.value_h:g} h; file day/night content aligns with 0 h"
        if offset_h == 0.0
        else f"header states {header.value_h:g} h; run uses {offset_h:g} h"
    )
    return TimeOffset(offset_h, TAG_USER_ENTERED, override_reason=reason)


def output_dir(base: Path, offset_h: float = OFFSET_H, tau_specific: bool = True) -> Path:
    """base itself at 0 h (the existing outputs); a sibling folder otherwise,
    with a _tau_<tau> suffix for a sensitivity run's tau-specific outputs.
    tau_specific=False for outputs that don't depend on tau (R1's cache and
    selection), which a sensitivity run reads from the offset's own folder."""
    if offset_h == 0.0:
        return base
    name = f"{base.name}_offset_{offset_h:g}h"
    return base.with_name(f"{name}_tau_{TAU:g}" if tau_specific and SENSITIVITY else name)


def sensitivity_dir(base: Path) -> Path:
    """Where this offset's sensitivity run (0 h tau) wrote base's outputs."""
    return base.with_name(f"{base.name}_offset_{OFFSET_H:g}h_tau_{ZERO_H_TAU:g}")


TAU_SELECTION_FILE = (
    output_dir(Path(__file__).parent / "outputs" / "trivial_plateau_amendment", tau_specific=False) / "tau_selection.json"
)


def tau_selection() -> dict | None:
    """R1's tau selection at this offset (None before R1 has run)."""
    return json.loads(TAU_SELECTION_FILE.read_text()) if TAU_SELECTION_FILE.exists() else None


def require_tau(allow_sensitivity: bool = False) -> None:
    """For every script that applies tau. At a non-zero offset, the 0 h
    default must not be used by accident, and PVDIAL_TAU must be the tau R1
    selected at that offset -- except in a sensitivity run, which only
    allow_sensitivity scripts (step4's all-pairs part) accept, and only with
    the 0 h tau."""
    if SENSITIVITY:
        if not allow_sensitivity:
            raise SystemExit(f"STOP: {SENSITIVITY_ENV}=1 is only for step4's all-pairs Phase 1, not this script.")
        if OFFSET_H == 0.0:
            raise SystemExit(f"STOP: the sensitivity run is the 0 h tau at a non-zero offset -- set {OFFSET_ENV}.")
        if not TAU_SET or TAU != ZERO_H_TAU:
            raise SystemExit(f"STOP: the sensitivity run applies the 0 h tau -- set {TAU_ENV}={ZERO_H_TAU:g}.")
        if tau_selection() is None:
            raise SystemExit(f"STOP: no {TAU_SELECTION_FILE.name} -- run R1 at {OFFSET_H:g} h first.")
        return
    if OFFSET_H == 0.0:
        return
    selection = tau_selection()
    if selection is None:
        raise SystemExit(f"STOP: no {TAU_SELECTION_FILE.name} -- run R1 at {OFFSET_H:g} h first.")
    if selection["default"] is None:
        raise SystemExit(f"STOP: R1 at {OFFSET_H:g} h found no stable band -- report before continuing (run plan).")
    if not TAU_SET:
        raise SystemExit(f"STOP: set {TAU_ENV}={selection['default']['centre']:g} (R1's tau at {OFFSET_H:g} h).")
    if abs(TAU - selection["default"]["centre"]) > 1e-9:
        raise SystemExit(f"STOP: {TAU_ENV}={TAU:g}, but R1 selected {selection['default']['centre']:g} at {OFFSET_H:g} h.")


def stable_band() -> tuple[float, float]:
    """R1's selected stable tau band at this offset (in a sensitivity run too:
    the band is a property of the offset's data, not of the tau applied)."""
    if OFFSET_H == 0.0:
        return ZERO_H_STABLE_BAND
    require_tau(allow_sensitivity=True)
    default = tau_selection()["default"]
    return (default["lo"], default["hi"])


def run_defaults() -> dict:
    """load_defaults() with dla.tau set to this run's TAU -- every tau the
    experiment code applies with record=False is read from this dict."""
    defaults = load_defaults()
    defaults["dla"]["tau"] = TAU
    return defaults


def _tau_reference() -> str | None:
    """R1's selection file and its sha256, so a record names exactly what its tau came from."""
    if not TAU_SELECTION_FILE.exists():
        return None
    digest = hashlib.sha256(TAU_SELECTION_FILE.read_bytes()).hexdigest()
    return f"{TAU_SELECTION_FILE.relative_to(Path(__file__).resolve().parents[2])} (sha256 {digest})"


def tau_override() -> Tau | None:
    """PVDIAL_TAU as the Tau for production code that records provenance
    (run_analysis, O4): its own source label and reference, not "default".
    None when PVDIAL_TAU is unset -- the default path, exactly as before."""
    return Tau(TAU, TAU_SOURCE_LABEL, _tau_reference()) if TAU_SET else None


def site_tau_kwargs() -> dict:
    """The same override for build_site_context(), whose settings every
    provenance record's site_context carries; {} when PVDIAL_TAU is unset."""
    tau = tau_override()
    return {} if tau is None else {"tau": tau.value, "tau_source": tau.source, "tau_reference": tau.reference}


def tau_record() -> dict:
    record = {"tau": TAU, "tau_source": TAU_SOURCE_LABEL if TAU_SET else "configs/run_defaults.yaml"}
    # Only a sensitivity run is marked, so every other run's record is unchanged.
    return {**record, "run_kind": "sensitivity (0 h tau at this offset)"} if SENSITIVITY else record


def run_record(ctx, with_tau: bool = True) -> dict:
    """The offset a run actually applied, read back from its SiteContext
    (not from OFFSET_H), plus the radiation database and, for runs that
    apply one, tau."""
    record = {
        "time_offset_h": ctx.time_offset_h,
        "time_offset_source": ctx.settings["time_offset_source"],
        "radiation_database": RADIATION_DATABASE,
    }
    return {**record, **tau_record()} if with_tau else record
