"""Page 4 logic that needs no database: the k band, the stored-dict round trip and the wording of states."""

import math
import random

import pytest

from app import analysis_logic as al
from app import wording

STAGES = al.STAGES

AB = dict(zip(STAGES, (0.1235, 0.0036, 0.1534, 0.0173, 0.0172), strict=True))
AC = dict(zip(STAGES, (0.1396, 0.0065, 0.1946, 0.0225, 0.0223), strict=True))
BC = dict(zip(STAGES, (0.0674, 0.0051, 0.0706, 0.0079, 0.0078), strict=True))
THESIS_TAU = 0.093


def _first_over(nrmsd, tau):
    return next((s for s in STAGES if nrmsd[s] > tau), None)


# --- k band (KT E.2): a pure function of the stored nRMSD values and τ ----------------------------------------


def test_thesis_k_bands():
    ab, ac, bc = (al.k_band(v, THESIS_TAU) for v in (AB, AC, BC))
    assert (ab.stage, ab.lower, ab.upper) == ("decomposition", None, 0.1235)
    assert (ac.stage, ac.lower, ac.upper) == ("decomposition", None, 0.1396)
    assert (bc.stage, bc.lower, bc.upper) == (None, None, 0.0706)
    assert al.k_band_text(ab) == "k stays at Decomposition for any τ below 0.1235"
    assert al.k_band_text(ac) == "k stays at Decomposition for any τ below 0.1396"
    assert al.k_band_text(bc) == "No stage is over τ for any τ at or above 0.0706"


def test_a_later_k_has_a_lower_edge_that_is_the_largest_earlier_value():
    values = dict(zip(STAGES, (0.01, 0.02, 0.15, 0.011, 0.012), strict=True))
    band = al.k_band(values, 0.05)
    assert (band.stage, band.lower, band.upper) == ("temperature", 0.02, 0.15)
    assert al.k_band_text(band) == "k stays at Cell temperature for τ from 0.0200 up to, but not including, 0.1500"


def test_the_edges_are_exact_lower_inclusive_upper_exclusive():
    # τ equal to a stage's nRMSD does not put that stage over τ, so k moves on
    assert al.k_band(AB, 0.1235).stage == "temperature"
    assert al.k_band(AB, 0.12349999).stage == "decomposition"
    assert al.k_band(AB, 0.1534).stage is None and al.k_band(AB, 0.15339999).stage == "temperature"


@pytest.mark.parametrize("seed", range(40))
def test_k_stays_the_same_across_the_band_and_changes_at_its_edges(seed):
    rng = random.Random(seed)
    values = dict(zip(STAGES, (round(rng.uniform(0.001, 0.3), 4) for _ in STAGES), strict=True))
    tau = round(rng.uniform(0.0005, 0.35), 4)
    band = al.k_band(values, tau)
    assert band.stage == _first_over(values, tau)
    inside = [tau, math.nextafter(band.upper, 0)]
    if band.lower is not None:
        inside.append(band.lower)
    if band.stage is None:  # no stage over τ for any τ at or above the largest value
        assert band.upper == max(values.values())
        assert _first_over(values, band.upper) is None
        assert _first_over(values, math.nextafter(band.upper, 0)) is not None
        return
    for t in inside:
        assert _first_over(values, t) == band.stage, (values, t, band)
    assert _first_over(values, band.upper) != band.stage  # at the upper edge k has moved
    if band.lower is not None:
        assert _first_over(values, math.nextafter(band.lower, 0)) != band.stage  # below the lower edge an earlier stage is over


# --- Stored dict <-> pvdials objects ------------------------------------------------------------------------------


def _entry(outcome=3, k="DECOMPOSITION", nrmsd=AB, source="default", value=0.093):
    return {
        "status": "ran", "pair": ["A", "B"], "outcome": outcome, "k": k,
        "differing_stages": ["DECOMPOSITION", "TRANSPOSITION", "TEMPERATURE", "DC"],
        "tau": {"value": value, "source": source},
        "metrics": [
            {"stage": s.upper(), "rmsd": 1.5, "nrmsd": nrmsd[s], "mad": 1.2, "mbd": -0.1,
             "systematic_share": None if s == "ac" else 0.25, "n_pooled": 8000, "not_computable_reason": None}
            for s in STAGES
        ],
    }


