"""Researcher-authored mapping of candidate models to stages.

pvlib has no stage metadata: which function belongs to which stage, and
whether it fits that stage's slot, is decided here by the researcher.
Pools are tuples in a fixed POOL ORDER. Nothing here sorts or ranks.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pvdials.physics.hardware import (
    ADR_INVERTER,
    CEC,
    CEC_INVERTER,
    SANDIA,
    ModuleRecord,
    has_noct,
    inverter_libraries,
)
from pvdials.physics.mounting import Mounting, sapm_key
from pvdials.types import Stage


@dataclass(frozen=True)
class CandidateModel:
    """One candidate model for a stage.

    reason: plain statement of why a model can't be selected; None if selectable.
    """

    name: str
    stage: Stage
    selectable: bool = True
    reason: str | None = None


def _selectable(name: str, stage: Stage) -> CandidateModel:
    return CandidateModel(name, stage)


def _shown(name: str, stage: Stage, reason: str) -> CandidateModel:
    return CandidateModel(name, stage, selectable=False, reason=reason)


_S1 = Stage.DECOMPOSITION
_S2 = Stage.TRANSPOSITION
_S3 = Stage.TEMPERATURE
_S4 = Stage.DC
_S5 = Stage.AC

# Reasons for the module- and mounting-dependent Stage 3 models (see stage3_selectable)
NO_NOCT_REASON = "needs the module's NOCT; the selected module's library doesn't carry it"
NO_SAPM_MOUNTING_REASON = "no SAPM coefficient set for this mounting/construction combination"

# Reasons for the module-dependent Stage 4 models (see stage4_selectable)
NO_SAPM_MODULE_REASON = (
    "needs SAPM's own characterisation fields; the selected module's library doesn't carry them"
)
NO_CEC_MODULE_REASON = (
    "needs CEC single-diode reference parameters; the selected module's library doesn't carry them"
)

# Reasons for the runtime-gated Stage 5 models (see stage5_selectable)
NO_V_DC_REASON = "needs v_dc; the selected DC model doesn't produce it"
NO_CEC_INVERTER_REASON = "needs a CECInverter entry; the selected inverter isn't in that database"
NO_ADR_INVERTER_REASON = "needs an ADRInverter entry; the selected inverter isn't in that database"

# Stage 1 fit check, 23/09: Stage 1 takes GHI (plus the shared site context) only.
# Stage 2 fit check, 23/09: get_total_irradiance() forwards dni_extra/airmass only to
# the models that need them, so one uniform call fits every candidate — no misfits.
# Stage 3 fit check, 23/09 (KT §7.2 order): faiman_rad needs IR(h), not in a PVGIS file;
# generic_linear needs per-installation heat-loss coefficients with no defensible
# default; prilliman corrects another model's output, not a standalone candidate.
# fuentes/noct_sam/ross are module-dependent (need NOCT) and sapm_cell is
# mounting-dependent — both checked per run by stage3_selectable(), not here.
STAGE_POOLS: dict[Stage, tuple[CandidateModel, ...]] = {
    Stage.DECOMPOSITION: (
        _selectable("erbs", _S1),
        _selectable("erbs_driesse", _S1),
        _selectable("disc", _S1),
        _selectable("dirint", _S1),
        _shown("dirindex", _S1, "needs clear-sky GHI and DNI; not derivable from GHI alone"),
        _selectable("boland", _S1),
        _selectable("louche", _S1),
        _selectable("orgill_hollands", _S1),
        _shown("campbell_norman", _S1, "needs atmospheric transmittance, not GHI"),
        _shown("gti_dirint", _S1, "needs plane-of-array irradiance, not GHI"),
    ),
    Stage.TRANSPOSITION: (
        _selectable("isotropic", _S2),
        _selectable("klucher", _S2),
        _selectable("haydavies", _S2),
        _selectable("reindl", _S2),
        _selectable("king", _S2),
        _selectable("perez", _S2),
        _selectable("perez-driesse", _S2),
    ),
    Stage.TEMPERATURE: (
        _selectable("faiman", _S3),
        _shown("faiman_rad", _S3, "needs downwelling longwave irradiance (IR(h)); not provided by this file"),
        _selectable("fuentes", _S3),
        _shown(
            "generic_linear",
            _S3,
            "needs heat-loss coefficients fitted per installation; no defensible default",
        ),
        _selectable("noct_sam", _S3),
        _shown("prilliman", _S3, "corrects another model's output; not a standalone temperature model"),
        _selectable("pvsyst_cell", _S3),
        _selectable("ross", _S3),
        _selectable("sapm_cell", _S3),
    ),
    # Stage 4 fit check, 23/09: singlediode_pvsyst needs gamma_ref/mu_gamma/R_sh_0,
    # carried by neither CECMod nor SandiaMod — a static exclusion, not module-gated.
    # pvwatts_dc/sapm/singlediode_desoto/singlediode_cec are module-library-gated,
    # checked per run by stage4_selectable(), not here (N38 closed the SandiaMod
    # pvwatts_dc gap, so pvwatts_dc itself has no static exclusion).
    Stage.DC: (
        _selectable("pvwatts_dc", _S4),
        _selectable("sapm", _S4),
        _selectable("singlediode_desoto", _S4),
        _selectable("singlediode_cec", _S4),
        _shown(
            "singlediode_pvsyst",
            _S4,
            "needs gamma_ref, mu_gamma, R_sh_0; not carried by CECMod or SandiaMod",
        ),
    ),
    # Stage 5 fit check, 23/09: all three are selectable in the static pool — the
    # gating is entirely runtime (which database(s) carry the chosen inverter name,
    # and whether the upstream DC model produced v_dc), checked by stage5_selectable().
    Stage.AC: (
        _selectable("sandia", _S5),
        _selectable("adr", _S5),
        _selectable("pvwatts", _S5),
    ),
}

# Stage 3 models gated by the module's NOCT, applying the same rule Umee gave for
# fuentes/noct_sam to ross too (23/09): ross needs noct or k, and k has no source
# anywhere in this project.
_NOCT_GATED_MODELS = {"fuentes", "noct_sam", "ross"}

# Stage 4 models gated by which module library was selected
_SANDIA_GATED_MODELS = {"sapm"}
_CEC_GATED_MODELS = {"singlediode_desoto", "singlediode_cec"}


def stage_pool(stage: Stage) -> tuple[CandidateModel, ...]:
    """All candidates for a stage, selectable or not, in pool order."""
    return STAGE_POOLS[stage]


def get_candidate(stage: Stage, name: str) -> CandidateModel | None:
    for candidate in STAGE_POOLS[stage]:
        if candidate.name == name:
            return candidate
    return None


def stage3_selectable(
    model: str, module: ModuleRecord, mounting: Mounting
) -> tuple[bool, str | None]:
    """Module- and mounting-dependent Stage 3 selectability, layered on the static pool.

    Assumes `model` already passed the static pool check (get_candidate).
    """
    if model in _NOCT_GATED_MODELS and not has_noct(module):
        return False, NO_NOCT_REASON
    if model == "sapm_cell" and sapm_key(mounting) is None:
        return False, NO_SAPM_MOUNTING_REASON
    return True, None


def stage4_selectable(model: str, module: ModuleRecord) -> tuple[bool, str | None]:
    """Module-library-dependent Stage 4 selectability, layered on the static pool.

    Assumes `model` already passed the static pool check (get_candidate).
    """
    if model in _SANDIA_GATED_MODELS and module.library != SANDIA:
        return False, NO_SAPM_MODULE_REASON
    if model in _CEC_GATED_MODELS and module.library != CEC:
        return False, NO_CEC_MODULE_REASON
    return True, None


_NEEDS_V_DC_MODELS = {"sandia", "adr"}


def stage5_selectable(
    model: str, inverter_libraries: set[str], dc_has_v_dc: bool
) -> tuple[bool, str | None]:
    """Runtime Stage 5 selectability, layered on the static pool (all 3 selectable).

    Assumes `model` already passed the static pool check (get_candidate).
    """
    if model in _NEEDS_V_DC_MODELS and not dc_has_v_dc:
        return False, NO_V_DC_REASON
    if model == "sandia" and CEC_INVERTER not in inverter_libraries:
        return False, NO_CEC_INVERTER_REASON
    if model == "adr" and ADR_INVERTER not in inverter_libraries:
        return False, NO_ADR_INVERTER_REASON
    return True, None


# --- Step 6: pool validity (KT §7.5) ----------------------------------------------
#
# Filter 1 (stage applicability) and filter 3 (parameter availability) are the
# static pool and the stageN_selectable() functions above, already built as each
# stage needed them. What's added here: filter 2 (cross-stage compatibility, the
# only known case in this project), and one merged "pool view" per stage that
# combines both filters into the single call a picker screen actually needs —
# every candidate, in pool order, already annotated with why it can't be chosen.

# KT §7.5, filter 2 — the only known cross-stage case in this project (checked
# against dc.py, 24/09): pvwatts_dc is the only Stage 4 model with no v_dc.
STAGE4_PRODUCES_V_DC: dict[str, bool] = {
    "pvwatts_dc": False,
    "sapm": True,
    "singlediode_desoto": True,
    "singlediode_cec": True,
}


def dc_model_produces_v_dc(model: str) -> bool:
    """Whether this Stage 4 model produces v_dc (KT §7.5, filter 2).

    This is the declared fact, used before Stage 4 has run (e.g. by a picker
    screen deciding whether to show sandia/adr as selectable). ac.py's own
    runtime check ("v_dc" in dc_result.outputs.columns) stays as a defensive
    backstop on what actually happened; a test ties the two together.
    """
    return STAGE4_PRODUCES_V_DC[model]


def _merge(candidate: CandidateModel, ok: bool, reason: str | None) -> CandidateModel:
    """Demote a statically-selectable candidate if the dynamic check fails.

    Never promotes a statically-excluded one — stageN_selectable() already
    assumes the static check passed, same as every adapter's own check.
    """
    if candidate.selectable and not ok:
        return CandidateModel(candidate.name, candidate.stage, selectable=False, reason=reason)
    return candidate


def stage1_pool_view() -> tuple[CandidateModel, ...]:
    """Stage 1 has no dynamic gate; the static pool already reflects everything."""
    return stage_pool(Stage.DECOMPOSITION)


def stage2_pool_view() -> tuple[CandidateModel, ...]:
    """Stage 2 has no dynamic gate (confirmed 23/09: zero misfits)."""
    return stage_pool(Stage.TRANSPOSITION)


def stage3_pool_view(module: ModuleRecord, mounting: Mounting) -> tuple[CandidateModel, ...]:
    """The whole Stage 3 pool, in pool order, with the module/mounting gate applied."""
    return tuple(
        _merge(c, *stage3_selectable(c.name, module, mounting)) if c.selectable else c
        for c in stage_pool(Stage.TEMPERATURE)
    )


def stage4_pool_view(module: ModuleRecord) -> tuple[CandidateModel, ...]:
    """The whole Stage 4 pool, in pool order, with the module-library gate applied."""
    return tuple(
        _merge(c, *stage4_selectable(c.name, module)) if c.selectable else c
        for c in stage_pool(Stage.DC)
    )


def stage5_pool_view(
    inverter_name: str,
    cec_inverters: pd.DataFrame,
    adr_inverters: pd.DataFrame,
    dc_model: str,
) -> tuple[CandidateModel, ...]:
    """The whole Stage 5 pool, in pool order, given the plain inverter name and
    the already-chosen DC model — no DC adapter run required to know whether
    sandia/adr are selectable (filter 2, cross-stage compatibility).
    """
    libraries = inverter_libraries(inverter_name, cec_inverters, adr_inverters)
    dc_has_v_dc = dc_model_produces_v_dc(dc_model)
    return tuple(
        _merge(c, *stage5_selectable(c.name, libraries, dc_has_v_dc)) if c.selectable else c
        for c in stage_pool(Stage.AC)
    )
