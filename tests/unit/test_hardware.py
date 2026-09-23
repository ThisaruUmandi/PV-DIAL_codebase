import pytest
from pvlib import pvsystem

from pvdials.physics.adapters import AdapterError
from pvdials.physics.hardware import (
    CEC,
    SANDIA,
    ModuleRecord,
    has_noct,
    module_dimensions,
    module_efficiency,
    noct,
)

CEC_MODULES = pvsystem.retrieve_sam(CEC)
SANDIA_MODULES = pvsystem.retrieve_sam(SANDIA)

CEC_NAME = "Canadian_Solar_Inc__CS6K_300MS"
CEC_MODULE = ModuleRecord(CEC, CEC_NAME, CEC_MODULES[CEC_NAME])

SANDIA_NAME = SANDIA_MODULES.columns[0]
SANDIA_MODULE = ModuleRecord(SANDIA, SANDIA_NAME, SANDIA_MODULES[SANDIA_NAME])


def test_has_noct_true_for_cec_false_for_sandia():
    assert has_noct(CEC_MODULE)
    assert not has_noct(SANDIA_MODULE)


def test_noct_reads_the_value():
    assert noct(CEC_MODULE) == pytest.approx(45.3)


def test_noct_raises_for_sandia():
    with pytest.raises(AdapterError, match="T_NOCT"):
        noct(SANDIA_MODULE)


def test_module_efficiency_matches_hand_computed_value():
    value, formula = module_efficiency(CEC_MODULE)

    p = CEC_MODULE.params
    expected = float(p["I_mp_ref"]) * float(p["V_mp_ref"]) / (float(p["A_c"]) * 1000.0)
    assert value == pytest.approx(expected)
    assert value == pytest.approx(0.185, abs=1e-3)
    assert "I_mp_ref" in formula and "V_mp_ref" in formula and "A_c" in formula


def test_module_efficiency_matches_stc_field_too():
    value, _ = module_efficiency(CEC_MODULE)
    p = CEC_MODULE.params

    assert value == pytest.approx(float(p["STC"]) / (float(p["A_c"]) * 1000.0))


def test_module_efficiency_raises_for_sandia():
    with pytest.raises(AdapterError, match="CEC-style"):
        module_efficiency(SANDIA_MODULE)


def test_module_dimensions_from_cec():
    length, width = module_dimensions(CEC_MODULE)

    assert length == pytest.approx(1.644)
    assert width == pytest.approx(0.986)


def test_module_dimensions_raises_for_sandia():
    with pytest.raises(AdapterError, match="Length/Width"):
        module_dimensions(SANDIA_MODULE)
