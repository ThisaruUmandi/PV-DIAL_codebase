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
STAGE_KEYS = ("decomposition", "transposition", "temperature", "dc", "ac")
# the one set, by lower-case key; every other list of stage names on any page is built from it
STAGE_NAME = {key: STAGE_NAMES[key.upper()] for key in STAGE_KEYS}
STAGE_NUMBERED = {key: f"{index} · {STAGE_NAME[key]}" for index, key in enumerate(STAGE_KEYS, start=1)}
STAGE_NAME_LIST = tuple(STAGE_NAME[key] for key in STAGE_KEYS)
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
STAGE_PILLS = STAGE_NAME_LIST
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
D_ALBEDO_LABEL = "Albedo"
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

# --- Shared field furniture (every page) ------------------------------------------------------
TAG_FROM_FILE = "from file"
TAG_REQUIRED = "required"
TAG_OPTIONAL = "optional"
TAG_DEFAULT = "default"
TAG_TITLES = {
    "file": "Read from the weather file; it cannot be edited here.",
    "required": "You must fill this in before you can continue.",
    "optional": "You can leave this empty.",
    "default": "Pre-filled with a standard value; change it if yours differs.",
    "user": "You changed this from its standard value.",
    "differs": "At least two of the three pipelines use different models at this stage.",
}

# --- Page 1: polish ------------------------------------------------------------------------------
D_CARD_FILE_SUB = "The hourly weather file for your site. It is checked as soon as it arrives."
D_CARD_OFFSET_SUB = "Which moment inside each hour the values stand for."
D_CARD_SITE_SUB = "Where the array is and what it is made of. Used by all three pipelines."
D_FILE_LABEL = "CSV file"
D_DROP_TEXT = "Drag a CSV here or click to browse"
D_DROP_NOTE = "Needs the columns GHI, T2m and WS10m. SP (surface pressure) is optional."
D_REPLACE_TEXT = "Replace file"
D_MSG_COLUMNS_OK = "Required columns found (GHI, T2m, WS10m, SP)"
D_MSG_COLUMNS_NO_SP = "GHI, T2m and WS10m found. SP is not in the file, so pressure is derived from the elevation"
D_MSG_COLUMNS_BAD = "Missing column(s): {names}"
D_MSG_TIERS_OK = "Tiers 1–4 passed · {n} warning{s}"
D_MSG_TIERS_WARN = "Tiers passed with {n} warning{s}; see the details"
D_MSG_TIERS_BAD = "Not passed · {n} problem{s}; see the details"
D_MSG_TIERS_WAIT = "Tiers 1–3 passed · tier 4 waits for the site and the time offset"
D_STRIP_FILE_ROWS = "{rows:,} rows"
D_CHECKLIST_TITLE = "Before you continue"
D_CHECKLIST_READY = "Everything is filled in."
D_CHECK_NAME = "Analysis name"
D_CHECK_FILE = "Weather file uploaded"
D_CHECK_TIERS = "File passes the checks"
D_CHECK_SITE = "Site coordinates"
D_CHECK_OFFSET = "Time offset"
D_CHECK_ORIENT = "Tilt, azimuth and albedo"
D_CHECK_HARDWARE = "Hardware and array size"
D_WAITS_FOR_FILE = "waits for the file"

# short names for the checklist ("still needed: ...")
D_STILL_NEEDED = "needs {names}"
N_NAME = "a value"
N_LAT = "latitude"
N_LON = "longitude"
N_REASON = "a reason"
N_TILT = "tilt"
N_AZIMUTH = "azimuth"
N_ALBEDO = "albedo"
N_MODULE = "module"
N_INVERTER = "inverter"
N_MODULES = "modules per string"
N_STRINGS = "strings per inverter"
N_HEIGHT = "module height"

