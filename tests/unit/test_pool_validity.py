import inspect
from pathlib import Path

import pytest
from pvlib import pvsystem

from pvdials.config import load_defaults
from pvdials.data.column_mapper import (
    detect_columns,
    detect_site_metadata,
    detect_time_offset,
)
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.physics.adapters.dc import dc_power
from pvdials.physics.adapters.decomposition import decompose
from pvdials.physics.adapters.temperature import cell_temperature
from pvdials.physics.adapters.transposition import transpose
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import (
    ADR_INVERTER,
    CEC,
    CEC_INVERTER,
    SANDIA,
    ModuleRecord,
    inverter_libraries,
)
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.registry import (
    STAGE4_PRODUCES_V_DC,
    dc_model_produces_v_dc,
    get_candidate,
    stage1_pool_view,
    stage2_pool_view,
    stage3_pool_view,
    stage3_selectable,
    stage4_pool_view,
    stage4_selectable,
    stage5_pool_view,
    stage5_selectable,
    stage_pool,
)
from pvdials.physics.site import build_site_context
from pvdials.types import Stage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GEOMETRY = ArrayGeometry(surface_tilt_deg=6.944, surface_azimuth_deg=180.0)
DEFAULT_ALBEDO = resolve_albedo(None, load_defaults())
DEFAULT_MOUNTING = resolve_mounting(None, None, load_defaults())

CEC_MODULES = pvsystem.retrieve_sam(CEC)
CEC_NAME = "Canadian_Solar_Inc__CS6K_300MS"
CEC_MODULE = ModuleRecord(CEC, CEC_NAME, CEC_MODULES[CEC_NAME])

SANDIA_MODULES = pvsystem.retrieve_sam(SANDIA)
SANDIA_NAME = SANDIA_MODULES.columns[0]
SANDIA_MODULE = ModuleRecord(SANDIA, SANDIA_NAME, SANDIA_MODULES[SANDIA_NAME])

CEC_INVERTERS = pvsystem.retrieve_sam(CEC_INVERTER)
ADR_INVERTERS = pvsystem.retrieve_sam(ADR_INVERTER)
INV_NAME = "ABB__PVI_6000_OUTD_S_US_A__208V_"

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


def test_stage1_and_stage2_views_equal_the_static_pool():
    assert stage1_pool_view() == stage_pool(Stage.DECOMPOSITION)
    assert stage2_pool_view() == stage_pool(Stage.TRANSPOSITION)


STAGE1_POOL_ORDER = [
    "erbs",
    "erbs_driesse",
    "disc",
    "dirint",
    "dirindex",
    "boland",
    "louche",
    "orgill_hollands",
    "campbell_norman",
    "gti_dirint",
]
STAGE3_POOL_ORDER = [
    "faiman",
    "faiman_rad",
    "fuentes",
    "generic_linear",
    "noct_sam",
    "prilliman",
    "pvsyst_cell",
    "ross",
    "sapm_cell",
]
STAGE4_POOL_ORDER = ["pvwatts_dc", "sapm", "singlediode_desoto", "singlediode_cec", "singlediode_pvsyst"]
STAGE5_POOL_ORDER = ["sandia", "adr", "pvwatts"]


def test_pool_views_stay_in_pool_order():
    assert [c.name for c in stage1_pool_view()] == STAGE1_POOL_ORDER
    assert [c.name for c in stage3_pool_view(CEC_MODULE, DEFAULT_MOUNTING)] == STAGE3_POOL_ORDER
    assert [c.name for c in stage4_pool_view(CEC_MODULE)] == STAGE4_POOL_ORDER
    assert [
        c.name for c in stage5_pool_view(INV_NAME, CEC_INVERTERS, ADR_INVERTERS, "singlediode_cec")
    ] == STAGE5_POOL_ORDER


def test_stage3_view_matches_manual_merge_for_a_gated_and_ungated_model():
    view = {c.name: c for c in stage3_pool_view(SANDIA_MODULE, DEFAULT_MOUNTING)}

    # fuentes: static-selectable, dynamically gated out (SandiaMod has no NOCT)
    ok, reason = stage3_selectable("fuentes", SANDIA_MODULE, DEFAULT_MOUNTING)
    assert not ok
    assert view["fuentes"].selectable == ok
    assert view["fuentes"].reason == reason

    # faiman: static-selectable, no dynamic gate at all
    assert view["faiman"].selectable is True
    assert view["faiman"].reason is None

    # faiman_rad: statically excluded — untouched by the merge, reason unchanged
    static = get_candidate(Stage.TEMPERATURE, "faiman_rad")
    assert view["faiman_rad"] == static


def test_stage4_view_matches_manual_merge():
    view = {c.name: c for c in stage4_pool_view(SANDIA_MODULE)}

    ok, reason = stage4_selectable("singlediode_cec", SANDIA_MODULE)
    assert not ok
    assert view["singlediode_cec"].selectable == ok
    assert view["singlediode_cec"].reason == reason

    static = get_candidate(Stage.DC, "singlediode_pvsyst")
    assert view["singlediode_pvsyst"] == static


