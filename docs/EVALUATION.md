# PV-DIAL: re-running the evaluation

All paths in this file are relative to the repository root.

The scripts in `experiments/` evaluate PV-DIAL's diagnostic method against simpler methods used for comparison (Baseline A, Baseline B and OAT). They also hold the scripts that calibrated τ. Results are reported in the dissertation, not here.

**Properties.** `docs/verification-properties.md` lists 26 testable properties. They are tested by the normal test suite (`python -m pytest`). Tests in `tests/unit/`, `tests/dla/` and `tests/guards/` name the property they cover in their docstrings, for example "Verification property #16". The tests in `tests/evaluation/` cover the evaluation helper modules. `test_step3_cases.py` there is marked slow.

**How to run.** Run every script from the repository root with the virtual environment active. Evaluation scripts run as modules (`python -m experiments.evaluation.<name>`). Calibration scripts run by path. `matplotlib` and `pytest` (the `dev` extra) are needed by some of them.

**Weather file.** Evaluation steps 0, 2, 3, 4, 4b and 5 read `data/weather/tmy_6.944_79.856_2005_2020.csv`, and `weather_source.py` checks its SHA-256 (`9828d22b6291d0f84d5c6d87331a5487109e3dd436e39f9809eaae03d408ebeb`) before each of them starts. A missing or changed file stops the script. The calibration scripts read the same file by path.

**Database.** `tests/conftest.py` and step 0 refuse `pvdials_dev`. Step 0 deletes every row in `stage_output_values` and `provenance_records` in the database it runs against. Steps 2 and 5 do not check the database name. They use `DATABASE_URL`, which `.env` sets to `pvdials_dev`, unless you set it on the command line. Step 5 reads the records that step 2 saved, so both must use the same database. The other scripts do not use a database.

**Run time.** One figure is recorded: the exhaustive τ run (all 2,116,653 pairs) is noted in the scripts as about 205 minutes. Step 4 is marked "long" in its docstring. No other times are recorded.

### Calibration of τ

Run these first, in this order. They write under `experiments/tau_calibration/outputs/`, which is in `.gitignore`.

1. **`tau_ensemble_timing.py`** measures the cost of Phase 1 over all 2,058 valid model chains for one fixed hardware set-up. It also supplies the set-up that the other calibration scripts reuse.
   - Command: `python experiments/tau_calibration/tau_ensemble_timing.py`
   - Needs: the weather file. No database.
   - Writes: nothing to disk; it prints.
2. **`tau_calibration_convergence.py`** checks whether the τ plateau holds as the number of chains grows (100, 300, 1000, 2058).
   - Command: `python experiments/tau_calibration/tau_calibration_convergence.py`
   - Needs: the weather file. No database.
   - Writes: `outputs/nrmsd_cache/nrmsd_matrix_n*.npy`, `outputs/stability_curve_n*.png` and `outputs/stability_curve_overlay.png`.
3. **`n34_calibration.py`** is the pre-registered calibration run: seeded random samples of 100 and 1000 chains.
   - Command: `python experiments/tau_calibration/n34_calibration.py`
   - Needs: the weather file. No database.
   - Writes: `outputs/n34/n34_stability_curve_n*.png` and `outputs/n34/n34_nrmsd_distribution_n*.png`.
4. **`n34_confirm_seed1.py`** repeats the 1000-chain run with a second seed.
   - Command: `python experiments/tau_calibration/n34_confirm_seed1.py`
   - Needs: the weather file. No database.
   - Writes: `outputs/n34/n34_*_n1000_seed1.png`.
5. **`trivial_plateau_amendment.py`** applies the amended plateau rule to 1000-chain samples (seeds 0 and 1).
   - Command: `python experiments/tau_calibration/trivial_plateau_amendment.py`
   - Needs: the weather file. No database.
   - Writes: `outputs/trivial_plateau_amendment/amended_stability_curve_n1000_seed*.png`.
6. **`trivial_plateau_amendment_exhaustive.py`** applies the amended rule to every pair of the 2,058 chains. Its cache is needed by evaluation step 4 and by the figures.
   - Command: `caffeinate -i python -u experiments/tau_calibration/trivial_plateau_amendment_exhaustive.py` (`caffeinate` keeps a Mac awake; leave it off elsewhere).
   - Needs: the weather file. No database.
   - Writes: `outputs/trivial_plateau_amendment/exhaustive_cache/` (`nrmsd_matrix_n2058_exhaustive.npy`, `min_s_idx_n2058_exhaustive.npy`, `labels_n2058_exhaustive.txt`) and `outputs/trivial_plateau_amendment/amended_stability_curve_n2058_exhaustive.png`.

`tau_calibration.py` is a library used by these scripts. It is not run on its own.