# --- Page 2 · Pipeline configuration ---------------------------------------------------------------
C_INTRO = "One model per stage for each pipeline. Lists come from the pool for this module, in pool order."
C_COLUMN = "Pipeline {label}"
C_STAGE_LABELS = STAGE_NUMBERED
C_STAGE_HEADER = "Stage"
C_DIFFERS = "Differs across pipelines"
C_CHOOSE = "Choose a model"
C_ARIA_CELL = "Pipeline {label} {stage}"
C_EXAMPLE_BUTTON = "Fill with the thesis example"
C_EXAMPLE_NOTE = (
    "An example to try the tool, taken from analysis.yaml. It says nothing about which pipeline "
    "is closer to the real system."
)
C_EXAMPLE_SKIPPED = "Not filled in, because it is not available here: {names}."
# the mock-up marks a DC model in this list, because sapm also names a temperature model
C_STAGE_MARK = {"dc": " (DC)"}
C_NOT_SELECTABLE_TITLE = "Not selectable for this module"
C_NOT_SELECTABLE_SUB = "Shown with the reason; these cannot be chosen."
C_AC_FOLLOWS = (
    "AC options follow each pipeline's DC model: with pvwatts_dc, sandia and adr become unavailable (no v_dc)."
)
C_NOTE_OWN_PVWATTS = "pvwatts_dc gives no DC voltage, so {names} cannot follow it and are not offered."
C_NOTE_OTHER_PVWATTS = (
    "Another pipeline uses pvwatts_dc, which gives no DC voltage. {names} are not offered here, because "
    "mixing them would leave the attribution for that pair incomputable."
)
C_NOTE_DC_OWN_AC = "pvwatts_dc is not offered because this pipeline's AC model ({ac}) needs a DC voltage."
C_NOTE_DC_OTHER_AC = (
    "pvwatts_dc is not offered because another pipeline's AC model needs a DC voltage; mixing them would "
    "leave the attribution for that pair incomputable."
)
C_SETTINGS_TITLE = "Analysis settings"
C_SETTINGS_SUB = "Values that apply to the whole analysis."
C_TAU_LABEL = "τ (threshold)"
C_TAU_RESET = "Reset to default"
C_TAU_PROBLEM = "τ must be a number greater than 0."
TAG_USER_ENTERED = "user entered"
C_CONTINUE = "Continue to run"
C_BACK = "Back to data & site"
C_SAVED_FLASH = "Saved. Step 2 is complete."
C_CHECKLIST_PIPELINE = "Pipeline {label}: all five stages chosen"
C_CHECKLIST_TAU = "τ is a number above 0"
C_STILL_NEEDS = "needs {stages}"
C_NO_DATA = "Complete step 1 first: the pipelines are chosen from the pool for the module you picked there."
C_SETUP_FAILED = "The configuration could not be saved ({detail}). Check the choices and try again."

# --- Page 3 · Run & provenance ---------------------------------------------------------------------
R_EMPTY_TITLE = "Not run yet"
R_EMPTY_TEXT = (
    "The three pipelines you configured have not been run for this analysis. "
    "Press Run pipelines to run them. Every stage output is kept with the analysis."
)
R_RUN = "Run pipelines"
R_RUN_AGAIN = "Run again"
R_RUN_AGAIN_NOTE = "Running again gives the same values and adds no new records."
R_BACK = "Back to configuration"
R_GO_ANALYSIS = "Go to analysis"
R_GO_LOCKED = "Go to analysis opens once the pipelines have run."

# progress, in the order the steps happen
R_PROGRESS_TITLE = "Running the pipelines"
R_PROGRESS_LOAD = "Reading the weather file"
R_PROGRESS_SITE = "Setting up the site and the time offset"
R_PROGRESS_HARDWARE = "Preparing the module and inverter"
R_PROGRESS_PIPELINE = "Running pipeline {label}"
R_PROGRESS_SAVE = "Saving the results"
R_PROGRESS_READ_BACK = "Reading the saved stage outputs back"
R_PROGRESS_DONE = "Done"

R_FILE_MISSING = "The weather file stored for this analysis is no longer there. Go back to step 1 and upload it again."
R_RUN_FAILED = "The run could not finish ({detail}). Check the inputs on steps 1 and 2 and try again."
R_NOT_RUN_STORED = "This analysis has no stored run to open."
R_NOT_SAVED = "The stage outputs of pipeline {label} could not be read back from the provenance store."