def test_stage5_view_matches_manual_merge():
    view = {c.name: c for c in stage5_pool_view(INV_NAME, CEC_INVERTERS, ADR_INVERTERS, "pvwatts_dc")}

    libraries = inverter_libraries(INV_NAME, CEC_INVERTERS, ADR_INVERTERS)
    ok, reason = stage5_selectable("sandia", libraries, dc_has_v_dc=False)
    assert not ok
    assert view["sandia"].selectable == ok
    assert view["sandia"].reason == reason


def test_stage5_view_flips_with_the_dc_model():
    with_pvwatts_dc = {c.name: c for c in stage5_pool_view(INV_NAME, CEC_INVERTERS, ADR_INVERTERS, "pvwatts_dc")}
    with_singlediode = {
        c.name: c for c in stage5_pool_view(INV_NAME, CEC_INVERTERS, ADR_INVERTERS, "singlediode_cec")
    }

    assert with_pvwatts_dc["sandia"].selectable is False
    assert with_pvwatts_dc["adr"].selectable is False
    assert "v_dc" in with_pvwatts_dc["sandia"].reason

    assert with_singlediode["sandia"].selectable is True
    assert with_singlediode["adr"].selectable is True

    # pvwatts is unaffected either way — no v_dc requirement
    assert with_pvwatts_dc["pvwatts"].selectable is True
    assert with_singlediode["pvwatts"].selectable is True


def test_dc_model_produces_v_dc_covers_every_stage4_model():
    stage4_models = [c.name for c in stage_pool(Stage.DC) if c.selectable]

    assert set(STAGE4_PRODUCES_V_DC) == set(stage4_models)


@pytest.mark.parametrize("model", ["pvwatts_dc", "sapm", "singlediode_desoto", "singlediode_cec"])
def test_dc_model_produces_v_dc_matches_the_adapters_real_output(model):
    # Ties the declared fact to what dc_power() actually produces, so the two
    # can't silently drift apart (same class of check as the perez/sapm
    # zero-irradiance consistency checks earlier in Step 4).
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    weather = preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    ctx = build_site_context(weather, site, detect_time_offset(uploaded.preamble))
    module = SANDIA_MODULE if model == "sapm" else CEC_MODULE

    decomposition = decompose("erbs", weather, ctx)
    transposition = transpose("isotropic", weather, decomposition, ctx, GEOMETRY, DEFAULT_ALBEDO)
    temperature = cell_temperature(
        "faiman", transposition, weather, DEFAULT_MOUNTING, GEOMETRY, module=module
    )
    dc = dc_power(
        model, transposition, temperature, ctx, module, modules_per_string=10, strings_per_inverter=2
    )

    actually_has_v_dc = "v_dc" in dc.outputs.columns
    assert actually_has_v_dc == dc_model_produces_v_dc(model)


def test_only_stage5_selectable_depends_on_another_stages_chosen_model():
    """Guard for Phase 3 (Shapley hybrid-validity rule, KT Step 9): the DC->AC
    v_dc dependency is the only cross-stage-model dependency in the registry
    (KT S7.5 filter 2). stage3_selectable/stage4_selectable take only
    hardware (module, mounting) alongside their own model name -- never
    another stage's model or a value derived from it. stage5_selectable is
    the sole exception (dc_has_v_dc). If a future change adds a new
    cross-stage-derived parameter anywhere here, this signature snapshot
    breaks first, rather than Phase 3's invalid-coalition rule going stale
    silently.
    """
    assert list(inspect.signature(stage3_selectable).parameters) == ["model", "module", "mounting"]
    assert list(inspect.signature(stage4_selectable).parameters) == ["model", "module"]
    assert list(inspect.signature(stage5_selectable).parameters) == [
        "model",
        "inverter_libraries",
        "dc_has_v_dc",
    ]


@pytest.mark.parametrize(
    "dc_model,ac_model,expected_ok",
    [
        ("pvwatts_dc", "sandia", False),
        ("pvwatts_dc", "adr", False),
        ("pvwatts_dc", "pvwatts", True),
        ("sapm", "sandia", True),
        ("sapm", "adr", True),
        ("sapm", "pvwatts", True),
        ("singlediode_desoto", "sandia", True),
        ("singlediode_desoto", "adr", True),
        ("singlediode_desoto", "pvwatts", True),
        ("singlediode_cec", "sandia", True),
        ("singlediode_cec", "adr", True),
        ("singlediode_cec", "pvwatts", True),
    ],
)
def test_hybrid_validity_full_enumeration(dc_model, ac_model, expected_ok):
    """The exact hybrid-validity table Phase 3 relies on: 2 invalid
    combinations out of 12, both from pvwatts_dc's lack of v_dc. Asserts the
    Stage 4/5 selectable pool sizes first, so a model added to either pool
    later can't silently fall outside this enumeration unnoticed.
    """
    stage4_models = [c.name for c in stage_pool(Stage.DC) if c.selectable]
    stage5_models = [c.name for c in stage_pool(Stage.AC) if c.selectable]
    assert len(stage4_models) == 4
    assert len(stage5_models) == 3

    dc_has_v_dc = dc_model_produces_v_dc(dc_model)
    ok, reason = stage5_selectable(ac_model, {CEC_INVERTER, ADR_INVERTER}, dc_has_v_dc)

    assert ok == expected_ok
    assert (reason is None) == expected_ok
