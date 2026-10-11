"""Guards chain_population.py's reimplementation of build_configs() against
the existing exhaustive-cache labels -- if this ever drifts (a registry pool
change, a different hardware default), the ensemble in step4_ensemble.py
would silently be drawn from a different population than the cache it's
cross-checked against.
"""

from experiments.evaluation.chain_population import (
    build_configs,
    default_hardware,
    load_cached_labels,
)


def test_regenerated_population_matches_the_cached_labels_exactly():
    module, mounting = default_hardware()
    configs = build_configs(module, mounting)
    cached_labels = load_cached_labels()

    assert len(configs) == 2058
    assert len(cached_labels) == 2058
    assert [c.label for c in configs] == cached_labels


def test_every_config_has_a_unique_label():
    module, mounting = default_hardware()
    configs = build_configs(module, mounting)

    assert len({c.label for c in configs}) == len(configs)