R_BANNER_PASSED = "{n} pipelines ran · all checks passed"
R_BANNER_NOT_PASSED = "{n} pipelines ran · {failed} did not pass every check"
R_BANNER_SUB = "Every stage output is kept for the analysis."
R_RUN_TIME = "Run time"

# one card per pipeline
R_PIPELINE = "Pipeline {label}"
R_SAVED = "Stage outputs saved"
R_PASSED = "Passed"
R_NOT_PASSED = "Not passed"
R_CHECK_LABELS = {
    "decomposition": "DNI, DHI finite and ≥ 0",
    "transposition": "POA irradiance finite and ≥ 0",
    "temperature": "Cell temperature finite, ≥ air − 5 °C",
    "dc": "DC power finite and ≥ 0",
    "ac_not_exceeding_dc": "AC ≤ DC",
    "all_finite": "Every output column finite",
}

# pipeline outputs
R_OUT_TITLE = "Pipeline outputs"
R_OUT_SUB = "What each pipeline produced at each stage, side by side."
R_DOWNLOAD = "Download CSV"
R_STAGE = "Stage"
R_QUANTITY = "Quantity"
R_PERIOD = "Period"
R_PERIODS = {"day": "One day", "week": "One week", "month": "One month", "year": "Full year"}
R_DATE = "Date"
R_DATE_HELP = "The day, or the week or the month that contains this date."
R_STAGE_SHORT = STAGE_NAME
R_CHART_ALT = "Chart of the selected stage for pipelines A, B and C. A is a solid line with circles, B dashed with squares, C dotted with triangles."
R_TABLE_WINDOW = "In the period shown"
R_TOTAL_IRRADIATION = "Irradiation (kWh/m²)"
R_TOTAL_ENERGY = "Energy (kWh)"
R_MEAN_TEMP = "Mean over daylight hours (°C)"
R_PEAK = "Peak ({unit})"
R_MAX_TEMP = "Maximum in daylight hours (°C)"
R_PER_DAY = "per day"
R_PER_MONTH = "per month"
R_HOURLY = "hourly"
R_NO_DATA_IN_PERIOD = "This file has no rows in the period you chose."

# one table for every stored output column: plain name and unit. A column that is not here is
# shown by its stored key, with no unit (a unit is never guessed).
COLUMN_INFO = {
    "dni": ("DNI", "W/m²"),
    "dhi": ("DHI", "W/m²"),
    "aoi": ("Angle of incidence", "°"),
    "poa_global": ("POA global", "W/m²"),
    "poa_direct": ("POA direct", "W/m²"),
    "poa_diffuse": ("POA diffuse", "W/m²"),
    "poa_sky_diffuse": ("POA sky diffuse", "W/m²"),
    "poa_ground_diffuse": ("POA ground-reflected", "W/m²"),
    "temp_cell": ("Cell temperature", "°C"),
    "i_dc": ("DC current", "A"),
    "v_dc": ("DC voltage", "V"),
    "p_dc": ("DC power", "W"),
    "p_ac": ("AC power", "W"),
}
# the unit a yearly or period total has when the column's values are summed over time
TOTAL_UNIT = {"W/m²": "kWh/m²", "W": "kWh"}

# stage cards
R_CARD_STAGE = "Stage"
R_CARD_MODEL = "Model"
R_CARD_OUTPUT = "Output (year)"
R_CARD_CHECK = "Check"
R_MEAN_DAYLIGHT = "Mean over daylight hours"
R_DAYLIGHT_TIP = (
    "Daylight means the sun is more than {margin:g}° above the horizon (true zenith under {zenith:g}°), "
    "the same rule the comparison later uses."
)
R_DAYLIGHT_TIP_PLAIN = "Daylight means the sun is above the horizon, the same rule the comparison later uses."
R_FOOTER_FINITE = "Every output column finite"

