# KT — PV-DIAL evaluation (A18)

_For Claude Code. 29/09/2026. Follows my supervisor's **PV-DIAL Evaluation Guide** (22/09/2026).
Branch: `feature-evaluation`._

**How we work:** for each step, plan first; no code until I approve the plan; then build that
step only. I review each step before the next. I commit myself. If anything here conflicts with
the code as it is, tell me before planning around it.

---

## 1. The idea

PV-DIAL has no correct output to compare against. Comparing a pipeline's output with measured or
reference output stays closed. What the evaluation does instead:

> **Compare PV-DIAL's diagnostic method with a simpler method that answers the same question, on
> the same runs.**

If the simpler method always gives the same answer, the algorithm added nothing. That is a
possible result and must be reported honestly. Nothing is tuned after seeing results.

Test for any evidence: *could it come out the same whether or not the method was worth building?*
If yes, it is **verification** (kept in full, Step 1), not **evaluation**.

Four layers, kept apart:

| Layer | Question | Evidence |
|---|---|---|
| Demonstration | Does it run at all? | The runs already done |
| Verification | Did I build what I specified? | The 24 properties, unit tests, provenance round-trip |
| **Evaluation** | Does the method do better than a simpler method on the same question? | The table below |
| Validation | What can these results not tell us? | Written by me, not code |

### The evaluation table

| Claim | Comparator | Metric | Data | What failure looks like |
|---|---|---|---|---|
| **Phase 1: WHERE** disagreement first becomes material | **Baseline A**: the first stage where the two pipelines use different models, min(S). Read off the configuration, no computation | **Informative rate**: share of pairs where Phase 1 says something different from Baseline A (k later than min(S), or outcome 1). Reported across the stable τ band | The ensemble, Phase 1 only (see section 3). Plus constructed cases | At the default τ, Phase 1 agrees with Baseline A on nearly every pair. Then the algorithm is a slow way of reading the configuration |
| **Phase 1: second check** | **Baseline B**: the stage with the largest single-step rise in nRMSD (the rejected "localizing by the largest increase" rule), no threshold | Agreement rate between k and Baseline B's stage; cases where they differ, listed and explained | Same runs | If A, B and Phase 1 always agree, τ is doing no work |
| **Phase 3: HOW MUCH** each stage contributed | **One-at-a-time substitution (OAT)**: change one stage from the anchor and measure the AC change, v({i}); also v(S) − v(S∖{i}) (what i adds last). Both are already inside the derived space | **Attribution gap**: \|Σ v({i}) − v(S)\| ÷ v(S). **Rank agreement**: does the largest Shapley share name the same stage as the largest single change? | Every pair with \|S\| ≥ 2 in the ensemble. Plus hand-built v tables | Gap near zero and ranks always agree. Then Shapley adds cost without changing the answer at this site (an honest, reportable finding) |
| **Provenance (O2)** | Not comparative: verification | Re-execution from the record alone reproduces every stage output, bitwise or within the documented tolerance | A sample of runs from each of the three execution sets | Any stage output that cannot be reproduced from the record |

Comparator code lives in `experiments/evaluation/` only. Nothing in `src/pvdials/` imports it, and
it is never shown to the user as a PV-DIAL result.

---

## 2. Definitions (use these exactly)

- **Stages:** 1 DECOMPOSITION, 2 TRANSPOSITION, 3 TEMPERATURE, 4 DC, 5 AC.
- **Pair (X, Y):** two configurations. **S** = stages where they use different models; **min(S)**
  = the first of them.
- **nRMSD(s)** = RMSD ÷ (P95 − P5 pooled over both pipelines), daylight rows; Stage 1 = DNI‖DHI
  concatenated. As in `dla/metrics.py`.
- **τ** default **0.093**. **Outcome** 1 = no stage over τ; 2 = some stage over τ and AC over τ;
  3 = some stage over τ, AC not. **k** = first stage over τ. Use outcome **numbers**, not their
  text labels (the outcome-3 label may be renamed).