def test_a_stored_phase1_entry_survives_the_round_trip_unchanged():
    from pvdials.analysis import phase1_to_dict

    entry = _entry()
    assert phase1_to_dict(al.phase1_from_dict(entry)) == entry
    failed = {"status": "not computable", "reason": "not computable — too few daylight samples at stage DC"}
    assert al.phase1_from_dict(failed) == failed["reason"]
    assert phase1_to_dict(al.phase1_from_dict(failed)) == failed


# --- Wording of states ------------------------------------------------------------------------------------------------


def test_outcome_labels_are_exactly_the_agreed_ones():
    assert wording.OUTCOME_TEXT == {
        1: "No stage exceeds τ",
        2: "Exceeds τ; final AC above τ",
        3: "Exceeds τ upstream; final AC below τ",
    }


def test_not_computable_text_names_the_reason_and_the_stage_and_other_forms_are_shown_as_stored():
    assert (
        al.not_computable_text("not computable — too few daylight samples at stage DC")
        == "Not computable — too few daylight samples at stage DC power"
    )
    assert al.not_computable_text("not computable — pipeline B failed dc") == "Not computable — pipeline B failed dc"


def test_a_pair_that_is_not_computable_has_no_k_and_no_band():
    phase1 = {
        "A-B": {"status": "not computable", "reason": "not computable — zero spread at stage AC"},
        "A-C": _entry(), "B-C": _entry(outcome=1, k=None, nrmsd=BC),
    }
    views = al.phase1_view(phase1)
    assert [v.key for v in views] == ["A-B", "A-C", "B-C"]  # fixed order
    assert views[0].computable is False and views[0].k is None and views[0].band is None
    assert views[0].not_computable == "Not computable — zero spread at stage AC conversion"
    assert views[0].outcome is None and views[0].nrmsd == dict.fromkeys(STAGES)


def test_the_stage_rows_name_both_models_or_say_same_model():
    view = al.phase1_view({k: _entry() for k in ("A-B", "A-C", "B-C")})[0]
    models = {"A": dict(zip(STAGES, ("erbs", "isotropic", "faiman", "singlediode_cec", "sandia"), strict=True)),
              "B": dict(zip(STAGES, ("disc", "haydavies", "pvsyst_cell", "singlediode_desoto", "sandia"), strict=True))}
    rows = al.stage_rows(view, models)
    assert [r["stage"] for r in rows] == list(STAGES)
    assert rows[0]["models"] == "A: erbs<br>B: disc" and rows[4]["models"] == "Same model"
    assert [r["first"] for r in rows] == [True, False, False, False, False]
    assert [r["over"] for r in rows] == [True, False, True, False, False]  # over τ = 0.093: decomposition, temperature


def test_a_value_equal_to_tau_is_not_over_tau_and_the_view_agrees_with_the_backend_rule():
    values = dict(zip(STAGES, (0.093, 0.02, 0.15, 0.01, 0.093), strict=True))  # two stages exactly at τ
    entry = _entry(outcome=3, k="TEMPERATURE", nrmsd=values)
    view = al.phase1_view({k: entry for k in ("A-B", "A-C", "B-C")})[0]
    assert view.over == frozenset({"temperature"})  # strictly above τ, as run_phase1 decides
    assert view.k == "temperature"


@pytest.mark.parametrize("seed", range(30))
def test_the_cells_marked_over_tau_always_match_the_backends_k_and_outcome(seed):
    """The view re-reads 'over τ' from the stored numbers; for any numbers the first such stage is k, and the
    final stage being over τ is what separates outcome 2 from outcome 3."""
    rng = random.Random(seed)
    values = dict(zip(STAGES, (round(rng.uniform(0.0, 0.2), 4) for _ in STAGES), strict=True))
    tau = rng.choice([*values.values(), round(rng.uniform(0.0, 0.2), 4)])  # sometimes exactly a stage's value
    over = [s for s in STAGES if values[s] > tau]
    k = over[0].upper() if over else None
    outcome = 1 if not over else (2 if "ac" in over else 3)
    entry = _entry(outcome=outcome, k=k, nrmsd=values, value=tau)
    view = al.phase1_view({key: entry for key in ("A-B", "A-C", "B-C")})[0]
    assert view.over == frozenset(over)
    assert (view.k, view.outcome) == (over[0] if over else None, outcome)