# provenance summary (readable view)
R_PROV_TITLE = "Provenance for this run"
R_PROV_WEATHER = "Weather file"
R_PROV_ROWS = "{rows:,} rows, {start} to {end} ({spacing})"
R_PROV_SPACING_HOURLY = "hourly"
R_PROV_SPACING_OTHER = "every {minutes:g} min"
R_PROV_SITE = "Site"
R_PROV_SITE_VALUE = "latitude {latitude:g}° ({lat_src}), longitude {longitude:g}° ({lon_src}), elevation {elevation:g} m ({elev_src})"
R_PROV_OFFSET = "Time offset"
R_PROV_TAU = "τ (threshold)"
R_PROV_PVLIB = "pvlib version"
R_PROV_STARTED = "Started"
R_PROV_FINISHED = "Finished"
R_PROV_SET = "Execution set"
R_PROV_RECORDS = "{set} · {n} records"
R_PROV_NOT_RECORDED = "not recorded"
R_PROV_REASON = "reason: {reason}"

# lineage (closed by default)
R_LINEAGE_OPEN = "Show the provenance records"
R_LINEAGE_NOTE = "One record per pipeline, read from what the run stored. Stages run in this order, each using what comes before it."
R_LINEAGE_WEATHER = "Weather file"
R_LINEAGE_CONFIG = "Configuration"
R_LINEAGE_CONFIG_USED = "Every stage used this configuration."
R_LINEAGE_CONFIG_USED_SOME = "Used by: {stages}."
R_LINEAGE_SETTINGS = "Settings"
R_LINEAGE_NO_SETTINGS = "No settings recorded beyond the model."
R_LINEAGE_USED_WEATHER = "the weather file"
R_LINEAGE_USED_STAGE = "the output of {stage} ({columns})"
R_LINEAGE_USED_NOTHING = "nothing recorded"
R_LINEAGE_STATEMENT = "{stage} ({model}) used {used} and produced {produced}, {rows:,} rows."
R_LINEAGE_NO_WEATHER_LINK = (
    "This stage also reads air temperature and wind speed from the weather file. The record does not carry that link."
)
R_LINEAGE_STAGE_NAMES = STAGE_NAME
# plain names for stored settings; a key that is not here is shown as stored. A unit appears only
# where the stored key carries one (its suffix).
SETTING_LABELS = {
    "surface_tilt_deg": "Tilt",
    "surface_azimuth_deg": "Azimuth",
    "albedo": "Albedo",
    "albedo_source": "Albedo source",
    "module_name": "Module",
    "module_library": "Module library",
    "inverter_name": "Inverter",
    "inverter_library": "Inverter library",
    "modules_per_string": "Modules per string",
    "strings_per_inverter": "Strings per inverter",
    "mounting_geometry": "Mounting geometry",
    "mounting_geometry_source": "Mounting geometry source",
    "mounting_construction": "Mounting construction",
    "mounting_construction_source": "Mounting construction source",
    "module_height_m": "Module height",
}
# only suffixes that mean one thing; "_s" is left out because it also ends names like R_s (a resistance)
SETTING_UNIT_SUFFIX = (("_deg", "°"), ("_m", " m"), ("_h", " h"), ("_w_m2", " W/m²"))

# technical identifiers (closed by default)
R_IDS_OPEN = "Technical identifiers"
R_IDS_NOTE = (
    "These identifiers let a stored record and its data be matched byte for byte; they are for checking, not for reading."
)
R_PROV_RUN_ID = "Run ID"
R_PROV_FILE_SHA = "File SHA-256"
R_PROV_FILE_SHA_HELP = "Fingerprint of the file you uploaded, byte for byte."
R_PROV_DATA_HASH = "Input data hash (provenance)"
R_PROV_DATA_HASH_HELP = (
    "Fingerprint of the weather data after it was read and prepared. The provenance records carry this one."
)
R_IDS_RECORD = "Record ID"
R_IDS_STAGE_HASH = "{stage} output"

