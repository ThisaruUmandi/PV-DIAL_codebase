"""Stage 1 adapters: GHI -> DNI, DHI.

Every model is run on the effective (HH:30) times from the SiteContext, so
pvlib's internal date-based terms line up with the irradiance values. The
outputs are relabelled to the canonical HH:00 index (the join key).
Every coefficient comes from run_defaults.yaml; nothing is left to pvlib's
internal defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pvlib

from pvdials.config import load_defaults
from pvdials.physics.registry import get_candidate
from pvdials.physics.site import SiteContext
from pvdials.types import Stage


class AdapterError(Exception):
    """Raised when a model can't be run in this stage slot."""


@dataclass(frozen=True)
class DecompositionResult:
    """outputs: 'dni' and 'dhi' on the canonical index. records: for provenance."""

    outputs: pd.DataFrame
    records: dict


# Where each model's extraterrestrial DNI comes from. Only erbs_driesse and
# orgill_hollands accept it as an input; the rest compute it internally.
ET_SITE = "SiteContext dni_extra"
ET_PVLIB_DEFAULT = "internal: spencer, 1366.1 (pvlib default)"
ET_DISC = "internal: spencer, 1370 (disc formulation)"

ET_SOURCE = {
    "erbs": ET_PVLIB_DEFAULT,
    "erbs_driesse": ET_SITE,
    "disc": ET_DISC,
    "dirint": ET_DISC,  # dirint calls disc internally
    "boland": ET_PVLIB_DEFAULT,
    "louche": ET_PVLIB_DEFAULT,
    "orgill_hollands": ET_SITE,
}

# Models that return DNI only; DHI comes from closure on true zenith (23/09)
CLOSURE_MODELS = {"disc", "dirint"}
CLOSURE_RULE = "closure: GHI - DNI*cos(true zenith)"

_irr = pvlib.irradiance

# Each entry: (inputs, coefficients) -> pvlib output
_MODELS = {
    "erbs": lambda i, c: _irr.erbs(i.ghi, i.zenith, i.times, **c),
    "erbs_driesse": lambda i, c: _irr.erbs_driesse(i.ghi, i.zenith, dni_extra=i.dni_extra, **c),
    "disc": lambda i, c: _irr.disc(i.ghi, i.zenith, i.times, pressure=i.pressure, **c),
    "dirint": lambda i, c: _irr.dirint(i.ghi, i.zenith, i.times, pressure=i.pressure, **c),
    "boland": lambda i, c: _irr.boland(i.ghi, i.zenith, i.times, **c),
    "louche": lambda i, c: _irr.louche(i.ghi, i.zenith, i.times, **c),
    "orgill_hollands": lambda i, c: _irr.orgill_hollands(
        i.ghi, i.zenith, i.times, dni_extra=i.dni_extra, **c
    ),
}


def _check_selectable(model: str) -> None:
    candidate = get_candidate(Stage.DECOMPOSITION, model)
    if candidate is None:
        raise AdapterError(f"'{model}' is not a Stage 1 candidate.")
    if not candidate.selectable:
        raise AdapterError(f"'{model}' can't be selected for Stage 1: {candidate.reason}.")


def decompose(
    model: str,
    weather: pd.DataFrame,
    ctx: SiteContext,
    defaults: dict | None = None,
) -> DecompositionResult:
    """Split GHI into DNI and DHI with one Stage 1 model."""
    _check_selectable(model)
    if not weather.index.equals(ctx.solpos.index):
        raise AdapterError("Weather table and site context must share the same index.")

    defaults = defaults or load_defaults()
    stage1 = defaults["stage1"]
    coefficients = dict(stage1[model])
    clip_min = float(stage1["dhi_clip_min_w_m2"])

    canonical = ctx.solpos.index
    times = pd.DatetimeIndex(ctx.solpos["time_effective"])

    def on_effective(series: pd.Series) -> pd.Series:
        return pd.Series(series.to_numpy(dtype=float), index=times)

    ghi = weather["ghi"].to_numpy(dtype=float)
    zenith = ctx.solpos["zenith"].to_numpy(dtype=float)  # true zenith
    inputs = SimpleNamespace(
        ghi=on_effective(weather["ghi"]),
        zenith=on_effective(ctx.solpos["zenith"]),
        times=times,
        pressure=on_effective(ctx.pressure),
        dni_extra=on_effective(ctx.dni_extra),
    )

    out = _MODELS[model](inputs, coefficients)
    if isinstance(out, pd.Series):  # dirint returns DNI only
        out = out.to_frame("dni")
    dni = np.asarray(out["dni"], dtype=float).copy()

    records: dict = {
        "model": model,
        "coefficients": coefficients,
        "et_dni_source": ET_SOURCE[model],
        "run_on": "time_effective",
    }

    if model == "dirint":
        # dirint returns NaN beyond its guard; the other models return 0 there (23/09)
        beyond_guard = np.isnan(dni) & (zenith >= coefficients["max_zenith"])
        dni[beyond_guard] = 0.0
        records["nan_beyond_guard_set_zero"] = int(beyond_guard.sum())

    if model in CLOSURE_MODELS:
        dhi = ghi - dni * np.cos(np.radians(zenith))
        records["dhi_source"] = CLOSURE_RULE
    else:
        dhi = np.asarray(out["dhi"], dtype=float).copy()
        records["dhi_source"] = "model output"

    # Clip rule for every Stage 1 DHI (23/09): negative diffuse breaks transposition
    below = dhi < clip_min
    records["dhi_clipped_count"] = int(below.sum())
    records["dhi_clipped_min_w_m2"] = float(dhi[below].min()) if below.any() else None
    dhi[below] = clip_min

    outputs = pd.DataFrame({"dni": dni, "dhi": dhi}, index=canonical)
    return DecompositionResult(outputs=outputs, records=records)
