"""Researcher-authored mapping of candidate models to stages.

pvlib has no stage metadata: which function belongs to which stage, and
whether it fits that stage's slot, is decided here by the researcher.
Pools are tuples in a fixed POOL ORDER. Nothing here sorts or ranks.
"""

from __future__ import annotations

from dataclasses import dataclass

from pvdials.physics.hardware import CEC, SANDIA, ModuleRecord, has_noct
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