# --- Page 4 · Analysis --------------------------------------------------------------------------------
P4_VIEW_RUN = "View run provenance"
P4_PAIR = "{a} – {b}"
P4_P1_BUTTON = "Run Phase 1 — Localisation"
P4_P1_CAPTION = "Where disagreement first exceeds τ"
P4_P2_BUTTON = "Run Phase 2 — Propagation"
P4_P2_CAPTION = "How disagreement grows or shrinks"
P4_P3_BUTTON = "Run Phase 3 — Contribution"
P4_P3_CAPTION = "Each stage's share of the final gap"
P4_LOCKED = "Phase 2 and Phase 3 unlock after Phase 1 has run — they use its results."
P4_RAN = "Done · running again gives the same values."
P4_PROGRESS_TITLE = "Running Phase 1"
P4_PROGRESS_REBUILD = "Rebuilding the pipelines from the stored inputs"
P4_PROGRESS_COMPARE = "Comparing the pipelines stage by stage"
P4_PROGRESS_SAVE = "Saving the Phase 1 result"
P4_FAILED = "Phase 1 could not finish ({detail}). Go back to step 3 and run the pipelines again."

P4_OUTCOME = "Outcome {n}"
P4_K = "k = {stage}"
P4_K_NONE = "k = none"
P4_K_TIP = HELP_K
P4_NOT_COMPUTABLE_TITLE = "Not computable"

# k band (KT E.2): where k stays the same as τ changes, from the stored nRMSD values only
P4_BAND_FIRST = "k stays at {stage} for any τ below {upper}"
P4_BAND_LATER = "k stays at {stage} for τ from {lower} up to, but not including, {upper}"
P4_BAND_NONE = "No stage is over τ for any τ at or above {upper}"

P4_HEAT_TITLE = "Disagreement map · pair × stage"
P4_HEAT_SUB = (
    "nRMSD per stage. Darker = larger. A heavy outline and the words “over τ” mark cells above τ = {tau}."
)
P4_OVER_TAU = "over τ"
P4_WITHIN_TAU = "within τ"
P4_FIRST_OVER = "First stage over τ"
P4_NA = "not computable"
P4_HEAT_AXIS = STAGE_NAME_LIST
P4_STAGE_TITLE = "Stage table against τ"
P4_STAGE_PAIR = "Pair"
P4_COL_STAGE = "Stage"
P4_COL_NRMSD = "nRMSD"
P4_COL_AGAINST = "Against τ = {tau}"
P4_COL_MODELS = "Models at this stage"
P4_MODELS_SAME = "Same model"
P4_MODELS_DIFFER = "{a}: {model_a}<br>{b}: {model_b}"
P4_UNITLESS = "nRMSD is unitless. The vertical line marks τ = {tau}."
P4_TAU_TEXT = "{value:g} ({source})"

P4_DEFS_OPEN = "What these numbers mean"
P4_METHOD_OPEN = "Method note"
P4_FULL_OPEN = "Full Phase 1 table"
P4_DEF_OUTCOMES = (
    "Outcome 1: no stage exceeds τ.",
    "Outcome 2: some stage exceeds τ and the final AC difference is above τ.",
    "Outcome 3: some stage exceeds τ but the final AC difference is below τ.",
)
P4_METHOD_LINES = (
    "Both pipelines are compared on daylight rows only (sun more than {margin:g}° above the horizon).",
    "Each stage's nRMSD divides the RMSD by the P95 − P5 range of both pipelines' values pooled together.",
    "A stage with too few daylight samples, or no spread in the pooled values, is not computable.",
    "k is the first stage, in pipeline order, where nRMSD is above τ.",
)
P4_METHOD_LINES_PLAIN = P4_METHOD_LINES[1:]
P4_FULL_COLUMNS = ("Pair", "Stage", "Unit", "RMSD", "nRMSD", "MAD", "MBD", "Systematic share", "Pooled values")
P4_FULL_UNITLESS = "–"
P4_PHI_NEGATIVE = "φ can be negative. The stages still add up to RMSD(A,B)."
P4_PHASE2_NOT_RUN_FAILED = "not run — a pipeline failed its checks"
P4_DERIVED_NOTE = "Shown from Phase 1: nothing to run."

