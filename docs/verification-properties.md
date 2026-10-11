# PV-DIAL — Testable properties (verification list)

_Source: section 9 of my **KT File for Evaluation Planning** (22/09/2026), the document my
supervisor read when he wrote the Evaluation Guide. He refers to "24 properties"; the table in
that KT has 26 rows. Use all 26._

_Each property is a direct consequence of a logged decision or definition. **Any violation is a
defect.**_

| # | Property | Source (decision) |
|---|---|---|
| 1 | nRMSD(A,B) = nRMSD(B,A) and RMSD(A,B) = RMSD(B,A) | Symmetry requirement, 08/08/2026; pooled denominator, 13/09/2026 |
| 2 | Relabelling pipelines A, B, C does not change the set of pairwise results | Pairwise symmetric design; no pipeline is a reference |
| 3 | Disagreement between a pipeline and itself is zero at every stage | Definition of RMSD |
| 4 | Upstream of the first stage where a pair's models differ, stage outputs are identical, so first emergence can never be earlier than the first differing stage | DLA audit finding, 13/09/2026 |
| 5 | First emergence can be later than the first differing stage when an earlier difference stays below τ | τ defence, 13/09/2026 |
| 6 | Stage 3 nRMSD is identical whether temperature is in °C or K | Offset-invariance of P95 − P5, 13/09/2026 |
| 7 | Σφ = v(S) for every pair | Shapley efficiency, 08/08/2026 |
| 8 | A stage not in S has null φ; a pair with \|S\| = 1 gives 100 % to that stage | DLA specification, 13/09/2026; 08/08/2026 |
| 9 | The derived space has exactly 2^\|S\| members with the correct model at every stage | O1 v1.1 derivation rule |
| 10 | Pairs with outcome 1 run no derived configurations and have no O4 track | Ordering correction, 13/09/2026 |
| 11 | Outcome 3 appears only when some upstream stage exceeds τ and stage 5 does not | N12, 13/09/2026 |
| 12 | Same inputs and settings give identical outputs on repeated runs | DLA determinism, 13/09/2026; NFR1, NFR4 |
| 13 | Re-execution from the provenance record alone reproduces stage outputs | O2 |
| 14 | Solar position is computed once and every configuration receives the same table | D6; NFR5 |
| 15 | The daylight mask is identical for every configuration | D1, 08/08/2026 |
| 16 | A file missing any required field is rejected with the missing fields named | 22/09/2026 |
| 17 | IAM/spectral treatment always matches the DC model mapping | N16, 13/09/2026 |
| 18 | No comparison ever contains both SAPM and single-diode | Hardware decision, 21/09/2026 |
| 19 | After any number of retries, the O4 configuration differs from its anchor at exactly one stage | R4.7, 13/09/2026 |
| 20 | A′ from one track never appears in another track | Track sealing, 13/09/2026 |
| 21 | No code path offers chained substitution | R4.7, 13/09/2026 |
| 22 | Alternatives render in pool order; no sort key by disagreement exists | 08/08 and 13/09/2026 |
| 23 | No banned word appears in any interface string or report template | 06/07/2026 language constraint |
| 24 | Every field listed in the DLA specification is present in the DLA output object | DLA specification: "a field absent from the output cannot be displayed" |
| 25 | τ is constant within a run and recorded with its origin in every provenance record | 21/09/2026 |
| 26 | The three execution sets appear in separate provenance bundles | D5 and 13/09/2026 |

## Notes for checking (from what has happened since 22/09)

- **#8:** the code reports 0.0 for a stage where both pipelines use the same model, and the CLI
  prints "same model — no difference". The property says *null*, not zero. Report how it is
  represented in the output object; do not change it — I decide.
- **#13:** Step 5 of the evaluation KT does the full round-trip. Here, point to the existing
  replay test.
- **#22, #23:** the Streamlit interface does not exist yet. Check what exists now (registry
  reason strings, CLI output, report module); the interface part is checked after it is built.
- **#25:** τ-in-provenance was an open item (N35) when last recorded. If it is not there, report
  it as a failed property; do not add it without a plan I approve.
  **29/09 update: fixed, approved plan built.** τ was absent from `provenance/model.py`/
  `recorder.py` (confirmed by direct read: `tau` appeared nowhere in either file). Fix:
  `physics/site.py::build_site_context()` now takes optional `tau`/`tau_source`, resolved once
  in `run_analysis()` via the existing `resolve_tau()` (unchanged elsewhere — Phase 1's own
  per-pair calls still happen exactly as before) and threaded through `step_site_and_offset()`.
  `tau_value`/`tau_source` ride into every provenance record automatically via the existing
  generic `ctx.settings` → `site_context` entity copy in `build_document()` — no changes to
  `model.py`, `recorder.py`, `dla/phase1.py`, `dla/phase3.py`, or `guided_reexecution.py`.
  Verified on a real run: every ORIGINAL/DERIVED record's `site_context.tau_value` matches the
  tau that pair's own Phase 1 result used, and all records within one analysis share the same
  value, at both the live default and an overridden τ. Phase 3 φ/v-tables and the replay test are
  confirmed unchanged (reran both suites). Record-hash consequence: every new provenance
  record's content-hash id changes going forward (site_context's serialized content is now
  different); existing pre-fix rows are not backfilled and permanently lack τ.
- **#18:** check against the current hardware/pool rules and say how it is guaranteed.