- **Phase 3** runs only for outcome 2 or 3 pairs (the product's gating; keep it).

**Baseline A:** answer = min(S). Phase 1 differs from it when outcome 1 **or** k > min(S). Assert
k < min(S) never happens. Report the informative rate and its two parts: (a) outcome 1;
(b) k > min(S).

**Baseline B:** with nRMSD(0) = 0, rise(s) = nRMSD(s) − nRMSD(s−1); B = stage with the largest
rise; ties → earliest. Agreement = B == k over pairs where k exists; outcome-1 pairs reported
separately. Also report the share where Phase 1, A and B all name the same stage.

**OAT and Shapley — one detail from my decisions (25/09):** the product's φ_final is the signed
average of the two directions (anchor X and anchor Y), i.e. the Shapley value of the averaged game
w(T) = (v_XY(T) + v_YX(T)) ÷ 2, where v_XY(T) = RMSD(config with Y's models on T and X's elsewhere,
X) at AC, daylight rows, and w(S) = RMSD(X, Y). So that the comparison is fair, read OAT from the
same averaged game: singleton w({i}), leave-one-out w(S) − w(S∖{i}). **Also report the
single-anchor readings** v_XY({i}) and v_YX({i}) beside them (the supervisor's "change one stage
from the anchor"). Confirm the averaged game matches `dla/phase3.py`; if not, stop and tell me.

**Metrics:**
- Attribution gap per pair (singleton and LOO versions); report the distribution.
- Rank agreement for **|S| ≥ 2**: share where the largest φ_final names the same stage as the
  largest singleton (and, separately, the largest LOO). **List every pair where they do not
  agree.** Ties within 1e-9 relative reported as ties. |S| = 1 excluded (trivially 100 %); count
  them. Also show the |S| = 2 and |S| ≥ 3 split: for |S| = 2 the ranks must agree, since
  φ₁ − φ₂ = w({1}) − w({2}) exactly.

---

## 3. Fixed values (pre-registered in my decisions file; do not change without asking)

| Item | Value |
|---|---|
| Default τ | 0.093 |
| Stable τ band | every grid point of `linspace(0,1,501)` in [0.088, 0.098]; plus the curve over the whole grid for context |
| **The ensemble** | 100 chains drawn at random without replacement from the 2,058 valid chains, **seed 20260929**; all C(100,2) = 4,950 pairs. Write the chain list to a file before computing anything |
| Phase 1 comparators | on the ensemble (the table's data) **and** on all 2,116,653 pairs from the saved cache (my 25/09 decision: exhaustive, so exact) |
| Phase 3 / OAT pairs | ensemble pairs with outcome 2 or 3 at τ = 0.093, \|S\| ≥ 2, and every hybrid in the 2^\|S\| space pool-valid; count the excluded ones by reason; no replacement |
| Worked examples | Colombo pairs A–B and A–C, reported separately |
| Efficiency tolerance ε | \|Σφ − w(S)\| ≤ 1e-9 × w(S) (absolute 1e-12 if w(S) = 0) |
| Provenance tolerance | bitwise identical expected; otherwise report max absolute/relative difference and the cause; fail if any relative difference > 1e-9 |
| Intervals | ensemble results: Wilson 95 %; all-pairs results are exact, no intervals |

---

## 4. Steps — in the supervisor's order

### Step 0 — Make Phase 3 fast enough for the ensemble (production code; results must not change)
A full Colombo run takes 2–3 minutes because Phase 3 runs, while one pipeline run is ~0.08 s.
Measure per pair: hybrid runs, unique configurations, time in physics vs provenance writes vs
nRMSD. Check for repeated runs (stages where both use the same model; the Y→X space is the same set
of configurations as the X→Y space). Propose running each unique configuration once. **Results
must be bitwise identical before and after** (φ, v tables, efficiency; Colombo pairs + one
constructed pair). Estimate the time for Phase 3 on all eligible ensemble pairs, with and without
provenance writes (the ensemble run in `experiments/` may skip provenance writes; say how). If over
12 hours even without them, stop and tell me.

Also: suppress **only** the known scipy `_chandrupatla.py:437` RuntimeWarning (0/0 at zero
irradiance), counted and summarised in one line at the end of CLI output; other warnings still
show; test that an unrelated RuntimeWarning is not suppressed.

### Step 1 — Verification: the 24 properties as unit tests
From `docs/verification-properties.md` (section 9 of my Evaluation Planning KT, 22/09; the
supervisor calls them "the 24 properties"; the table has 26 rows, so use all 26): a table of each
property → the test(s) covering it → pass/fail.
Flag any property with no test and propose one. If any of these are not among the 24, add them to
the table too: symmetry nRMSD(X,Y) = nRMSD(Y,X); nRMSD(X,X) = 0; Shapley efficiency within ε;
exactly 2^|S| derived configurations with correct membership; °C/K invariance of Stage 3 nRMSD;
same inputs twice → identical outputs; a stage where both use the same model gets φ = 0.

### Step 2 — Hand-built v tables (unit level, no pvlib)
Pure functions in `experiments/evaluation/comparators.py`: Shapley from a v table, averaged game,
singleton and LOO readings, gap, rank agreement with ties. Tests in `tests/evaluation/`:

| Table | v | Expected (worked on paper) |
|---|---|---|
| Additive | v({1,2}) = v({1}) + v({2}), e.g. v({1}) = 3, v({2}) = 1, v({1,2}) = 4 | φ = singletons = (3, 1); gap 0; identical ranks |
| Interactive (the supervisor's example: stage 2 alone does nothing but doubles the effect of stage 1) | v({1}) = 4, v({2}) = 0, v({1,2}) = 8 | φ = (6, 2); singleton sum 4, gap 0.5; ranks agree |

Also run the functions on the Colombo A–B and A–C v tables from `results.json`: φ must match the
production φ_final within ε.

Also, for my supervisor's question: pick one real pair from the pool that differs at **exactly two
stages** (the first such pair in label order; state it). Run it and give me only v({i}), v({j}),
v({i,j}) for both directions and the averaged game. Do not give me the Shapley values: I compute
them by hand first, then you check my arithmetic.

### Step 3 — Perturbation wrappers (pipeline level)
Test doubles wrapping a pvlib model and returning its output × (1 + ε). Used only inside tests,
never in the user's pool; they add no physics, only a known perturbation. Use the existing ones
(`tests/dla/mock_adapters.py`) on the real Colombo file; several cases already exist as tests, so
map them and add the missing ones in `tests/evaluation/`. Record Baseline A and B beside Phase 1
for each case.

| Case | Construction | Must produce |
|---|---|---|
| Phase 1 case | share stage 1; small perturbation at stage 2 sized so its nRMSD is **below** τ; large perturbation at stage 4 sized **above** τ | k = 4 by construction, while Baseline A says 2 (exists: `test_sub_tau_upstream_delta_plus_supra_tau_later_delta_gives_k_at_the_later_stage`) |
| One perturbed stage | a perturbation at one stage only | 100 % of φ to that stage |
| Two multiplicative perturbations | stage 2 output × (1 + a) and AC output × (1 + c), e.g. a = 0.30, c = 0.10 | **Expected values computed on paper before running** (R = RMS of the anchor AC over daylight; assuming AC scales linearly with POA): v({2}) ≈ aR, v({5}) = cR, v({2,5}) ≈ (a + c + ac)R, φ₂ ≈ (a + ac/2)R, φ₅ ≈ (c + ac/2)R. The code's φ must equal the Shapley formula applied to the measured v table within ε; measured vs paper values reported, differences with their cause |

State every perturbation value in the plan before running. Do not adjust values afterwards to make
a case pass; if the code disagrees with the paper calculation, report it. If a constructed pair
does not reach outcome 2 or 3, say so and call Phase 3 directly for the Phase 3 checks.

### Step 4 — The ensemble: Phase 1 vs Baselines A and B; Phase 3 vs OAT
Draw the ensemble (section 3) and save the chain list first.

**Phase 1** (no new pipeline runs for all-pairs: use
`experiments/tau_calibration/outputs/trivial_plateau_amendment/exhaustive_cache/`). Note: the
all-pairs Baseline A figures already exist from the τ work (k = min(S) 45.83 %, outcome 1 30.27 %
at τ = 0.093); re-derive them; they must match exactly, or stop and report. Baseline B is new.
For the ensemble and for all pairs, at τ = 0.093 and at each τ in the band:
- informative rate with parts (a) and (b); curve over the whole τ grid with the band shaded;
- Baseline B agreement; the k × B table; share where Phase 1, A and B all agree;
- **ensemble: every pair where k and B differ, listed** (pair, models per stage, nRMSD profile,
  k, B, min(S)); all pairs: each off-diagonal k × B cell with its count, the common model pairs and
  3 examples. I write the explanations; you supply the data and, if you see one, a candidate
  mechanism, labelled as a candidate.

**Phase 3** on every eligible ensemble pair, through the **production** code path; then the Step 2
functions:
- counts: ensemble, excluded by reason, eligible; |S| distribution;
- singleton and LOO gap: median, P10, P90, max; histogram;
- rank agreement for |S| ≥ 2 (and the 2 / ≥3 split) with Wilson intervals; **every disagreeing
  pair listed** with φ, singleton and LOO values;
- single-anchor readings beside the averaged ones;
- also (descriptive): share of pairs with any φ_final < −ε (the supervisor: Shapley sees
  interaction through negative values; one-at-a-time cannot);
- the Colombo A–B and A–C worked examples, separately.
Save every pair's v tables.

### Step 5 — Provenance round-trip (verification)
From the record alone, in a fresh process (new interpreter, record read from the database or disk,
no in-memory objects), re-execute and compare every stage output for a sample from each execution
set: originals (A, B, C of a Colombo run); derived (10 hybrids from its Phase 3, seed 20260929);
re-executed (one confirmed O4 substitution and one discarded retry). Report per run: stages
compared, bitwise yes/no, max differences if not.

### Step 6 — The evaluation table, filled
`experiments/evaluation/outputs/`: `evaluation_results.json` (every number, with the fixed values
and seeds echoed), the figures, and a markdown copy of the section 1 table with each row's numbers
placed next to its "what failure looks like" condition. **Do not write the verdict**; I write it.

---

## 5. Rules for all steps
- Code in `experiments/evaluation/` and `tests/evaluation/` only, except Step 0's production
  change. Nothing in `src/pvdials/` imports evaluation code.
- Do not change τ, `run_defaults.yaml`, Phase 1/2/3 logic, or any fixed value. If a result suggests
  one of them is wrong, stop and report.
- Neutral wording in outputs: "differs from", "agrees with", "higher", "lower". Never
  "better/worse", "accuracy", "error", "correct", "best", "optimal", "improve", "recommend",
  "suggest".
- Long runs: `caffeinate -i python3 -u …`, `flush=True` progress lines, log file, intermediate
  saves so a crash resumes without recomputing.
- Seeds as stated, written into the output JSON.
- Full test suite and guards green at the end of every step.

## 6. What I want back first
The plan for **Step 0** only, plus anything in this KT that conflicts with the code.
