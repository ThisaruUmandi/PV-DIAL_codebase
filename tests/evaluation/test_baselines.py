import pytest

from experiments.evaluation.baselines import (
    baseline_a_stage,
    baseline_b_stage,
    informative_rate_parts,
)
from pvdials.types import Stage


def test_baseline_a_is_the_first_differing_stage_in_pipeline_order():
    s = frozenset({Stage.DC, Stage.TEMPERATURE, Stage.AC})
    assert baseline_a_stage(s) == Stage.TEMPERATURE


def test_baseline_a_raises_on_empty_s():
    with pytest.raises(ValueError):
        baseline_a_stage(frozenset())


@pytest.mark.parametrize(
    "outcome, k, min_s, expected_a, expected_b",
    [
        (1, None, Stage.TRANSPOSITION, True, False),   # outcome 1: part (a)
        (2, Stage.TRANSPOSITION, Stage.TRANSPOSITION, False, False),  # k == min(S): agrees
        (2, Stage.DC, Stage.TRANSPOSITION, False, True),  # k > min(S): part (b)
        (3, Stage.DECOMPOSITION, Stage.DECOMPOSITION, False, False),
    ],
)
def test_informative_rate_parts_split_correctly(outcome, k, min_s, expected_a, expected_b):
    part_a, part_b = informative_rate_parts(outcome, k, min_s)
    assert part_a == expected_a
    assert part_b == expected_b


def test_baseline_b_picks_the_largest_single_step_rise():
    profile = {
        Stage.DECOMPOSITION: 0.01,
        Stage.TRANSPOSITION: 0.02,
        Stage.TEMPERATURE: 0.015,
        Stage.DC: 0.20,
        Stage.AC: 0.19,
    }
    # rises: 0.01, 0.01, -0.005, 0.185, -0.01 -- DC's rise is by far the largest.
    assert baseline_b_stage(profile) == Stage.DC


def test_baseline_b_ties_go_to_the_earliest_stage():
    profile = {
        Stage.DECOMPOSITION: 0.05,
        Stage.TRANSPOSITION: 0.05,
        Stage.TEMPERATURE: 0.10,
        Stage.DC: 0.10,
        Stage.AC: 0.10,
    }
    # rises: 0.05, 0.0, 0.05, 0.0, 0.0 -- DECOMPOSITION and TEMPERATURE tie
    # at 0.05; earliest wins.
    assert baseline_b_stage(profile) == Stage.DECOMPOSITION


def test_baseline_b_all_zero_picks_the_first_stage():
    profile = dict.fromkeys(
        (Stage.DECOMPOSITION, Stage.TRANSPOSITION, Stage.TEMPERATURE, Stage.DC, Stage.AC), 0.0
    )
    assert baseline_b_stage(profile) == Stage.DECOMPOSITION