# --- Page 4 · Phase 2 -----------------------------------------------------------------------------------
P4_P2_TITLE = "Propagation profile · nRMSD by stage"
P4_P2_SUB = (
    "Phase 2 reads the Phase 1 values of all three pairs: one line per pair, with τ = {tau} drawn as a horizontal line."
)
P4_P2_PROGRESS_TITLE = "Running Phase 2"
P4_P2_PROGRESS_READ = "Reading the Phase 1 values of the three pairs"
P4_P2_PROGRESS_SAVE = "Saving the Phase 2 result"
P4_P2_FAILED = "Phase 2 could not finish ({detail})."
P4_P2_COL_MEAN = "Mean"
P4_P2_COL_MAX = "Max"
P4_P2_COL_DELTA = "Δ"
P4_P2_NOTE = "Across the three pairs. Δ = change in the mean from the previous stage."
P4_P2_DEFS = (
    ("Mean", "The average of the three pairs' nRMSD at a stage."),
    ("Max", "The largest of the three pairs' nRMSD at a stage."),
    ("Δ", "The change in the mean from the previous stage; the first stage is compared with 0."),
)
P4_P2_CHART_ALT = (
    "Line chart of nRMSD by stage for the pairs A–B, A–C and B–C, with a horizontal line at τ. "
    "A–B is a solid line with diamonds, A–C dashed with crosses, B–C dash-dotted with triangles."
)
P4_P2_NOT_RUN_TITLE = "Phase 2"
P4_P2_STAGE = "Stage"
P4_MINUS = "−"

# --- Page 4 · Phase 3 -----------------------------------------------------------------------------------
P4_P3_PICK = "Pair"
P4_P3_TITLE = "Contribution to the final AC gap · {pair}"
P4_P3_SUB = "Stages in pipeline order"
P4_P3_COL_PHI = "φ {a}→{b} ({unit})"
P4_P3_COL_PHI_FINAL = "φ final ({unit})"
P4_P3_COL_SHARE = "Share"
P4_P3_SHARE_UNDEFINED = "not defined: RMSD is 0"
P4_P3_EFF = "Efficiency check: the stages' φ final add up to {total} {unit}; RMSD({a},{b}) is {rmsd} {unit}."
P4_P3_EFF_DIFF = "They differ by {diff} {unit}."
P4_P3_WATERFALL_TITLE = "How the final AC gap builds up · {pair}"
P4_P3_WATERFALL_SUB = "Each stage adds its φ final; the stages sum to RMSD({a},{b})."
P4_P3_TOTAL_BAR = "RMSD({a},{b})"
P4_P3_BAR_SAME = "same model"
P4_P3_AXIS = "Contribution ({unit})"
P4_P3_ALT = (
    "Waterfall chart: one bar per stage, each starting where the previous one ended, and a final bar for "
    "RMSD({a},{b}). Every bar carries its value."
)
P4_P3_PENDING = "Not run yet. Press Run Phase 3 to attribute the final AC difference of this pair."
P4_P3_INVALID_COUNT = "{n} of the stage combinations cannot be run, so no value is given."
P4_P3_PROGRESS_TITLE = "Running Phase 3"
P4_P3_PROGRESS_PAIR = "Attributing the final AC difference for {pair} ({i} of {n}). This takes a few seconds."
P4_P3_PROGRESS_SAVE = "Saving the Phase 3 result"
P4_P3_FAILED = "Phase 3 could not finish ({detail})."

