import pytest
from pvlib import pvsystem

from pvdials.physics.adapters import AdapterError
from pvdials.physics.hardware import (
    CEC,
    SANDIA,
    ModuleRecord,
    cec_diode_params,
    gamma_pdc,
    has_noct,
    module_dimensions,
    module_efficiency,
    noct,
    pdc0,
    resolve_array_size,
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


def test_pdc0_from_cec_stc_field():
    value, formula = pdc0(CEC_MODULE)

    assert value == pytest.approx(float(CEC_MODULE.params["STC"]))
    assert formula == "STC"


def test_pdc0_from_sandia_vmpo_impo():
    value, formula = pdc0(SANDIA_MODULE)

    p = SANDIA_MODULE.params
    assert value == pytest.approx(float(p["Vmpo"]) * float(p["Impo"]))
    assert formula == "Vmpo * Impo"


def test_gamma_pdc_from_cec_gamma_r_divided_by_100():
    value, formula = gamma_pdc(CEC_MODULE)

    p = CEC_MODULE.params
    assert value == pytest.approx(float(p["gamma_r"]) / 100.0)
    assert -0.006 < value < -0.002  # matches pvwatts_dc's documented typical range
    assert formula == "gamma_r / 100"


def test_gamma_pdc_from_sandia_product_rule():
    value, formula = gamma_pdc(SANDIA_MODULE)

    p = SANDIA_MODULE.params
    # Bvmpo's own Mbvmp irradiance-dependence term vanishes at reference conditions
    # (Ee=1), confirmed against sapm()'s own source (23/09) — so the raw field is used
    # directly, with no extra reference-condition adjustment needed here.
    expected = float(p["Bvmpo"]) / float(p["Vmpo"]) + float(p["Aimp"])
    assert value == pytest.approx(expected)
    assert formula == "Bvmpo / Vmpo + Aimp"


def test_cec_diode_params_reads_calcparams_desoto_fields():
    params = cec_diode_params(CEC_MODULE, need_adjust=False)

    assert set(params) == {"alpha_sc", "a_ref", "I_L_ref", "I_o_ref", "R_sh_ref", "R_s"}
    assert params["alpha_sc"] == pytest.approx(float(CEC_MODULE.params["alpha_sc"]))


def test_cec_diode_params_with_adjust_for_calcparams_cec():
    params = cec_diode_params(CEC_MODULE, need_adjust=True)

    assert "Adjust" in params
    assert params["Adjust"] == pytest.approx(float(CEC_MODULE.params["Adjust"]))


def test_cec_diode_params_raises_for_sandia():
    with pytest.raises(AdapterError, match="single-diode"):
        cec_diode_params(SANDIA_MODULE, need_adjust=False)


def test_array_size_has_no_default():
    with pytest.raises(AdapterError, match="[Nn]o default"):
        resolve_array_size(None, None)
    with pytest.raises(AdapterError, match="[Nn]o default"):
        resolve_array_size(10, None)


def test_array_size_resolves_when_both_given():
    array = resolve_array_size(10, 2)

    assert array.modules_per_string == 10
    assert array.strings_per_inverter == 2