### Evaluation steps

Run these in this order. They write under `experiments/evaluation/outputs/`, which is in `.gitignore`. The names follow the steps in `docs/evaluation-kt.md`. Step 1 of that file is the property tests above.

1. **Step 0, `step0_measure_phase3`** times Phase 3 and counts its runs and provenance records for the pairs A–B and A–C.
   - Command: `python -m experiments.evaluation.step0_measure_phase3`
   - Needs: the weather file; a database other than `pvdials_dev` (set `DATABASE_URL`).
   - Writes: nothing to disk; it prints.
2. **Step 2, `step2_colombo_and_pair`** runs `analysis.yaml` once, checks an independent Shapley calculation against the production values, and builds the v tables for a pair with two differing stages.
   - Command: `python -m experiments.evaluation.step2_colombo_and_pair`
   - Needs: the weather file; a database (see Database above); `analysis.yaml`.
   - Writes: `outputs/step2/colombo/` (`results.json`, `stage_outputs.csv`, `provenance.json`), `outputs/step2/colombo_check.json` and `outputs/step2/two_stage_pair_v_tables.json`. It also saves the run to the database.
3. **Step 3, `step3_perturbation_cases`** runs three constructed cases with mock models, on the weather file.
   - Command: `python -m experiments.evaluation.step3_perturbation_cases`
   - Needs: the weather file; `pytest` (dev extra). No database.
   - Writes: `outputs/step3/perturbation_cases.json`.
4. **Step 4, `step4_ensemble`** takes 100 chains (seed 20260929) and the all-pairs population from the exhaustive cache. It compares Phase 1 with Baseline A and Baseline B, then runs Phase 3 on the eligible ensemble pairs.
   - Command: `caffeinate -i python -u -m experiments.evaluation.step4_ensemble`
   - Needs: the weather file; the exhaustive cache from calibration script 6. No database.
   - Writes to `outputs/step4/`: `chains.json`, `weather_file.json`, `all_pairs_baseline_check.json`, `tau_band_curve.json`, `ensemble_phase1.json`, `phase3_results.jsonl`, `phase3_summary.json` and `phase3_exclusions.json`.
5. **Step 4b, `step4_phase3_rerun_v2`** reruns the Phase 3 pass on the same chains, this time saving the v tables.
   - Command: `caffeinate -i python -u -m experiments.evaluation.step4_phase3_rerun_v2`
   - Needs: the weather file; `outputs/step4/chains.json` and `outputs/step4/ensemble_phase1.json` from step 4. No database.
   - Writes to `outputs/step4/`: `phase3_results_v2.jsonl`, `phase3_summary_v2.json` and `phase3_exclusions_v2.json`.
6. **Step 4c, `verify_v2_unchanged`** checks that the rerun changed none of the earlier values.
   - Command: `python -m experiments.evaluation.verify_v2_unchanged`
   - Needs: the step 4 and 4b files. No weather file, no database.
   - Writes: nothing to disk; it prints.
7. **Step 4d, `single_anchor_analysis`** reads the v tables and compares Phase 3 with the OAT readings of each anchor.
   - Command: `python -m experiments.evaluation.single_anchor_analysis`
   - Needs: `outputs/step4/phase3_results_v2.jsonl`. No weather file, no database.
   - Writes: `outputs/step4/single_anchor_summary.json`.
8. **Step 5, `step5_replay_sample`** samples provenance records saved by step 2, exports them, replays each in a fresh process and compares the stage outputs.
   - Command: `python -m experiments.evaluation.step5_replay_sample`
   - Needs: the weather file; the database that step 2 wrote to.
   - Writes: `outputs/step5/records/` and `outputs/step5/replay_results.json`. It also adds a re-executed record and a discarded attempt to the database.
9. **Step 6, `step6_fill_table`** gathers the saved outputs of steps 2 to 5 into one table. It does not use the database.
   - Command: `python -m experiments.evaluation.step6_fill_table`
   - Needs: the saved outputs of steps 2 to 5 (including `outputs/step4/single_anchor_summary.json`). No weather file, no database.
   - Writes: `outputs/evaluation_results.json` and `outputs/evaluation_table.md`.
10. **Figures, `make_figures`** draws three figures from the saved outputs.
    - Command: `python -m experiments.evaluation.make_figures`
    - Needs: the saved outputs of step 4 and the exhaustive cache. `matplotlib` (dev extra). No weather file, no database.
    - Writes: `outputs/figures/tau_curve.png`, `outputs/figures/gap_histograms.png` and `outputs/figures/k_times_b_heatmap.png`.

The support modules `baselines.py`, `comparators.py`, `chain_population.py`, `weather_source.py`, `wording.py` and `db_safety.py` are imported by these scripts and are not run on their own.
