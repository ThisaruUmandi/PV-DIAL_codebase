"""The interface texts equal the brief's (KT) strings, and none says 'error'."""

import re

from app import wording
from pvdials.guided_reexecution import DISCLAIMER as BACKEND_DISCLAIMER


def test_help_texts_are_the_kt_texts():
    assert wording.HELP_NRMSD == (
        "How far apart two pipelines' outputs are at a stage, on a unitless scale: RMSD divided "
        "by the P95 − P5 range of both pipelines' daylight values."
    )
    assert wording.HELP_TAU == (
        "τ is the threshold a stage's nRMSD must exceed to count as material. The default was set "
        "by a pre-registered stability rule for the Colombo file, this hardware and this model "
        "pool. No value of τ is claimed to be the right one."
    )
    assert wording.HELP_K == "The first stage, in pipeline order, where nRMSD is above τ."
    assert wording.HELP_PHI == (
        "The part of the final AC difference attributed to a stage (Shapley value), in watts. "
        "The stages add up to RMSD(A,B)."
    )
    assert wording.HELP_SHARE == "φ final divided by RMSD(A,B)."


def test_outcome_texts_and_states():
    assert wording.OUTCOME_TEXT == {
        1: "No stage exceeds τ",
        2: "Exceeds τ; final AC above τ",
        3: "Exceeds τ upstream; final AC below τ",
    }
    assert wording.PHASE3_OUTCOME_1 == "Outcome 1 — nothing to attribute."
    assert wording.SAME_MODEL == "same model — no difference"
    assert wording.NOT_COMPUTABLE.format(reason="too few daylight samples", stage="DC") == (
        "Not computable — too few daylight samples at stage DC"
    )
    assert wording.NOT_COMPUTABLE_HYBRID == "Not computable — DC/AC hybrid invalidity"
    assert wording.ONE_STAGE_NOTE == (
        "Only one stage differs between these pipelines, so the whole final difference is "
        "attributed to it. This follows from the configuration, not from the analysis."
    )


def test_pair_sentences():
    fill = {"a": "A", "b": "B", "stage": "Decomposition"}
    assert wording.PAIR_SENTENCE[1].format(**fill) == "A and B do not differ by more than τ at any stage."
    assert wording.PAIR_SENTENCE[2].format(**fill) == (
        "A and B first differ by more than τ at Decomposition. "
        "At the final AC output the difference is still above τ."
    )
    assert wording.PAIR_SENTENCE[3].format(**fill) == (
        "A and B first differ by more than τ at Decomposition. "
        "At the final AC output the difference is below τ."
    )


def test_disclaimer_matches_the_backend_text_exactly():
    assert wording.DISCLAIMER == BACKEND_DISCLAIMER


def test_home_text_and_hash_labels_and_messages():
    assert wording.HOME_NOT_SHOWN == (
        "What it does not show: which pipeline is closer to the real system. There is no measured "
        "reference, so PV-DIALS reports how far the pipelines differ and never which one is right. "
        "Choosing between configurations stays with you."
    )
    assert wording.LABEL_FILE_SHA == "File SHA-256"
    assert wording.LABEL_INPUT_HASH == "Input data hash (provenance)"
    assert wording.DB_UNREACHABLE == (
        "The provenance store cannot be reached. Start PostgreSQL and reload this page."
    )
    assert wording.EMPTY_ANALYSIS == (
        "No analysis yet. Run Phase 1 to see where the pipelines first differ by more than τ."
    )


def test_clears_message():
    assert wording.clears_message(3) == "This clears steps 3 to 6 of this analysis."
    assert wording.clears_message(6) == "This clears step 6 of this analysis."


def test_every_text_is_free_of_the_word_error_and_of_compensation():
    texts = []
    for name in dir(wording):
        value = getattr(wording, name)
        if name.startswith("_"):
            continue
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            texts += [v for v in value.values() if isinstance(v, str)]
        elif isinstance(value, tuple):
            for item in value:
                texts += [item] if isinstance(item, str) else [t for t in item if isinstance(t, str)]
    assert texts
    for text in texts:
        assert not re.search(r"error|compensat", text, re.IGNORECASE), text
