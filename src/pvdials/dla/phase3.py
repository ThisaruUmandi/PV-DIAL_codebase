"""Phase 3 (KT Step 9): Shapley-value contribution quantification.

Attributes how much of the total A-vs-B disagreement (measured at final AC
output) each of the 5 stages contributes, via Shapley's (1953, eq. 13)
cooperative-game value. Players = the 5 stages; a coalition T subset of
stages is a derived pipeline where T's stages take the "other" config's
model and the rest keep the anchor's (build_derived_config). v(T) = plain
(non-normalized) RMSD at final AC between that derived pipeline's output and
a fixed anchor pipeline's output (N1) -- never dla.metrics' pooled nRMSD,
which doesn't apply here.

Anchor dependence (v, and so phi, isn't symmetric in which pipeline is
called the coalition's empty baseline) is handled by computing the whole
decomposition twice -- once anchored at A, once at B -- and averaging the
two signed results. Both directional values are always kept and reported,
never discarded: a gap between them is itself a finding (stage interaction),
not noise.

N32 (Shapley's own efficiency axiom: sum of phi = v(S) - v(empty) = v(S)
here, since v(empty)=0 by construction) is enforced only as a unit test
(tests/dla/test_phase3.py) -- a violation beyond float tolerance would only
ever mean a code bug, never a legitimate research finding, so nothing here
asserts it at runtime.

Never imports pvlib (KT §4) -- everything here operates on already-computed
PipelineResults, or triggers new ones via the real run_pipeline(), never on
raw physics inputs directly.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import pandas as pd

from pvdials.config import load_defaults
from pvdials.dla.metrics import stage_series
from pvdials.physics.hardware import ADR_INVERTER, CEC_INVERTER
from pvdials.physics.pipeline import PipelineResult, SharedInputs, run_pipeline
from pvdials.physics.registry import dc_model_produces_v_dc, stage5_selectable
from pvdials.provenance.recorder import record as record_provenance
from pvdials.types import ExecutionSet, PipelineConfig, Stage

ALL_STAGES: tuple[Stage, ...] = tuple(Stage)

_STAGE_FIELD: dict[Stage, str] = {
    Stage.DECOMPOSITION: "decomposition_model",
    Stage.TRANSPOSITION: "transposition_model",
    Stage.TEMPERATURE: "temperature_model",
    Stage.DC: "dc_model",
    Stage.AC: "ac_model",
}

NOT_COMPUTABLE_REASON = "not computable — DC/AC hybrid invalidity"


def stage_field(stage: Stage) -> str:
    """The PipelineConfig field name holding this stage's model choice."""
    return _STAGE_FIELD[stage]


def build_derived_config(
    config_a: PipelineConfig, config_b: PipelineConfig, coalition: frozenset[Stage], label: str
) -> PipelineConfig:
    """The pipeline for coalition T: stages in T take config_b's model, the
    rest take config_a's. T=empty reproduces config_a exactly; T=all 5
    stages reproduces config_b exactly.
    """
    fields = {}
    for stage in ALL_STAGES:
        field = stage_field(stage)
        source = config_b if stage in coalition else config_a
        fields[field] = getattr(source, field)
    return PipelineConfig(label=label, **fields)


def all_coalitions(stages: tuple[Stage, ...] = ALL_STAGES) -> tuple[frozenset[Stage], ...]:
    """Every subset of stages (the full 2^5=32-member powerset), ordered by
    size then combination order -- deterministic, so callers can rely on it.
    """
    coalitions = []
    for size in range(len(stages) + 1):
        for combo in itertools.combinations(stages, size):
            coalitions.append(frozenset(combo))
    return tuple(coalitions)


