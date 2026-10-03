"""Every piece of interface text lives here, so pages and the report import one
source and the vocabulary guard has one place to read.

Texts marked KT are verbatim from the interface brief (frontend-kt, 03/10/2026).
UK English. No text here ranks, advises or says which pipeline is right.
"""

from __future__ import annotations

TAU = "τ"

# --- Steps and pages ---------------------------------------------------------------

STEP_TITLES = {
    1: "Data & site",
    2: "Pipeline configuration",
    3: "Run & provenance",
    4: "Analysis",
    5: "Guided re-execution",
    6: "Report",
}
STEP_SUMMARIES = {
    1: "Weather file, time offset, site and hardware.",
    2: "One model per stage for A, B and C.",
    3: "Run the pipelines, see their outputs.",
    4: "Phase 1, then Phase 2 and 3.",
    5: "Swap one model at the flagged stage (optional).",
    6: "The whole analysis on one page, to download.",
}
HOME_TITLE = "Home"
PAST_TITLE = "Past analyses"
APP_TITLE = "PV-DIALS"
APP_TAGLINE = "Pipeline disagreement diagnostics"

STEP_OF = "Step {n} of 6"

STATUS_DONE = "Done"
STATUS_CURRENT = "Current"
STATUS_LOCKED = "Locked"
STATUS_OPEN = "Open"

STAGE_NAMES = {
    "DECOMPOSITION": "Decomposition",
    "TRANSPOSITION": "Transposition",
    "TEMPERATURE": "Cell temperature",
    "DC": "DC power",
    "AC": "AC conversion",
}
PAIR_ORDER = ("A-B", "A-C", "B-C")

# --- Outcomes (KT section C) ---------------------------------------------------------

OUTCOME_TEXT = {
    1: "No stage exceeds τ",
    2: "Exceeds τ; final AC above τ",
    3: "Exceeds τ upstream; final AC below τ",
}
K_NONE = "none"
PHASE3_OUTCOME_1 = "Outcome 1 — nothing to attribute."
NOT_COMPUTABLE = "Not computable — {reason} at stage {stage}"
NOT_COMPUTABLE_HYBRID = "Not computable — DC/AC hybrid invalidity"
SAME_MODEL = "same model — no difference"
ONE_STAGE_NOTE = (
    "Only one stage differs between these pipelines, so the whole final difference is "
    "attributed to it. This follows from the configuration, not from the analysis."
)
PHASE2_NOT_RUN = "not run — no pair exceeds τ"

# One plain sentence under each pair card (F2.4); descriptive only.
PAIR_SENTENCE = {
    1: "{a} and {b} do not differ by more than τ at any stage.",
    2: (
        "{a} and {b} first differ by more than τ at {stage}. "
        "At the final AC output the difference is still above τ."
    ),
    3: (
        "{a} and {b} first differ by more than τ at {stage}. "
        "At the final AC output the difference is below τ."
    ),
}

# --- Plain-words help texts (F2.3) ---------------------------------------------------

HELP_NRMSD = (
    "How far apart two pipelines' outputs are at a stage, on a unitless scale: RMSD divided "
    "by the P95 − P5 range of both pipelines' daylight values."
)
HELP_TAU = (
    "τ is the threshold a stage's nRMSD must exceed to count as material. The default was set "
    "by a pre-registered stability rule for the Colombo file, this hardware and this model "
    "pool. No value of τ is claimed to be the right one."
)
HELP_K = "The first stage, in pipeline order, where nRMSD is above τ."
HELP_PHI = (
    "The part of the final AC difference attributed to a stage (Shapley value), in watts. "
    "The stages add up to RMSD(A,B)."
)
HELP_SHARE = "φ final divided by RMSD(A,B)."

DISCLAIMER = (
    "This shows how disagreement changes with one substitution. It does not identify which "
    "configuration is preferable — that choice remains the user's."
)

# --- Home ------------------------------------------------------------------------------

HOME_HEADLINE = "Where do your PV pipelines start to disagree?"
HOME_INTRO = (
    "Run up to three pvlib pipelines on the same weather file, site and hardware. PV-DIALS "
    "compares their outputs stage by stage, shows where the disagreement first becomes "
    "material, and how much each modelling stage contributes to it."
)
HOME_SHOWS = (
    (
        "Phase 1",
        "Where. For each pair of pipelines, the first stage whose disagreement passes the threshold τ.",
    ),
    ("Phase 2", "How it carries. How that disagreement grows or shrinks through the later stages."),
    ("Phase 3", "How much. Each stage's share of the final AC disagreement (Shapley attribution)."),
)
HOME_NOT_SHOWN = (
    "What it does not show: which pipeline is closer to the real system. There is no measured "
    "reference, so PV-DIALS reports how far the pipelines differ and never which one is right. "
    "Choosing between configurations stays with you."
)
HOME_BEFORE_YOU_START = (
    "An hourly PVGIS TMY file (CSV) with GHI, T2m, WS10m and SP",
    "Tilt, azimuth and albedo for the array",
    "A module and inverter from the CEC database",
    "The module mounting height",
)
HOME_SAVED_NOTE = (
    "Each analysis is saved as you go. Steps open one at a time; changing an earlier input "
    "clears the steps after it."
)
START_NEW_ANALYSIS = "Start new analysis"

# --- Labels used on several pages ----------------------------------------------------------

LABEL_FILE_SHA = "File SHA-256"
LABEL_INPUT_HASH = "Input data hash (provenance)"
NOT_SET_YET = "not set yet"

# --- Locks, empty states, messages -----------------------------------------------------------

LOCK_REASON = {
    2: "Complete step 1 (Data & site) first: upload a weather file and fill in the site and hardware.",
    3: "Complete step 2 (Pipeline configuration) first.",
    4: "Run the pipelines in step 3 first.",
    5: "Run Phase 1 in step 4 first. This step needs a pair with a first stage over τ.",
    6: "Run Phase 1 in step 4 first.",
}
LOCKED_HEADING = "This step is locked"
PLACEHOLDER = "Page content arrives in a later step."

EMPTY_ANALYSIS = (
    "No analysis yet. Run Phase 1 to see where the pipelines first differ by more than τ."
)
EMPTY_PAST = "No saved analyses yet. Choose Start new analysis to begin one."

DB_UNREACHABLE = "The provenance store cannot be reached. Start PostgreSQL and reload this page."

# Shown before an input change clears later steps (F2.5).
CLEARS_STEPS = "This clears steps {first} to 6 of this analysis."
CLEARS_STEP_6 = "This clears step 6 of this analysis."
CONFIRM = "Confirm change"
CANCEL = "Cancel"
CANCELLED_NOTE = "Change cancelled. Everything is kept as it was."

SAVED_NOTE = "Saved."


def clears_message(first_step: int) -> str:
    """'This clears steps 3 to 6 of this analysis.' (or step 6 alone)."""
    return CLEARS_STEP_6 if first_step >= 6 else CLEARS_STEPS.format(first=first_step)
