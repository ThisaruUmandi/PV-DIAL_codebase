"""Page 2 logic without Streamlit: the model pool for the chosen module, which options each
cell may offer given the others, validation, and saving.

The rules come from the registry and from Phase 3's own hybrid check, not from a copy:
- A cell lists only models the module and mounting allow, in pool order, never sorted.
- pvwatts_dc gives no DC voltage, so sandia/adr cannot follow it.
- Phase 3 builds mixed chains (one pipeline's DC with another's AC). A chain with pvwatts_dc
  and sandia/adr has no voltage, so such a pair could not be attributed. The page therefore
  does not offer a combination that would make any pair of the three incomputable.
- The module library decides the DC family (SAPM needs a Sandia module, single-diode a CEC
  one), so one comparison can never mix SAPM and single-diode (#18).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app import wording
from pvdials.analysis import AnalysisError
from pvdials.config import ROOT, load_defaults
from pvdials.dla.metrics import resolve_user_tau
from pvdials.dla.phase3 import pair_is_shapley_computable
from pvdials.physics.hardware import (
    ADR_INVERTER,
    CEC,
    CEC_INVERTER,
    load_inverter_database,
    load_module,
)
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.registry import (
    CandidateModel,
    stage1_pool_view,
    stage2_pool_view,
    stage3_pool_view,
    stage4_pool_view,
    stage5_pool_view,
    stage5_selectable,
)
from pvdials.provenance.analyses import save_analysis
from pvdials.types import PipelineConfig

LABELS = ("A", "B", "C")
STAGES = ("decomposition", "transposition", "temperature", "dc", "ac")
PVWATTS_DC = "pvwatts_dc"


# --- The pool for this module ----------------------------------------------------------------------


@dataclass(frozen=True)
class Pools:
    """Stages 1-4 as pool views (pool order, each candidate marked selectable or not with
    its reason). Stage 5 depends on the chosen DC model, so it is built per cell."""

    module: str
    inverter: str
    views: dict[str, tuple[CandidateModel, ...]]


@lru_cache(maxsize=2)
def _inverter_tables():
    return load_inverter_database(CEC_INVERTER), load_inverter_database(ADR_INVERTER)


@lru_cache(maxsize=8)
def pools_for(module: str, geometry: str | None, construction: str | None, inverter: str) -> Pools:
    mounting = resolve_mounting(geometry, construction, load_defaults())
    record = load_module(CEC, module)
    return Pools(
        module=module,
        inverter=inverter,
        views={
            "decomposition": stage1_pool_view(),
            "transposition": stage2_pool_view(),
            "temperature": stage3_pool_view(record, mounting),
            "dc": stage4_pool_view(record),
        },
    )


def _voltage_dependent_ac() -> tuple[str, ...]:
    """AC models that need a DC voltage, in pool order, found from the registry's own rule, not listed here."""
    cec, adr = _inverter_tables()
    names = []
    for candidate in stage5_pool_view(next(iter(cec.columns)), cec, adr, "singlediode_cec"):
        ok_without_voltage, _ = stage5_selectable(candidate.name, {CEC_INVERTER, ADR_INVERTER}, False)
        if candidate.selectable and not ok_without_voltage:
            names.append(candidate.name)
    return tuple(names)


def not_selectable(pools: Pools) -> list[tuple[str, str, str]]:
    """(stage, model, reason) for every pool model the module cannot use, with the registry's
    own reason, in pool order. AC models are decided by the DC model per cell, so none here."""
    return [
        (stage, c.name, c.reason or "")
        for stage in STAGES[:4]
        for c in pools.views[stage]
        if not c.selectable
    ]


# --- Options for one cell ---------------------------------------------------------------------------


@dataclass
class Options:
    """What each stage of one pipeline may offer, in pool order, with a plain note for any
    model left out because of this pipeline's other choices or another pipeline's."""

    models: dict[str, list[str]] = field(default_factory=dict)
    notes: dict[str, list[str]] = field(default_factory=dict)


def options(pools: Pools, column: dict[str, str | None], others: list[dict[str, str | None]]) -> Options:
    needs_voltage = _voltage_dependent_ac()
    out = Options({stage: [] for stage in STAGES}, {stage: [] for stage in STAGES})
    for stage in STAGES[:3]:
        out.models[stage] = [c.name for c in pools.views[stage] if c.selectable]

    own_ac = column.get("ac")
    other_ac_needs_voltage = any(o.get("ac") in needs_voltage for o in others)
    dc_models = [c.name for c in pools.views["dc"] if c.selectable]
    if PVWATTS_DC in dc_models and own_ac in needs_voltage:
        dc_models.remove(PVWATTS_DC)
        out.notes["dc"].append(wording.C_NOTE_DC_OWN_AC.format(ac=own_ac))
    elif PVWATTS_DC in dc_models and other_ac_needs_voltage:
        dc_models.remove(PVWATTS_DC)
        out.notes["dc"].append(wording.C_NOTE_DC_OTHER_AC)
    out.models["dc"] = dc_models

    cec, adr = _inverter_tables()
    own_dc = column.get("dc")
    # before a DC model is chosen, any voltage-giving model stands in for it
    ac_view = stage5_pool_view(pools.inverter, cec, adr, own_dc or "singlediode_cec")
    ac_models = [c.name for c in ac_view if c.selectable]
    other_without_voltage = any(o.get("dc") == PVWATTS_DC for o in others)
    removed = [m for m in ac_models if m in needs_voltage] if other_without_voltage else []
    if own_dc == PVWATTS_DC:
        out.notes["ac"].append(wording.C_NOTE_OWN_PVWATTS.format(names=" and ".join(needs_voltage)))
    elif removed:
        ac_models = [m for m in ac_models if m not in removed]
        out.notes["ac"].append(wording.C_NOTE_OTHER_PVWATTS.format(names=" and ".join(removed)))
    out.models["ac"] = ac_models
    return out