# --- Page 5 · Guided re-execution -----------------------------------------------------------------------
RX_OPTIONAL = "Optional"
RX_INTRO = "Swap one model at the pair's localised stage, re-run, and compare."
RX_EMPTY = "No pair has a first stage over τ, so there is nothing to substitute. The Report is still available."
RX_GO_REPORT = "Go to the Report"
RX_PAIR = "Pair (only pairs with a k)"
RX_PAIR_PLACEHOLDER = "Choose a pair"
RX_PAIR_OPTION = "{pair} · Outcome {n}"
RX_STAGE_FIXED = "Localised stage (from Phase 1, fixed)"
RX_ANCHOR = "Pipeline to modify (anchor)"
RX_ANCHOR_OPTION = "{a} — compare the result with {b}"
RX_CANDIDATE = "Candidate at {stage} (pool order)"
RX_RUN = "Run substitution"
RX_RUN_NEEDS = "Choose a pair, an anchor and a candidate to run a substitution."
RX_SENTENCE = (
    "Every attempt starts from the original {anchor} and changes only {stage}. "
    "Earlier attempts stay in the provenance record but never carry over."
)
RX_NOT_SELECTABLE_TITLE = "Not selectable here"
RX_NOT_SELECTABLE_SUB = "Shown with the reason; these cannot be chosen."
RX_REASON_CURRENT = "already the model in {anchor}"
RX_PROGRESS_TITLE = "Running the substitution"
RX_PROGRESS_RUN = "Running {anchor} with {candidate} at {stage}"
RX_PROGRESS_COMPARE = "Comparing it with {other}"
RX_PROGRESS_SAVE = "Saving the attempt"
RX_PROGRESS_CONFIRM = "Running the confirmed substitution"
RX_FAILED = "The substitution could not run ({detail})."
RX_RESULT_TITLE = "Disagreement with {other} · nRMSD"
RX_RESULT_SUB = "Attempt {n}: {candidate} at {stage}, anchor {anchor}, pair {pair}."
RX_COL_BEFORE = "Before"
RX_COL_AFTER = "After"
RX_COL_CHANGE = "Change"
RX_ROW_OUTCOME = "Outcome and k"
RX_OUTCOME_K = "Outcome {n}, {k}"
RX_CHART_ALT = (
    "Line chart of nRMSD by stage for the pair, before the substitution (dashed, squares) and after it "
    "(solid, circles), with a horizontal line at τ."
)
RX_ATTEMPTS_TITLE = "Attempts in this session"
RX_ATTEMPTS_NONE = "No attempt has been run for this pair yet."
RX_ATTEMPT_COLUMNS = ("Attempt", "Anchor", "Candidate", "Outcome", "k")
RX_VIEW = "Attempt shown"
RX_ATTEMPT_LABEL = "Attempt {n}"
RX_YIELD_OPEN = "Show annual yield"
RX_YIELD_NOTE = "Annual AC energy over the file, in kWh."
RX_YIELD_ORIGINAL = "{anchor} (original)"
RX_YIELD_SUBSTITUTED = "{anchor} with {candidate}"
RX_CONFIRM = "Confirm {candidate}"
RX_CONFIRM_ASK = "Save {candidate} at {stage} for {anchor} in {pair} as the confirmed change?"
RX_CONFIRM_REPLACES = "This replaces the confirmed change: {change}."
RX_CONFIRM_YES = "Save"
RX_CONFIRM_NO = "Cancel"
RX_YIELD_CHECK = "Also compute the annual yield on confirm"
RX_CONFIRM_ONLY_RUN = "Confirm is offered for an attempt that has been run in this session."
RX_CONFIRMED_TITLE = "Confirmed change"
RX_CONFIRMED_CHANGE = "{pair} · {stage}: {candidate}"
RX_CONFIRMED_SAVED = "Saved. The confirmed change is {change}."
RX_CONFIRMED_ANCHOR = "Anchor"
RX_CONFIRMED_CANDIDATE = "Candidate"
RX_CONFIRMED_STAGE = "Stage"
RX_CONFIRMED_MODELS = "Models of the confirmed pipeline"
RX_CONFIRMED_YIELD = "Annual AC energy"
RX_NOT_RECORDED = "not recorded for this analysis"
RX_NOT_COMPUTABLE_AFTER = "After the substitution: {text}"
RX_OPTIONAL_TITLE = "This step is optional. The Report does not need it."
RX_YIELD_NONE = "not computed"
RX_COL_ATTEMPT = "Attempt {n}"
RX_CURRENT = "current"
RX_COL_CONFIRMED = "Confirmed {model}"
RX_COL_CONFIRMED_PLAIN = "Confirmed"
RX_YIELD_STRIP = "Annual yield · {change} (confirmed)"
RX_NO_RESULTS = "Choose a pair, an anchor and a candidate, then run a substitution to see how the disagreement changes."
RX_ATTEMPTS_SUB = "Attempts of this session for this pair, in the order made."
RX_CONFIRMED_FACTS_SUB = "What is saved with this analysis."
RX_RESULT_TITLE_PLAIN = "Disagreement · nRMSD"
