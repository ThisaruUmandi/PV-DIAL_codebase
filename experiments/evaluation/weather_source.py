"""The one thesis weather file every evaluation script must use (Umee's
decision WF CLOSED, 28/09): data/weather/tmy_6.944_79.856_2005_2020.csv --
the same file tau and the exhaustive cache were built on, copied in from
/Users/umandi/workfolder/Research/Sandbox/pvlib_test1/ (content verified
identical by SHA-256, and by header lat/lon/elevation and row count).

The 2005-2023 file (tmy_6.939_79.854_2005_2023.csv) is a different,
exploratory re-download at slightly different coordinates and years -- kept
in the repo, but never used for a thesis result. Every evaluation script
must call verify_thesis_weather_file() at start-up (fails loudly on any
mismatch) and include its return value in its own output JSON.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THESIS_WEATHER_FILE = REPO_ROOT / "data" / "weather" / "tmy_6.944_79.856_2005_2020.csv"
EXPECTED_SHA256 = "9828d22b6291d0f84d5c6d87331a5487109e3dd436e39f9809eaae03d408ebeb"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_thesis_weather_file() -> dict:
    """Raises if the thesis weather file is missing or its content has
    changed. Returns a small dict to be written into every evaluation
    script's own output JSON, so the exact file used is always on record.
    """
    if not THESIS_WEATHER_FILE.exists():
        raise FileNotFoundError(f"Thesis weather file not found: {THESIS_WEATHER_FILE}")
    actual = _sha256(THESIS_WEATHER_FILE)
    if actual != EXPECTED_SHA256:
        raise ValueError(
            f"Thesis weather file content has changed!\n"
            f"  path: {THESIS_WEATHER_FILE}\n"
            f"  expected sha256: {EXPECTED_SHA256}\n"
            f"  actual sha256:   {actual}"
        )
    return {"weather_file": str(THESIS_WEATHER_FILE.relative_to(REPO_ROOT)), "sha256": actual}


if __name__ == "__main__":
    print(verify_thesis_weather_file())
