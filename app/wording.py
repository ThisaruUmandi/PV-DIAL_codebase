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
    5: "Swap one model at the flagged stage.",
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
    ("Phase 1", "Where.", "For each pair of pipelines, the first stage whose disagreement passes the threshold τ."),
    ("Phase 2", "How it carries.", "How that disagreement grows or shrinks through the later stages."),
    ("Phase 3", "How much.", "Each stage's share of the final AC disagreement (Shapley attribution)."),
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

# --- Home layout and sidebar chrome (labels from the Main mock-up) -----------------------
STAGES_COMPARED = "Stages compared"
STAGE_PILLS = ("Decomposition", "Transposition", "Cell temperature", "DC", "AC")
HOME_CARD_SHOWS = "What the analysis shows"
HOME_CARD_BEFORE = "Before you start"
RECENT_ANALYSES = "Recent analyses"
VIEW_ALL_PAST = "View all past analyses"
RECENT_HEADERS = ("Analysis", "Saved", "Phase 1 outcome by pair", "Status", "Action")
SIX_STEPS = "The six steps"
OPTIONAL = "optional"
CURRENT_ANALYSIS = "Current analysis"
STORE_CONNECTED = "Provenance store: connected"
STORE_NOT_CONNECTED = "Provenance store: not connected"
TAU_FOOTER = "τ = {value:g} ({source})"
PVLIB_FOOTER = "pvlib {version}"
SAVED_WORK = "Saved work"

# --- Page 1 · Data & site ----------------------------------------------------------------------
D_NAME_LABEL = "Analysis name"
D_NAME_HELP = "Used to find this analysis again under Past analyses."
D_CARD_FILE = "Weather file"
D_UPLOAD_LABEL = "Upload a weather file (CSV)"
D_UPLOAD_HELP = "An hourly PVGIS TMY file as .csv, with GHI, T2m and WS10m (and SP if you have it)."
D_REPLACE_FILE = "Replace file"
D_FILE_META = "{source} · {rows:,} rows · {step}"
D_SOURCE_PVGIS = "PVGIS TMY"
D_SOURCE_OTHER = "Weather file"
D_STEP_HOURLY = "hourly"
D_STEP_OTHER = "not an hourly series"
D_COLUMNS_LABEL = "Required columns (GHI, T2m, WS10m, SP)"
D_COLUMNS_FOUND = "Found"
D_COLUMNS_FOUND_NO_SP = "Found · SP not in the file; pressure is derived from the elevation"
D_COLUMNS_MISSING = "Missing: {names}"
D_TIERS_LABEL = "Validation tiers 1–4"
D_TIERS_PASSED = "Passed · {n} warning{s}"
D_TIERS_FAILED = "Not passed · {n} problem{s}"
D_TIERS_WAITING = "Tiers 1–3: {state} · tier 4 waits for the site and the time offset"
D_TIER_NAMES = {
    1: "Tier 1 · structure",
    2: "Tier 2 · physical ranges",
    3: "Tier 3 · full-year check",
    4: "Tier 4 · day and night consistency",
}
D_CHECK_DETAILS = "Details of the checks"
D_NO_FINDINGS = "Nothing to report."
HELP_FILE_SHA = (
    "A fingerprint of the exact file you uploaded. The same file always gives the same value, "
    "so this analysis can be tied to this file."
)
D_COLUMN_NAMES = {"ghi": "GHI", "temp_air": "T2m", "wind_speed": "WS10m", "pressure": "SP"}