# --- Validation ---------------------------------------------------------------------------------------


def missing_stages(column: dict[str, str | None]) -> list[str]:
    return [stage for stage in STAGES if not column.get(stage)]


def to_pipeline_config(label: str, column: dict[str, str | None]) -> PipelineConfig:
    return PipelineConfig(
        label, column["decomposition"], column["transposition"], column["temperature"], column["dc"], column["ac"]
    )


def problems(pools: Pools, config: dict[str, dict[str, str | None]]) -> list[str]:
    """Plain-words reasons the configuration cannot be saved; empty when it can. The page
    prevents most of these by what it offers; this is the check behind it."""
    found = []
    for label in LABELS:
        gaps = missing_stages(config[label])
        if gaps:
            found.append(
                wording.C_CHECKLIST_PIPELINE.format(label=label) + f" ({wording.C_STILL_NEEDS.format(stages=', '.join(gaps))})"
            )
    if found:
        return found
    for label in LABELS:
        offered = options(pools, config[label], [config[o] for o in LABELS if o != label])
        for stage in STAGES:
            if config[label][stage] not in offered.models[stage]:
                found.append(f"{wording.C_COLUMN.format(label=label)} · {wording.C_STAGE_LABELS[stage]}: {config[label][stage]}")
    pipelines = {label: to_pipeline_config(label, config[label]) for label in LABELS}
    for a, b in (("A", "B"), ("A", "C"), ("B", "C")):
        computable, _ = pair_is_shapley_computable(pipelines[a], pipelines[b])
        if not computable:
            found.append(f"{a}-{b}: attribution not computable")
    return found


def differs(config: dict[str, dict[str, str | None]], stage: str) -> bool:
    chosen = {config[label].get(stage) for label in LABELS if config[label].get(stage)}
    return len(chosen) > 1


# --- The thesis example --------------------------------------------------------------------------------


def example_pipelines(path: Path | None = None) -> dict[str, dict[str, str]] | None:
    """A, B and C as written in analysis.yaml, or None if that file is not there."""
    path = path or ROOT / "analysis.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {label: dict(data["pipelines"][label]) for label in LABELS}


def usable_example(pools: Pools, example: dict[str, dict[str, str]]) -> tuple[dict, list[str]]:
    """The example as far as this module allows: a model that is not offered is left empty
    and named, never swapped for another."""
    config = {label: {stage: example[label].get(stage) for stage in STAGES} for label in LABELS}
    left_out = []
    for stage in STAGES:
        for label in LABELS:
            offered = options(pools, config[label], [config[o] for o in LABELS if o != label])
            if config[label][stage] not in offered.models[stage]:
                left_out.append(f"{wording.C_COLUMN.format(label=label)} {config[label][stage]}")
                config[label][stage] = None
    return config, left_out


# --- tau ---------------------------------------------------------------------------------------------------


def default_tau() -> float:
    return float(load_defaults()["dla"]["tau"])


def tau_problem(value) -> str | None:
    """None if value is a usable tau (a number above 0). That is the only check: nothing
    is said about the value itself."""
    if value is None:
        return wording.C_TAU_PROBLEM
    try:
        resolve_user_tau(float(value), load_defaults())
    except (TypeError, ValueError):
        return wording.C_TAU_PROBLEM
    return None


def tau_from_value(value: float) -> dict:
    """{'value', 'source'}: the default tag while the value is the default, user_entered once it differs."""
    return {"value": float(value), "source": "default" if float(value) == default_tau() else "user_entered"}


# --- Saving --------------------------------------------------------------------------------------------------


def commit_page2(
    analysis_id: str, inputs: dict, pools: Pools, config: dict[str, dict[str, str | None]], tau: dict
) -> dict:
    """Save the configuration and tau with the same save function the command line uses.
    Status 'pipelines_configured' (the pipelines are chosen, not yet run). Returns the inputs saved."""
    reasons = problems(pools, config)
    if reasons or tau_problem(tau["value"]):
        raise AnalysisError("; ".join([*reasons, *([tau_problem(tau["value"])] if tau_problem(tau["value"]) else [])]))
    saved = {**inputs, "pipelines": {label: {s: config[label][s] for s in STAGES} for label in LABELS}, "tau": tau}
    save_analysis(analysis_id, inputs["name"], "pipelines_configured", saved)
    return saved
