"""Turns outputs/other_locations/summary.json into a SQL file to run once in
pgAdmin (Query Tool). Creates three tables and the views listed at the bottom
of the generated file. Drops/recreates only its own tau_* objects.

    python experiments/tau_calibration/export_other_locations_sql.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).parent / "outputs" / "other_locations"

SITE_NAMES = {"6.944": "Colombo (baseline)", "6.034": "Galle", "7.296": "Kandy", "9.666": "Jaffna"}


def q(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return repr(v)


def main() -> None:
    data = json.loads((OUT_DIR / "summary.json").read_text())
    lines = [
        "DROP VIEW IF EXISTS tau_locations_summary, tau_locations_plateau_table, tau_locations_flagged;",
        "DROP TABLE IF EXISTS tau_location_plateau, tau_location_runs;",
        "",
        "CREATE TABLE tau_location_runs (",
        '    "Site" TEXT, "File" TEXT, "N chains" INT, "Pairs" INT, "NaN pairs" INT,',
        '    "Latitude" DOUBLE PRECISION, "Longitude" DOUBLE PRECISION, "Elevation m" DOUBLE PRECISION,',
        '    "Offset h" DOUBLE PRECISION, "Default tau" DOUBLE PRECISION, "Default width" DOUBLE PRECISION,',
        '    "Default stable fraction" DOUBLE PRECISION,',
        '    "Plateau 0.088-0.098 stable" DOUBLE PRECISION,',
        '    "Outcome-1 share at 0.093" DOUBLE PRECISION, "k=min(S) share at 0.093" DOUBLE PRECISION,',
        '    "nRMSD median" DOUBLE PRECISION, "nRMSD P90" DOUBLE PRECISION,',
        '    "nRMSD P99" DOUBLE PRECISION, "nRMSD max" DOUBLE PRECISION, "Flags" TEXT,',
        '    PRIMARY KEY ("File", "N chains")',
        ");",
        "CREATE TABLE tau_location_plateau (",
        '    "File" TEXT, "N chains" INT, "Width" DOUBLE PRECISION, "Lo" DOUBLE PRECISION,',
        '    "Hi" DOUBLE PRECISION, "Centre" DOUBLE PRECISION, "Stable fraction" DOUBLE PRECISION',
        ");",
        "",
    ]
    for r in data.values():
        lat = f"{r['latitude']:.3f}"
        m = r["max_stage_nrmsd"]
        site = SITE_NAMES.get(lat, lat)
        vals = [
            site, r["file"], r["n_chains"], r["n_pairs"], r["nan_pairs"], r["latitude"], r["longitude"],
            r["elevation"], r["offset_h"], r["amended_default_tau"], r["amended_default_width"],
            r["amended_default_stable_fraction"], r["plateau_stable_fraction"],
            r["share_outcome1_at_0.093"], r["share_k_eq_minS_at_0.093"],
            m["median"], m["p90"], m["p99"], m["max"], "; ".join(r["flags"]) or "ok",
        ]
        lines.append(f"INSERT INTO tau_location_runs VALUES ({', '.join(q(v) for v in vals)});")
        for c in r["plateau_table"]:
            pv = [r["file"], r["n_chains"], c["width"], c["lo"], c["hi"], c["centre"], c["stable_fraction"]]
            lines.append(f"INSERT INTO tau_location_plateau VALUES ({', '.join(q(v) for v in pv)});")

    lines += [
        "",
        'CREATE VIEW tau_locations_summary AS',
        '    SELECT "Site", "N chains", "Default tau", "Default width", "Plateau 0.088-0.098 stable",',
        '           "Outcome-1 share at 0.093", "k=min(S) share at 0.093",',
        '           "nRMSD median", "nRMSD P90", "nRMSD P99", "nRMSD max", "Offset h", "Flags"',
        '    FROM tau_location_runs ORDER BY "N chains", "Latitude";',
        "CREATE VIEW tau_locations_plateau_table AS",
        '    SELECT r."Site", p."N chains", p."Width", p."Lo", p."Hi", p."Centre", p."Stable fraction"',
        '    FROM tau_location_plateau p JOIN tau_location_runs r USING ("File", "N chains")',
        '    ORDER BY p."N chains", r."Latitude", p."Width";',
        "CREATE VIEW tau_locations_flagged AS",
        '    SELECT "Site", "N chains", "Plateau 0.088-0.098 stable", "Default tau", "Flags"',
        '    FROM tau_location_runs WHERE "Flags" <> \'ok\' ORDER BY "N chains", "Latitude";',
    ]
    out = OUT_DIR / "other_locations.sql"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({len(data)} runs)")


if __name__ == "__main__":
    main()