D_CARD_OFFSET = "Time offset"
D_OFFSET_INTRO = "The file header states {value:g} h. The counts show how each choice fits the file's own day and night values."
D_OFFSET_INTRO_ABSENT = "The file header does not state an offset; 0 h is assumed. The counts show how each choice fits the file's own day and night values."
HELP_OFFSET = (
    "Each hourly value stands for a moment inside that hour. The offset is how many hours after the "
    "time stamp that moment is. The counts compare each choice with the file's own day and night "
    "values: hours with sunlight recorded while the sun is down, and hours with none recorded while "
    "the sun is up."
)
D_OFFSET_HEADER = "Header ({value:g} h)"
D_OFFSET_HEADER_ABSENT = "Header (not stated, 0 h assumed)"
D_OFFSET_START = "Hour-start (0 h)"
D_OFFSET_CENTRE = "Hour-centre (0.5 h)"
D_OFFSET_COLS = ("Offset", "GHI > 0, sun down", "GHI = 0, sun up")
D_OFFSET_CHOICE = "Offset used"
D_OFFSET_REASON = "Reason (recorded in provenance)"
D_OFFSET_REASON_HELP = "Needed when the offset you use differs from the one the file header states."
D_OFFSET_NEEDS_SITE = "Enter the latitude and longitude to see the counts."

D_CARD_SITE = "Site & hardware"
D_SITE_SUB = "Shared by all three pipelines."
D_LAT = "Latitude"
D_LON = "Longitude"
D_ELEV = "Elevation (m)"
D_FROM_FILE = "file"
D_FROM_FILE_HELP = "Read from the weather file header."
D_TILT = "Tilt (°)"
D_AZIMUTH = "Azimuth (°)"
D_ALBEDO = "Albedo (default 0.2)"
D_GEOMETRY = "Mounting geometry"
D_CONSTRUCTION = "Construction"
D_GEOMETRY_NAMES = {"open_rack": "Open rack", "close_mount": "Close mount", "insulated_back": "Insulated back"}
D_CONSTRUCTION_NAMES = {"glass_polymer": "Glass / polymer", "glass_glass": "Glass / glass"}
D_MODULE = "Module (CECMod)"
D_INVERTER = "Inverter"
D_MODULES_PER_STRING = "Modules per string"
D_STRINGS = "Strings per inverter"
D_MODULE_HEIGHT = "Module height (m)"
D_REQUIRED = "required"

D_CONTINUE = "Continue to configuration"
D_CONTINUE_BLOCKED = "To continue:"
D_SAVED_FLASH = "Saved. Step 1 is complete."

# Plain-words messages for what blocks Continue (F2.6, F2.7)
D_NEED_NAME = "give the analysis a name"
D_NEED_FILE = "upload a weather file"
D_NEED_COLUMNS = "the file is missing the column(s) {names}; upload a file that has GHI, T2m and WS10m"
D_NEED_TIERS = "the file did not pass {tiers}; see the details of the checks, fix the file and upload it again"
D_NEED_LAT = "enter a latitude between −90 and 90"
D_NEED_LON = "enter a longitude between −180 and 180"
D_NEED_REASON = "give a reason for using an offset that differs from the file header"
D_NEED_TILT = "enter the tilt, between 0 and 90 degrees"
D_NEED_AZIMUTH = "enter the azimuth, between 0 and 360 degrees"
D_NEED_ALBEDO = "enter an albedo between 0 and 1"
D_NEED_MODULES = "enter the number of modules per string (a whole number, 1 or more)"
D_NEED_STRINGS = "enter the number of strings per inverter (a whole number, 1 or more)"
D_NEED_HEIGHT = "enter the module height in metres (more than 0)"
D_NEED_MODULE = "choose a module"
D_NEED_INVERTER = "choose an inverter"
D_NEED_ELEVATION = "enter an elevation in metres, or leave it empty to use standard pressure"

D_UPLOAD_UNREADABLE = (
    "That file could not be read as a weather CSV ({detail}). Upload an hourly PVGIS TMY file saved as .csv."
)
D_UPLOAD_COLUMNS = (
    "The file is missing the column(s) {names}, so it cannot be used. Upload a file that has GHI, T2m and WS10m."
)
D_SETUP_FAILED = "The inputs could not be set up ({detail}). Check the site and hardware values and try again."
