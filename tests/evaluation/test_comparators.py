"""Step 2 (evaluation KT): the two hand-built v tables, worked on paper in
the KT itself, checked against comparators.py's independent Shapley
implementation.
"""

import math

import pytest

from experiments.evaluation.comparators import (
    argmax_with_ties,
    attribution_gap,
    averaged_game,
    loo_reading,
    parse_coalition_key,
    rank_agreement,
    shapley_values,
    singleton_reading,
    wilson_interval,
)
from pvdials.types import Stage

EMPTY = frozenset()
FULL = frozenset({1, 2})


def test_additive_table_gives_singletons_as_phi_zero_gap_identical_ranks():
    # v({1,2}) = v({1}) + v({2}): 3, 1, 4.
    v = {EMPTY: 0.0, frozenset({1}): 3.0, frozenset({2}): 1.0, FULL: 4.0}

    phi = shapley_values(v, (1, 2))

    assert phi[1] == pytest.approx(3.0)
    assert phi[2] == pytest.approx(1.0)

    singletons = {i: singleton_reading(v, i) for i in (1, 2)}
    assert attribution_gap(singletons, v[FULL]) == pytest.approx(0.0)
    assert rank_agreement(phi, singletons) == "agree"


def test_interactive_table_stage2_doubles_stage1_gives_the_supervisors_numbers():
    # Stage 2 alone does nothing but doubles stage 1's effect: 4, 0, 8.
    v = {EMPTY: 0.0, frozenset({1}): 4.0, frozenset({2}): 0.0, FULL: 8.0}

    phi = shapley_values(v, (1, 2))

    assert phi[1] == pytest.approx(6.0)
    assert phi[2] == pytest.approx(2.0)

    singletons = {i: singleton_reading(v, i) for i in (1, 2)}
    assert sum(singletons.values()) == pytest.approx(4.0)
    assert attribution_gap(singletons, v[FULL]) == pytest.approx(0.5)
    assert rank_agreement(phi, singletons) == "agree"


def test_averaged_game_is_the_mean_of_both_directions():
    v_xy = {EMPTY: 0.0, frozenset({1}): 4.0, frozenset({2}): 0.0, FULL: 8.0}
    v_yx = {EMPTY: 0.0, frozenset({1}): 2.0, frozenset({2}): 2.0, FULL: 8.0}

    w = averaged_game(v_xy, v_yx)

    assert w[frozenset({1})] == pytest.approx(3.0)
    assert w[frozenset({2})] == pytest.approx(1.0)
    assert w[FULL] == pytest.approx(8.0)


def test_loo_reading_is_v_of_full_minus_v_of_full_without_i():
    v = {EMPTY: 0.0, frozenset({1}): 4.0, frozenset({2}): 0.0, FULL: 8.0}

    assert loo_reading(v, FULL, 1) == pytest.approx(8.0 - 0.0)
    assert loo_reading(v, FULL, 2) == pytest.approx(8.0 - 4.0)


def test_ties_within_relative_tolerance_are_reported_as_ties():
    phi = {1: 5.0, 2: 5.0 + 1e-12}
    top, _ = argmax_with_ties(phi)
    assert set(top) == {1, 2}

    readings = {1: 5.0, 2: 3.0}
    assert rank_agreement(phi, readings) == "tie"


def test_attribution_gap_is_zero_when_v_of_full_is_zero_and_readings_sum_to_zero():
    assert attribution_gap({1: 0.0, 2: 0.0}, 0.0) == 0.0


def test_wilson_interval_matches_a_hand_computed_example():
    # n=100, successes=50: textbook Wilson interval is roughly (0.404, 0.596).
    lo, hi = wilson_interval(50, 100)
    assert lo == pytest.approx(0.404, abs=0.001)
    assert hi == pytest.approx(0.596, abs=0.001)


def test_parse_coalition_key_round_trips_the_analysis_py_format():
    assert parse_coalition_key("EMPTY") == frozenset()
    assert parse_coalition_key("DECOMPOSITION") == frozenset({Stage.DECOMPOSITION})
    assert parse_coalition_key("DECOMPOSITION+TEMPERATURE") == frozenset(
        {Stage.DECOMPOSITION, Stage.TEMPERATURE}
    )


def test_shapley_efficiency_holds_for_a_5_player_game():
    # Sanity check beyond the 2-player hand-built tables: efficiency axiom
    # (sum of phi == v(full set)) for the actual 5-stage powerset shape.
    players = tuple(Stage)
    import random

    rng = random.Random(0)
    v = {}
    for size in range(len(players) + 1):
        import itertools

        for combo in itertools.combinations(players, size):
            v[frozenset(combo)] = rng.uniform(0, 10)
    v[frozenset()] = 0.0

    phi = shapley_values(v, players)
    assert sum(phi.values()) == pytest.approx(v[frozenset(players)], abs=1e-9)
    assert not math.isnan(sum(phi.values()))
