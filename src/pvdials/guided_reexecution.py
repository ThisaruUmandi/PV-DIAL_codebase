"""O4 (KT Step 10): guided re-execution.

Single-candidate substitution, never evaluate-all: at a pair's own localized
stage (Phase 1's k), the user is shown every pool-valid candidate at that
stage and picks exactly one to substitute and re-execute. Every attempt --
including a discarded retry -- is logged in provenance (ExecutionSet.REEXEC,
required for O2's reconstructibility), and the configuration under test is
always anchor + exactly one substitution: propose()/retry() only ever
substitute against the session's own frozen anchor_config, never against a
previous attempt, so chaining is structurally unreachable, not just
discouraged. A session is built from one specific pair and never exposes a
way to extract a substituted config for reuse elsewhere, so a substitution
discovered for one pair can't leak into a different pair's comparison
(track sealing).

No scored or sorted ordering is exposed here: alternatives() returns the
pool in pool order only, never sorted by disagreement or badged.

Never imports pvlib directly (KT §4) -- cec_inverters/adr_inverters are
passed in already-loaded, the same way stage5_pool_view() itself takes them.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pvdials.config import load_defaults
from pvdials.dla.phase1 import PairPhase1Result, run_phase1
from pvdials.physics.pipeline import PipelineResult, SharedInputs, run_pipeline
from pvdials.physics.registry import (
    CandidateModel,
    stage1_pool_view,
    stage2_pool_view,
    stage3_pool_view,
    stage4_pool_view,
    stage5_pool_view,
)
from pvdials.provenance.recorder import record as record_provenance
from pvdials.types import ExecutionSet, PipelineConfig, Stage

# The required disclaimer (O5): a disagreement change is an observation
# about this one substitution, never framed as success.
DISCLAIMER = (
    "This shows how disagreement changes with one substitution. It does not "
    "identify which configuration is preferable — that choice remains the user's."
)

_STAGE_FIELD: dict[Stage, str] = {
    Stage.DECOMPOSITION: "decomposition_model",
    Stage.TRANSPOSITION: "transposition_model",
    Stage.TEMPERATURE: "temperature_model",
    Stage.DC: "dc_model",
    Stage.AC: "ac_model",
}


class O4Error(Exception):
    """Raised when a candidate model isn't pool-valid at the session's stage."""


def stage_field(stage: Stage) -> str:
    """The PipelineConfig field name holding this stage's model choice."""
    return _STAGE_FIELD[stage]


def substitute_stage(
    anchor: PipelineConfig, stage: Stage, new_model: str, label: str
) -> PipelineConfig:
    """anchor with exactly one stage's model replaced. Not coalition-based
    (unlike Phase 3's build_derived_config) -- new_model is any pool-valid
    candidate at `stage`, not necessarily another pipeline's own choice.
    """
    fields = {
        Stage.DECOMPOSITION: anchor.decomposition_model,
        Stage.TRANSPOSITION: anchor.transposition_model,
        Stage.TEMPERATURE: anchor.temperature_model,
        Stage.DC: anchor.dc_model,
        Stage.AC: anchor.ac_model,
    }
    fields[stage] = new_model
    return PipelineConfig(
        label=label,
        decomposition_model=fields[Stage.DECOMPOSITION],
        transposition_model=fields[Stage.TRANSPOSITION],
        temperature_model=fields[Stage.TEMPERATURE],
        dc_model=fields[Stage.DC],
        ac_model=fields[Stage.AC],
    )


def _shared_for(config: PipelineConfig, shared_cec: SharedInputs, shared_adr: SharedInputs) -> SharedInputs:
    """Same inverter-library routing Phase 3 uses: 'adr' needs the
    ADRInverter-tagged SharedInputs, everything else uses the CEC one.
    """
    return shared_adr if config.ac_model == "adr" else shared_cec


def alternatives_at_stage(
    stage: Stage,
    anchor: PipelineConfig,
    shared_cec: SharedInputs,
    cec_inverters: pd.DataFrame,
    adr_inverters: pd.DataFrame,
) -> tuple[CandidateModel, ...]:
    """Every pool-valid candidate at `stage`, in pool order -- the full pool
    (Steps 3-6's own stageN_pool_view()), not just "the other pipeline's
    model". Uses anchor's own hardware/model context: module/mounting/
    inverter are shared, fixed hardware (D6, so identical whichever of
    shared_cec/shared_adr is read here); dc_model (for Stage 5's v_dc gate)
    comes from anchor's own choice, since only `stage` is being substituted.
    """
    if stage == Stage.DECOMPOSITION:
        return stage1_pool_view()
    if stage == Stage.TRANSPOSITION:
        return stage2_pool_view()
    if stage == Stage.TEMPERATURE:
        return stage3_pool_view(shared_cec.module, shared_cec.mounting)
    if stage == Stage.DC:
        return stage4_pool_view(shared_cec.module)
    if stage == Stage.AC:
        inverter_name = shared_cec.inverter.name if shared_cec.inverter is not None else None
        return stage5_pool_view(inverter_name, cec_inverters, adr_inverters, anchor.dc_model)
    raise ValueError(f"Unknown stage: {stage!r}")


