# PV-DIAL

PV-DIAL compares pvlib simulation pipelines stage by stage. For each pair of pipelines it shows the first stage where they differ by more than a threshold (τ), how that difference carries through the later stages, and how much each stage contributes to the final AC difference. It reports where the pipelines differ and by how much. It does not say which pipeline is right.

## Technology stack

Versions come from `pyproject.toml` where it pins them. Otherwise the version is the one installed in `.venv`, marked "installed".

| Layer | Technology | Version | Used for |
| --- | --- | --- | --- |
| Language | Python | 3.11 or newer (`pyproject.toml`); 3.13.9 installed | All code |
| Interface | Streamlit | 1.64.0 (installed) | The web interface in `app/` |
| Charts | Altair | 6.3.0 (installed) | Charts in the interface and the report |
| Charts | Vega, Vega-Lite, Vega-Embed | 6.4.0, 6.4.1, 7.3.0 (`app/vendor/vega/VERSIONS.json`) | Draw the charts in the downloaded HTML report, offline |
| Charts | Plotly | 7.1.0 (installed) | Declared in `pyproject.toml`; not used by PV-DIAL's own code (no import in `src/`, `app/`, `tests/` or `experiments/`). Streamlit lists it only as an optional extra |
| PV modelling | pvlib | 0.15.2 (pinned) | Solar position, the stage models, the CEC module and inverter lists |
| Numerical | pandas | 3.0.5 (installed) | Weather tables and stage outputs |
| Numerical | NumPy | 2.5.3 (installed) | Array work |
| Numerical | SciPy | 1.18.1 (installed) | Required by pvlib (`scipy>=1.7.2` in pvlib's metadata), which uses it in its numerical routines. Declared in `pyproject.toml`; not used by PV-DIAL's own code (no direct import in `src/` or `app/`) |
| Configuration | PyYAML | 6.0.3 (installed) | Reads `analysis.yaml` and `configs/run_defaults.yaml` |
| Configuration | python-dotenv | 1.2.3 (installed) | Reads `.env` |
| Database | PostgreSQL | 17.11 (installed); version not pinned | The provenance store (JSONB columns) |
| Database driver | psycopg (binary) | 3.3.6 (installed) | Connects to PostgreSQL |
| Provenance | prov | 3.2.2 (installed) | Builds the provenance documents |
| Report | Jinja2 | 3.1.6 (installed) | Fills the HTML report template |
| Testing | pytest | 9.1.1 (installed, `dev` extra) | Test runner |
| Linting | Ruff | 0.16.8 (installed, `dev` extra) | Lint checks (line length 100, target Python 3.11) |
| Other (`dev` extra) | matplotlib | 3.11.2 (installed) | Figure scripts in `experiments/` |
| Other (`dev` extra) | watchdog | 6.0.0 (installed) | Used by Streamlit, when installed, to watch source files for changes (otherwise it polls). Streamlit requires it on platforms other than macOS. Declared in `pyproject.toml`; not used by PV-DIAL's own code |

## How the code is organised

The code has five layers (data, physics, diagnostic, orchestration and interface) plus provenance storage. The orchestration, diagnostic and interface layers write to or read from the storage.

| Layer | Where | What it holds |
| --- | --- | --- |
| Data | `src/pvdials/data/` | `upload.py` reads the CSV and stores it. `column_mapper.py` maps column names and finds the site and time offset. `preprocess.py` cleans the table. `validate.py` runs the checks. |
| Physics | `src/pvdials/physics/` | `site.py` (solar position, daylight mask), `adapters/` (one adapter per stage), `registry.py` (which models belong to which stage), `pipeline.py` (runs one pipeline), plus `hardware.py`, `geometry.py`, `mounting.py`, `shared_inputs.py` and `version.py`. |
| Diagnostic | `src/pvdials/dla/`, `src/pvdials/guided_reexecution.py` | `metrics.py` (RMSD, nRMSD and others), `phase1.py` (first stage over τ), `phase2.py` (propagation), `phase3.py` (Shapley attribution). `guided_reexecution.py` swaps one model and re-runs. |
| Orchestration | `src/pvdials/analysis.py`, `__main__.py`, `report.py`, `config.py`, `configs/run_defaults.yaml` | `analysis.py` runs the steps in order and saves after each one. `__main__.py` is the command line. `report.py` shapes results into rows. |
| Interface | `app/` | The Streamlit pages in `app/screens/`, the page logic in `app/*_logic.py`, `services.py`, `state.py`, `gating.py` and the report files. |
| Storage | `src/pvdials/provenance/`, `data/uploads/` | `schema.sql` and `db.py` for PostgreSQL. `recorder.py`, `model.py`, `replay.py` and `analyses.py` write and read records. Uploaded files sit in `data/uploads/`. |

A run flows through the layers like this:

1. **Upload.** The interface sends the file to the data layer. The file is stored in `data/uploads/`, its columns are mapped, it is cleaned, and tiers 1 to 3 of the checks run.
2. **Site and time offset.** The physics layer builds one shared site context (solar position and daylight mask). Tier 4 of the checks runs on it. The inputs are saved to the `analyses` table.
3. **Run.** Pipelines A, B and C run stage by stage on the same weather, site and hardware. The recorder writes the stage outputs and one provenance record per run to PostgreSQL.
4. **Analysis.** The diagnostic layer reads the stage outputs and computes Phase 1, then Phase 2 and Phase 3. The results are saved to the analysis row.
5. **Guided re-execution (optional).** One model is swapped at the stage found by Phase 1. The attempt is recorded.
6. **Report.** The Report page and its three downloads are built only from what is stored. No pipeline runs when a report opens.

**pvlib and PV-DIAL's own code.** pvlib supplies the physical models: solar position, decomposition, transposition, cell temperature, DC power and AC conversion, and the CEC module and inverter lists. The adapters in `src/pvdials/physics/` call pvlib, and a guard test keeps pvlib imports inside that folder. PV-DIAL's own Python code chooses which models form each stage's pool, gives all pipelines the same inputs, runs them, compares their outputs (Phase 1 to 3), records provenance, and provides the command line, the interface and the report.

## Project structure

```
PV-DIAL/
├── .streamlit/
│   └── config.toml              Streamlit theme and server settings
├── app/                         Streamlit interface
│   ├── main.py                  Entry point (streamlit run app/main.py)
│   ├── page_map.py              Which screen each page shows
│   ├── gating.py                Which steps are open, done or locked
│   ├── state.py                 Session state
│   ├── store.py                 Checks that the database is reachable
│   ├── services.py              Step 1 logic: read the file, check the form, save
│   ├── config_logic.py          Step 2 logic: model pools and options
│   ├── run_logic.py             Step 3 logic: run and read back stage outputs
│   ├── analysis_logic.py        Step 4 logic: Phase 1 to 3 views
│   ├── analysis_charts.py       Altair charts for step 4
│   ├── reexec_logic.py          Step 5 logic: guided re-execution
│   ├── report_logic.py          The Report, built from stored data
│   ├── report_export.py         The three downloads
│   ├── report_html.py           The downloadable HTML report
│   ├── past_logic.py            Past analyses and Home's recent rows
│   ├── session_load.py          Open, Continue and Duplicate
│   ├── components.py            Shared Streamlit pieces (sidebar, headings)
│   ├── tables.py                HTML tables shared by pages and report
│   ├── theme.py                 Loads the stylesheet
│   ├── wording.py               All interface text
│   ├── screens/                 One module per page
│   ├── static/                  Stylesheets
│   ├── templates/               The HTML report template
│   └── vendor/                  Vendored Vega files (see Third-party software)
├── configs/
│   └── run_defaults.yaml        Run defaults, written into provenance
├── data/
│   └── weather/                 Weather CSV files used by analysis.yaml and some tests
├── docs/
│   ├── EVALUATION.md            How to re-run the evaluation
│   ├── evaluation-kt.md         Notes for the evaluation work
│   └── verification-properties.md   List of testable properties
├── experiments/                 Scripts that are not part of the package
│   ├── evaluation/              Evaluation steps and the test-database guard
│   ├── tau_calibration/         Scripts for choosing τ
│   ├── pool_scan.py             Runs every valid model chain and checks outputs
│   ├── spike_model_list.py      Early check of pvlib models
│   └── spike_n21_bug.py         Early check of one issue (N21)
├── src/
│   └── pvdials/                 The Python package (data, physics, dla, provenance)
├── tests/
│   ├── conftest.py              Forces the test database and runs the guard
│   ├── storage_helpers.py       Worker for a cross-process re-run test
│   ├── dla/                     Tests of the metrics and Phase 1 to 3
│   ├── evaluation/              Tests of the evaluation scripts
│   ├── fixtures/                Small weather files and a stored row
│   ├── guards/                  Rules that scan the code (layers, wording)
│   ├── interface/               Tests of the interface
│   └── unit/                    Tests of the package modules
├── .env                         DATABASE_URL
├── .gitignore
├── LICENSE
├── README.md
├── analysis.yaml                Example input for the command line
└── pyproject.toml               Package, dependencies, pytest and Ruff settings
```

Some folders are in `.gitignore` and are left out of the tree above: `.venv/`, the caches, `outputs/` (where the command line writes results), `backups/` and `data/uploads/`.

## Requirements

- Python 3.11 or newer (`requires-python` in `pyproject.toml`). The project has been run with Python 3.13.9.
- PostgreSQL, running on your machine. The project has been run with PostgreSQL 17.11. The schema uses JSONB columns.

## Setup

Run these from the repository root.

1. Create and activate a virtual environment, then install the package with the `dev` extra:

   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

   Only pvlib is pinned (`pvlib==0.15.2`). A new install may get newer versions of the other packages than the stack table shows.

2. Put one line in a file named `.env` in the repository root:

   ```
   DATABASE_URL=postgresql://localhost:5432/pvdials_dev
   ```

   This is also the value the code uses if `DATABASE_URL` is not set.

3. Create the two databases and their tables:

   ```
   createdb pvdials_dev
   python -m pvdials db init
   createdb pvdials_test
   DATABASE_URL=postgresql://localhost:5432/pvdials_test python -m pvdials db init
   ```

### Databases

- The CLI and the app use `pvdials_dev` (`DATABASE_URL` in `.env`).
- Tests use `pvdials_test` (forced by `tests/conftest.py`; a guard refuses `pvdials_dev`).
- On a new machine create the test database first: see step 3 of Setup above.

## Running the app

With the virtual environment active, run this from the repository root:

```
streamlit run app/main.py
```

Streamlit prints the local address in the terminal. If PostgreSQL is not running, the app says that the provenance store cannot be reached.

## How to use

The sidebar lists Home, the six steps and Past analyses. Steps open one at a time. Changing an earlier input clears the steps after it, and the app asks you to confirm first. Each analysis is saved as you go.

1. **Home.** Read what the analysis shows and what you need before you start. Choose **Start new analysis**. Recent analyses are listed here too.
2. **Step 1, Data & site.** Name the analysis and upload a weather CSV. The page lists the columns it found and the results of the file checks. Choose the time offset: the file header's value, hour-start (0 h) or hour-centre (0.5 h). Give a reason if you differ from the header. Enter the site (latitude and longitude if the file has none, elevation is optional), tilt, azimuth, albedo (default 0.2), mounting geometry, construction, module, inverter, modules per string, strings per inverter and module height. Choose **Continue to configuration**.
3. **Step 2, Pipeline configuration.** For pipelines A, B and C, choose one model for each of the five stages: decomposition, transposition, cell temperature, DC power and AC conversion. Models that cannot be chosen are shown with the reason. Check τ under Analysis settings. Choose **Continue to run**.
4. **Step 3, Run & provenance.** Choose **Run pipelines**. The page shows the checks for each pipeline, their outputs stage by stage, and the provenance of the run. Choose **Go to analysis**.
5. **Step 4, Analysis.** Choose **Run Phase 1** to see, for each pair, the first stage whose nRMSD is above τ. Phase 2 (how the difference carries through the stages) and Phase 3 (each stage's share of the final AC difference) open after Phase 1 has run.
6. **Step 5, Guided re-execution (optional).** This step opens when a pair has a first stage over τ. Choose that pair, the pipeline to modify (the anchor) and one candidate model at the localised stage. Choose **Run substitution** to see how the nRMSD changes. Each attempt starts from the original anchor. You can confirm one change to save it with the analysis.
7. **Step 6, Report.** The whole analysis is on one page. Download the files described under Downloads. **Start new analysis** or **Back to past analyses** is at the foot of the page.
8. **Past analyses.** Every saved analysis is listed. You can search by name or weather file, filter by All, Complete or Stopped, and order by newest, oldest or name. Each row has three actions:
   - **Open** shows a finished analysis on the Report page, read-only.
   - **Continue** reopens an unfinished analysis at the step where it stopped. If the stored weather file is gone, the app tells you to upload it again.
   - **Duplicate** starts a new analysis with the same inputs. Nothing is run. Saved analyses are never edited.

## Weather input

You upload a `.csv` file on step 1. The file must be UTF-8 text with one row per hour.

- **Header lines.** Lines above the table are kept as text. The table starts at the first line that has a time column, and it ends at the first blank line. Latitude, longitude, elevation and an irradiance time offset are read from the header lines when they are there.
- **Required fields.** Column names are matched without regard to case:

  | Field | Accepted column names |
  | --- | --- |
  | Time | `time`, `datetime`, `time(UTC)`, `date`, `timestamp` |
  | GHI | `ghi`, `g(h)`, `global horizontal irradiance` |
  | T2m | `t2m`, `temp_air`, `temperature`, `air temperature` |
  | WS10m | `ws10m`, `wind_speed`, `wind speed` |

- **Optional fields.** `sp` (also `surface_pressure`, `surface pressure`, `pressure`) is surface pressure in Pa. If it is missing, pressure is derived from the elevation. Relative humidity is range-checked if present. Columns for DNI and DHI are dropped, because Stage 1 derives them from GHI.
- **If a required field is missing,** the file cannot be used. The page names the missing columns and asks for a file that has GHI, T2m and WS10m. **Continue** stays blocked.
- **File checks.** Missing values, duplicate timestamps and gaps in the hourly series are problems that block **Continue**. Out-of-range values (for example negative GHI, or pressure outside 30,000 to 110,000 Pa) also block it. Warnings, such as a file that is not 8,760 rows, do not.
- **Timestamps.** Formats such as `20200101:0000` and `2020-01-01 00:00` are read. Times are treated as UTC. Rows are moved onto one non-leap year by month, day and hour, so a file with a 29 February row is not accepted.
- **Storage.** The uploaded file is stored in `data/uploads/`, named by the SHA-256 hash of its content (`<hash>.csv`). The same content is stored once. `data/uploads/` is not in git.

## Downloads

The Report page has three downloads. Each file name starts with the analysis name and the saved date.

| Button | File | What it holds |
| --- | --- | --- |
| Download report (HTML) | `..._report.html` | One file that opens with no internet connection. It has the same sections, charts and tables as the Report page. |
| Results (CSV) | `..._results.csv` | One tidy table (columns `section`, `pair`, `pipeline`, `stage`, `quantity`, `value`, `unit`, `text`). It holds the run's settings, annual energies, Phase 1 metrics, Phase 2, Phase 3 (including signed φ) and the confirmed change. |
| Provenance (PROV-JSON) | `..._provenance.json` | One JSON file holding one PROV-JSON document per record, each unchanged. |

## Command line

The command line runs an analysis without the interface. PostgreSQL must be running, because the run is saved to it.

```
python -m pvdials run analysis.yaml --out outputs/my_run
python -m pvdials list
python -m pvdials db init
```

- `run` reads an analysis file, runs every step, prints a summary and writes `results.json`, `stage_outputs.csv` and `provenance.json` to the `--out` folder. `analysis.yaml` in the repository root is an example.
- `list` lists the saved analyses.
- `db init` creates or updates the tables.

An analysis file has the keys `name`, `weather_file`, `time_offset`, `site`, `hardware` and `pipelines` (exactly A, B and C, each with the five stages). `reexecution` is optional.

## Tests

Run the tests from the repository root with the virtual environment active:

```
python -m pytest
```

Use `python -m pytest`. The bare `pytest` command does not find the `experiments` package that `tests/conftest.py` imports.

- The tests use `pvdials_test` only. `tests/conftest.py` sets `DATABASE_URL` to `TEST_DATABASE_URL` (default `postgresql://localhost:5432/pvdials_test`) before any test file is imported.
- A guard in `experiments/evaluation/db_safety.py` raises an exception if that URL contains `pvdials_dev`. Nothing is collected or run in that case.
- Create `pvdials_test` and its tables first (see Setup). Several tests are skipped if PostgreSQL cannot be reached. One test needs Chrome or Chromium and is skipped without it.
- Slow tests (real multi-minute runs on full-size data) are left out by default. Run only the slow tests with `python -m pytest -m slow`. Run everything with `python -m pytest -m ""`.
- Lint checks: `ruff check src app tests`.

## Evaluation

- The scripts in `experiments/` evaluate PV-DIAL's diagnostic method against simpler methods used for comparison.
- The 26 testable properties in `docs/verification-properties.md` are tested by the normal test suite.
- The calibration and evaluation scripts are in `experiments/tau_calibration/` and `experiments/evaluation/`.
- They need the thesis weather file (`data/weather/tmy_6.944_79.856_2005_2020.csv`) and a database. Step 0 needs a database other than `pvdials_dev`. Steps 2 and 5 use `DATABASE_URL`.
- Results are reported in the dissertation, not here.
- The scripts, their order, commands, inputs and outputs are in [docs/EVALUATION.md](docs/EVALUATION.md).

## Third-party software

### Direct dependencies

Versions are the ones installed in `.venv`. Licences are read from each package's installed metadata (the licence field, or the licence classifier where the field holds no licence name).

| Package | Version | Licence (from package metadata) |
| --- | --- | --- |
| pvlib | 0.15.2 | BSD-3-Clause |
| pandas | 3.0.5 | BSD 3-Clause License |
| NumPy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| SciPy | 1.18.1 | BSD License (classifier) |
| PyYAML | 6.0.3 | MIT |
| Streamlit | 1.64.0 | Apache-2.0 |
| Altair | 6.3.0 | BSD License (classifier) |
| Plotly | 7.1.0 | MIT |
| psycopg, psycopg-binary | 3.3.6 | LGPL-3.0-only |
| python-dotenv | 1.2.3 | BSD-3-Clause |
| prov | 3.2.2 | MIT |
| Jinja2 | 3.1.6 | BSD License (classifier) |
| pytest (`dev`) | 9.1.1 | MIT |
| Ruff (`dev`) | 0.16.8 | MIT |
| matplotlib (`dev`) | 3.11.2 | Matplotlib licence; classifier: Python Software Foundation License |
| watchdog (`dev`) | 6.0.0 | Apache-2.0 |

### Vendored files

`app/vendor/vega/` holds Vega, Vega-Lite and Vega-Embed, so that the downloaded HTML report opens with no internet connection. The versions come from `app/vendor/vega/VERSIONS.json`.

| Package | Version | File | Licence | Licence file |
| --- | --- | --- | --- | --- |
| Vega | 6.4.0 | `vega.min.js` | BSD-3-Clause | `app/vendor/vega/LICENSE-vega` |
| Vega-Lite | 6.4.1 | `vega-lite.min.js` | BSD-3-Clause | `app/vendor/vega/LICENSE-vega-lite` |
| Vega-Embed | 7.3.0 | `vega-embed.min.js` | BSD-3-Clause | `app/vendor/vega/LICENSE-vega-embed` |

## Licence

PV-DIAL is under the BSD 3-Clause licence. See [LICENSE](LICENSE).