def coalition_is_pool_valid(
    config_a: PipelineConfig, config_b: PipelineConfig, coalition: frozenset[Stage]
) -> bool:
    """Whether this coalition's derived pipeline is pool-valid.

    Uses stage5_selectable/dc_model_produces_v_dc directly (KT §7.5 filter
    2) rather than a re-derived copy, so this can never drift from
    tests/unit/test_pool_validity.py's own hybrid-validity table. Passes
    both inverter libraries as always-present: inverter-library availability
    is shared, fixed hardware (D6) and can't vary between coalitions -- any
    ac_model appearing here was already validated against the real inverter
    when config_a or config_b was itself built. The only thing that *can*
    vary between coalitions is the (dc_model, ac_model) pairing itself.
    """
    derived = build_derived_config(config_a, config_b, coalition, label="_hybrid_validity_check")
    dc_has_v_dc = dc_model_produces_v_dc(derived.dc_model)
    ok, _ = stage5_selectable(derived.ac_model, {CEC_INVERTER, ADR_INVERTER}, dc_has_v_dc)
    return ok


def pair_is_shapley_computable(
    config_a: PipelineConfig, config_b: PipelineConfig
) -> tuple[bool, list[frozenset[Stage]]]:
    """Whether every one of the 32 coalitions for this pair is pool-valid.

    Checked once, before any pipeline is run, so an invalid pair costs
    nothing beyond 32 cheap dict lookups.
    """
    invalid = [c for c in all_coalitions() if not coalition_is_pool_valid(config_a, config_b, c)]
    return not invalid, invalid


def _rmsd(series_a: pd.Series, series_b: pd.Series) -> float:
    diff = series_a.to_numpy() - series_b.to_numpy()
    return float(math.sqrt((diff**2).mean()))


def _mbd(series_a: pd.Series, series_b: pd.Series) -> float:
    diff = series_a.to_numpy() - series_b.to_numpy()
    return float(diff.mean())


def shapley_values(
    v: dict[frozenset[Stage], float], stages: tuple[Stage, ...] = ALL_STAGES
) -> dict[Stage, float]:
    """Shapley's (1953, eq. 13) formula, directly, over a precomputed v(T)
    for every T in the powerset of `stages`:

        phi_i(v) = sum_{T subset S\\{i}} [|T|!(|S|-|T|-1)!/|S|!] * [v(T+{i}) - v(T)]
    """
    n = len(stages)
    phi = {}
    for i in stages:
        others = [s for s in stages if s != i]
        total = 0.0
        for size in range(len(others) + 1):
            for combo in itertools.combinations(others, size):
                coalition = frozenset(combo)
                weight = math.factorial(len(coalition)) * math.factorial(n - len(coalition) - 1)
                weight /= math.factorial(n)
                total += weight * (v[coalition | {i}] - v[coalition])
        phi[i] = total
    return phi


def _shared_for(config: PipelineConfig, shared_cec: SharedInputs, shared_adr: SharedInputs) -> SharedInputs:
    return shared_adr if config.ac_model == "adr" else shared_cec


def _coalition_series_cache(
    config_anchor: PipelineConfig,
    result_anchor: PipelineResult,
    config_other: PipelineConfig,
    result_other: PipelineResult,
    shared_cec: SharedInputs,
    shared_adr: SharedInputs,
    defaults: dict,
    daylight: pd.Series,
) -> dict[frozenset[Stage], pd.Series]:
    """Final-AC, daylight-masked series for every one of the 32 coalitions,
    in one direction (config_anchor fixed), computed exactly once.

    T=empty and T=full-set are free: they're exactly config_anchor's and
    config_other's own already-known results (no new pipeline run). Both
    the RMSD-based v and the MBD-based signed v (N2) read from this same
    cache -- a direction's 30 non-trivial pipelines are never re-run per
    metric.

    Every non-trivial coalition's run is recorded as ExecutionSet.DERIVED,
    the same content-hash-deduplicated way an original run is (KT §4, N10;
    O2's reconstructibility requires every execution, including Phase 3's,
    to be recoverable from the record) -- this requires a reachable
    Postgres, same as any other recorded run.
    """
    full_set = frozenset(ALL_STAGES)
    cache: dict[frozenset[Stage], pd.Series] = {}
    for coalition in all_coalitions():
        if len(coalition) == 0:
            cache[coalition] = stage_series(result_anchor.outputs, Stage.AC, daylight)
        elif coalition == full_set:
            cache[coalition] = stage_series(result_other.outputs, Stage.AC, daylight)
        else:
            label = f"_derived_{'_'.join(str(int(s)) for s in sorted(coalition))}"
            derived_config = build_derived_config(config_anchor, config_other, coalition, label)
            shared = _shared_for(derived_config, shared_cec, shared_adr)
            derived_result = run_pipeline(derived_config, shared, defaults)
            record_provenance(derived_config, shared, derived_result, ExecutionSet.DERIVED.value)
            cache[coalition] = stage_series(derived_result.outputs, Stage.AC, daylight)
    return cache