@dataclass(frozen=True)
class ProposalResult:
    """One propose()/retry() attempt. Always anchor + exactly one
    substitution -- never a chain, since it's always built from the
    session's own frozen anchor_config, never from a previous attempt.
    """

    pair: tuple[str, str]
    candidate_model: str
    config: PipelineConfig
    result: PipelineResult
    phase1: PairPhase1Result


@dataclass(frozen=True)
class FinalRunResult:
    """The one final end-to-end run on confirmation."""

    pair: tuple[str, str]
    config: PipelineConfig
    result: PipelineResult
    annual_yield_kwh: float | None
    disclaimer: str = DISCLAIMER


def annual_yield_kwh(result: PipelineResult) -> float:
    """Annual yield over the FULL, unmasked AC series (every timestep,
    including correctly-zero night hours) -- the daylight mask exists to
    avoid zero-inflation in a *comparison*; an energy total needs every
    hour, or it silently undercounts real output at partial-daylight edges.

    Each row's duration is the gap to its own next timestamp (handles
    arbitrary-length/irregular uploads); the last row has no next
    timestamp, so it's assumed equal to the preceding interval.
    """
    p_ac = result.outputs.ac.outputs["p_ac"]
    index = p_ac.index
    if len(index) < 2:
        hours = pd.Series([1.0], index=index)
    else:
        gap_hours = (index[1:] - index[:-1]).total_seconds() / 3600.0
        hours = pd.Series([*gap_hours, gap_hours[-1]], index=index)
    energy_wh = float((p_ac.to_numpy() * hours.to_numpy()).sum())
    return energy_wh / 1000.0


@dataclass(frozen=True)
class O4Session:
    """One guided-re-execution session, sealed to one pair and one stage
    (Phase 1's k for that pair). anchor_config/other_config are always the
    pair's two ORIGINAL configs -- there is no method anywhere that takes a
    previous attempt as a new base, so chaining is structurally impossible,
    and no method exposes a substituted config for reuse in another pair's
    session, so a substitution can't leak across pairs (track sealing).
    """

    pair: tuple[str, str]
    anchor_config: PipelineConfig
    anchor_result: PipelineResult
    other_config: PipelineConfig
    other_result: PipelineResult
    stage: Stage
    shared_cec: SharedInputs
    shared_adr: SharedInputs
    cec_inverters: pd.DataFrame
    adr_inverters: pd.DataFrame
    daylight: pd.Series
    defaults: dict | None = None

    def alternatives(self) -> tuple[CandidateModel, ...]:
        return alternatives_at_stage(
            self.stage, self.anchor_config, self.shared_cec, self.cec_inverters, self.adr_inverters
        )

    def _validate(self, candidate_model: str) -> None:
        """Pool-valid-only is enforced here, inside the session -- not left
        as a separate function the caller has to remember to consult first.
        """
        valid_names = {c.name for c in self.alternatives() if c.selectable}
        if candidate_model not in valid_names:
            raise O4Error(
                f"'{candidate_model}' is not a pool-valid candidate at stage "
                f"{self.stage.name} for this session."
            )

    def _run_substitution(
        self, candidate_model: str, label_suffix: str, defaults: dict
    ) -> tuple[PipelineConfig, PipelineResult]:
        self._validate(candidate_model)
        label = f"{self.pair[0]}_{self.pair[1]}_{label_suffix}"
        config = substitute_stage(self.anchor_config, self.stage, candidate_model, label)
        shared = _shared_for(config, self.shared_cec, self.shared_adr)
        result = run_pipeline(config, shared, defaults)
        record_provenance(config, shared, result, ExecutionSet.REEXEC.value)
        return config, result

    def propose(self, candidate_model: str) -> ProposalResult:
        """First attempt at a substitution."""
        return self._propose_or_retry(candidate_model)

    def retry(self, candidate_model: str) -> ProposalResult:
        """A further attempt. Discards nothing because nothing was kept:
        this always substitutes against anchor_config, exactly like
        propose() -- never against the previous attempt's result.
        """
        return self._propose_or_retry(candidate_model)

    def _propose_or_retry(self, candidate_model: str) -> ProposalResult:
        defaults = self.defaults or load_defaults()
        config, result = self._run_substitution(candidate_model, "reexec", defaults)
        phase1 = run_phase1(
            config, result, self.other_config, self.other_result, self.daylight, defaults=defaults
        )
        return ProposalResult(
            pair=self.pair, candidate_model=candidate_model, config=config, result=result, phase1=phase1
        )

    def confirm(self, candidate_model: str, compute_yield: bool = False) -> FinalRunResult:
        """One final end-to-end run of candidate_model at this session's
        stage. Independent of any prior propose()/retry() call -- always a
        fresh run against anchor_config, recorded the same way.
        """
        defaults = self.defaults or load_defaults()
        config, result = self._run_substitution(candidate_model, "confirmed", defaults)
        yield_kwh = annual_yield_kwh(result) if compute_yield else None
        return FinalRunResult(pair=self.pair, config=config, result=result, annual_yield_kwh=yield_kwh)
