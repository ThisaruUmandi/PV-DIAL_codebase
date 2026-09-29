"""Step 3 (evaluation KT): the three perturbation cases as pytest tests,
reusing the same construction functions the standalone script uses so the
two can't drift apart. Real Colombo file, real pvlib runs -- slow.
"""

import pytest

from pvdials.config import load_defaults
from pvdials.types import Stage
from pvdials.warning_filter import ChandrupatlaWarningFilter

from experiments.evaluation.step0_measure_phase3 import _shared
from experiments.evaluation.step3_perturbation_cases import (
    case1_phase1,
    case2_one_perturbed_stage,
    case3_two_multiplicative,
)

pytestmark = [pytest.mark.slow, pytest.mark.filterwarnings("ignore::RuntimeWarning")]


@pytest.fixture(scope="module")
def shared():
    defaults = load_defaults()
    with ChandrupatlaWarningFilter():
        shared_cec, shared_adr, daylight = _shared()
    return shared_cec, shared_adr, daylight, defaults


def test_case1_k_is_dc_baseline_a_is_transposition_baseline_b_is_dc(shared):
    shared_cec, shared_adr, daylight, defaults = shared
    result = case1_phase1(shared_cec, shared_adr, daylight, defaults)

    assert result["k"] == "DC"
    assert result["baseline_a"] == "TRANSPOSITION"
    assert result["baseline_b"] == "DC"


def test_case2_share_is_100_percent_to_temperature(shared):
    shared_cec, shared_adr, daylight, defaults = shared
    result = case2_one_perturbed_stage(shared_cec, shared_adr, daylight, defaults)

    assert result["share_TEMPERATURE"] == pytest.approx(1.0, abs=1e-9)
    for stage in Stage:
        if stage != Stage.TEMPERATURE:
            assert result["phi_final"][stage.name] == pytest.approx(0.0, abs=1e-9)


def test_case3_internal_consistency_check_is_exact(shared):
    """The one real stop-condition check in Step 3: production's phi_final
    must equal comparators' independent Shapley of the averaged game, built
    from the measured v tables -- within 1e-9 relative. Paper-vs-measured
    (a separate, informational comparison) is not asserted here.
    """
    shared_cec, shared_adr, daylight, defaults = shared
    result = case3_two_multiplicative(shared_cec, shared_adr, daylight, defaults)

    assert result["internal_consistency_check"]["within_1e-9"]