def _v_from_cache(cache: dict[frozenset[Stage], pd.Series], metric) -> dict[frozenset[Stage], float]:
    anchor_series = cache[frozenset()]
    return {coalition: metric(series, anchor_series) for coalition, series in cache.items()}


@dataclass(frozen=True)
class Phase3Result:
    """One pair's Shapley decomposition. share[stage] is None when
    rmsd_ab == 0 (identical pipelines -- 0/0, not a defensible 0, same
    convention as dla.metrics.PairMetrics.systematic_share).
    """

    pair: tuple[str, str]
    phi_ab: dict[Stage, float]
    phi_ba: dict[Stage, float]
    phi_final: dict[Stage, float]
    share: dict[Stage, float | None]
    v_ab: dict[frozenset[Stage], float]
    v_ba: dict[frozenset[Stage], float]
    rmsd_ab: float
    signed_phi: dict[Stage, float]
    signed_v: dict[frozenset[Stage], float]


@dataclass(frozen=True)
class Phase3NotComputable:
    """This pair can't be Shapley-decomposed: at least one of the 32
    coalitions combines pvwatts_dc with sandia/adr (KT §7.5 filter 2). No
    value is fabricated and the player set is never restricted; the pair is
    simply reported as not computable, naming the specific invalid
    coalition(s).
    """

    pair: tuple[str, str]
    invalid_coalitions: list[frozenset[Stage]]
    reason: str = NOT_COMPUTABLE_REASON


def run_phase3(
    config_a: PipelineConfig,
    result_a: PipelineResult,
    config_b: PipelineConfig,
    result_b: PipelineResult,
    shared_cec: SharedInputs,
    shared_adr: SharedInputs,
    daylight: pd.Series,
    defaults: dict | None = None,
) -> Phase3Result | Phase3NotComputable:
    """Phase 3 for one pair. Checks computability before running anything --
    an invalid pair costs zero pipeline runs.
    """
    computable, invalid = pair_is_shapley_computable(config_a, config_b)
    if not computable:
        return Phase3NotComputable(pair=(config_a.label, config_b.label), invalid_coalitions=invalid)

    defaults = defaults or load_defaults()

    cache_ab = _coalition_series_cache(
        config_a, result_a, config_b, result_b, shared_cec, shared_adr, defaults, daylight
    )
    cache_ba = _coalition_series_cache(
        config_b, result_b, config_a, result_a, shared_cec, shared_adr, defaults, daylight
    )

    v_ab = _v_from_cache(cache_ab, _rmsd)
    v_ba = _v_from_cache(cache_ba, _rmsd)
    v_signed = _v_from_cache(cache_ab, _mbd)  # N2: direction A->B only

    phi_ab = shapley_values(v_ab)
    phi_ba = shapley_values(v_ba)
    signed_phi = shapley_values(v_signed)

    phi_final = {stage: (phi_ab[stage] + phi_ba[stage]) / 2 for stage in ALL_STAGES}
    rmsd_ab = v_ab[frozenset(ALL_STAGES)]
    if rmsd_ab != 0:
        share: dict[Stage, float | None] = {stage: phi_final[stage] / rmsd_ab for stage in ALL_STAGES}
    else:
        share = {stage: None for stage in ALL_STAGES}

    return Phase3Result(
        pair=(config_a.label, config_b.label),
        phi_ab=phi_ab,
        phi_ba=phi_ba,
        phi_final=phi_final,
        share=share,
        v_ab=v_ab,
        v_ba=v_ba,
        rmsd_ab=rmsd_ab,
        signed_phi=signed_phi,
        signed_v=v_signed,
    )
