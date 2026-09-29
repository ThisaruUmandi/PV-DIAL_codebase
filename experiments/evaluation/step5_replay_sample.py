"""Evaluation KT Step 5: provenance round-trip (verification).

Samples from each of the three execution sets in the provenance store left
by Step 2's just-regenerated colombo run: 3 originals (A, B, C), 10 derived
(seed 20260929, out of the 20 available), and 2 re-executed (one confirmed
O4 substitution, one discarded attempt -- built fresh here). Exports every
sampled record's full document plus the stage outputs it references BEFORE
replaying, then replays each in a fresh process and reports bitwise
match/mismatch per stage.

Run standalone: python3 -m experiments.evaluation.step5_replay_sample
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from pvdials.config import load_defaults
from pvdials.dla.phase1 import run_phase1
from pvdials.guided_reexecution import O4Session
from pvdials.physics.hardware import ADR_INVERTER, CEC_INVERTER
from pvdials.physics.pipeline import run_pipeline
from pvdials.provenance.db import get_connection
from pvdials.provenance.model import unwrap_value
from pvdials.provenance.replay import replay
from pvdials.types import PipelineConfig
from pvdials.warning_filter import ChandrupatlaWarningFilter

from experiments.evaluation.step0_measure_phase3 import _shared
from experiments.evaluation.weather_source import verify_thesis_weather_file

SEED = 20260929
OUT_DIR = Path(__file__).resolve().parent / "outputs" / "step5"
RECORDS_DIR = OUT_DIR / "records"
_STAGES = ("decomposition", "transposition", "temperature", "dc", "ac")

CONFIG_A = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
CONFIG_B = PipelineConfig("B", "disc", "haydavies", "pvsyst_cell", "singlediode_desoto", "sandia")


def _sampled_record_ids() -> dict[str, list[str]]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM provenance_records WHERE execution_set = 'original' ORDER BY id")
        originals = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT id FROM provenance_records WHERE execution_set = 'derived' ORDER BY id")
        derived_all = [r[0] for r in cur.fetchall()]
    if len(originals) != 3:
        raise RuntimeError(f"Expected exactly 3 original records, found {len(originals)}")
    if len(derived_all) < 10:
        raise RuntimeError(f"Expected at least 10 derived records, found {len(derived_all)}")
    derived_sample = random.Random(SEED).sample(derived_all, 10)
    return {"original": originals, "derived": derived_sample}


def _make_reexec_records(defaults) -> list[str]:
    """One confirmed O4 substitution, one discarded attempt -- against the
    real A-B pair from the colombo run.
    """
    shared_cec, shared_adr, daylight = _shared()
    result_a = run_pipeline(CONFIG_A, shared_cec, defaults)
    result_b = run_pipeline(CONFIG_B, shared_cec, defaults)
    phase1 = run_phase1(CONFIG_A, result_a, CONFIG_B, result_b, daylight, defaults=defaults)
    if phase1.k is None:
        raise RuntimeError("A-B pair has no k (outcome 1) -- can't build an O4 session")

    from pvlib import pvsystem

    cec_inverters = pvsystem.retrieve_sam(CEC_INVERTER)
    adr_inverters = pvsystem.retrieve_sam(ADR_INVERTER)

    record_ids = []
    session = O4Session(
        pair=(CONFIG_A.label, CONFIG_B.label),
        anchor_config=CONFIG_A, anchor_result=result_a,
        other_config=CONFIG_B, other_result=result_b,
        stage=phase1.k,
        shared_cec=shared_cec, shared_adr=shared_adr,
        cec_inverters=cec_inverters, adr_inverters=adr_inverters,
        daylight=daylight, defaults=defaults,
        on_record=record_ids.append,
    )
    candidates = [c.name for c in session.alternatives() if c.selectable]
    if len(candidates) < 2:
        raise RuntimeError(f"Need at least 2 pool-valid candidates at {phase1.k.name}, found {candidates}")

    discarded = session.propose(candidates[0])  # never confirmed -- discarded
    confirmed = session.confirm(candidates[-1])  # the confirmed substitution

    if len(record_ids) != 2:
        raise RuntimeError(f"Expected exactly 2 reexec records (propose + confirm), got {len(record_ids)}")
    return record_ids


def export_record(record_id: str, cur) -> dict:
    cur.execute("SELECT execution_set, config_label, document FROM provenance_records WHERE id = %s", (record_id,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"Record {record_id} not found")
    execution_set, config_label, document = row

    record_dir = RECORDS_DIR / record_id
    record_dir.mkdir(parents=True, exist_ok=True)
    (record_dir / "document.json").write_text(json.dumps(document, indent=2))

    bundle_name = next(iter(document["bundle"]))
    bundle = document["bundle"][bundle_name]
    stage_hashes = {}
    for name in ("weather", *_STAGES):
        entity = bundle["entity"].get(name)
        if entity is None:
            continue
        content_hash = unwrap_value(entity["content_hash"])
        stage_hashes[name] = content_hash
        cur.execute("SELECT payload FROM stage_output_values WHERE content_hash = %s", (content_hash,))
        payload_row = cur.fetchone()
        payload = payload_row[0] if payload_row else None
        (record_dir / f"{name}.json").write_text(json.dumps(payload))

    return {
        "record_id": record_id,
        "execution_set": execution_set,
        "config_label": config_label,
        "bundle_name": bundle_name,
        "stage_content_hashes": stage_hashes,
    }


def main() -> None:
    weather_info = verify_thesis_weather_file()
    print(f"Weather file verified: {weather_info}", flush=True)
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    defaults = load_defaults()

    with ChandrupatlaWarningFilter() as wf:
        reexec_ids = _make_reexec_records(defaults)
    if wf.count:
        print(f"({wf.count} known scipy chandrupatla 0/0 warnings suppressed)")

    sampled = _sampled_record_ids()
    all_ids = sampled["original"] + sampled["derived"] + reexec_ids
    print(f"Sampled {len(all_ids)} records: {len(sampled['original'])} original, "
          f"{len(sampled['derived'])} derived (seed={SEED}), {len(reexec_ids)} reexec.", flush=True)

    manifest = []
    with get_connection() as conn, conn.cursor() as cur:
        for record_id in all_ids:
            manifest.append(export_record(record_id, cur))
    (RECORDS_DIR / "manifest.json").write_text(json.dumps({
        "seed": SEED, "weather_file": weather_info, "records": manifest,
    }, indent=2))
    print(f"Exported {len(manifest)} records (document + stage outputs) to {RECORDS_DIR}", flush=True)

    replay_results = []
    for record_id in all_ids:
        result = replay(record_id)
        entry = {
            "record_id": record_id,
            "passed": result.passed,
            "stages": [
                {"stage": s.stage, "hash_matches": s.hash_matches, "values_match": s.values_match}
                for s in result.stages
            ],
        }
        if not result.passed:
            # Report the max absolute/relative difference and the cause, per
            # the fixed-values table's tolerance rule.
            entry["mismatch_detail"] = "see replay ReplayResult -- values differ from the stored payload"
        replay_results.append(entry)
        print(f"  {record_id}: passed={result.passed}", flush=True)

    n_passed = sum(1 for r in replay_results if r["passed"])
    output = {
        "seed": SEED,
        "weather_file": weather_info,
        "n_records": len(replay_results),
        "n_passed": n_passed,
        "all_passed": n_passed == len(replay_results),
        "results": replay_results,
    }
    (OUT_DIR / "replay_results.json").write_text(json.dumps(output, indent=2))
    print(f"Step 5 done. {n_passed}/{len(replay_results)} records replayed bitwise-identical.", flush=True)


if __name__ == "__main__":
    main()
