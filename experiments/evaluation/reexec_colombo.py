"""Every guided re-execution attempt on the Colombo run (analysis.yaml), through the
production O4Session.propose(). Writes provenance to pvdials_test only.

Run from the repository root; the result goes to stdout:
    DATABASE_URL=postgresql://localhost:5432/pvdials_test \
        python experiments/evaluation/reexec_colombo.py > experiments/evaluation/outputs/reexec_colombo.json
"""
import json
import os
import sys
import uuid

assert os.environ["DATABASE_URL"].endswith("/pvdials_test"), "pvdials_test only"

from pvdials import analysis as an
from pvdials.config import load_defaults
from pvdials.guided_reexecution import O4Session, annual_yield_kwh, stage_field
from pvdials.provenance.analyses import save_analysis

cfg = an.parse_analysis_yaml("analysis.yaml")
defaults = load_defaults()
tau = an.resolve_user_tau(None, defaults)
aid = uuid.uuid4().hex
save_analysis(aid, "reexec_check", "started", an.build_inputs_dict(cfg, tau))
load = an.step_load_and_validate(cfg.weather_file)
site = an.step_site_and_offset(load, cfg, defaults, tau)
hw = an.step_hardware(load, site, cfg, defaults)
pl = an.step_run_pipelines(cfg, hw, defaults, aid)
p1 = an.step_disagreement_check(pl, site.ctx, defaults, tau=tau)


def nrmsd(res):
    return {st.name: m.nrmsd for st, m in res.metrics.items()}


rows = []
for (a, b), orig in p1.items():
    if isinstance(orig, str) or orig.k is None:
        rows.append({"pair": f"{a}-{b}", "k": None, "outcome": getattr(orig, "outcome", orig)})
        continue
    before = nrmsd(orig)
    for anchor in (a, b):
        other = b if anchor == a else a
        s = O4Session(
            pair=(a, b), anchor_config=pl.configs[anchor], anchor_result=pl.results[anchor],
            other_config=pl.configs[other], other_result=pl.results[other], stage=orig.k,
            shared_cec=hw.shared_cec, shared_adr=hw.shared_adr, cec_inverters=hw.cec_inverters,
            adr_inverters=hw.adr_inverters, daylight=site.ctx.daylight, defaults=defaults, tau=tau,
        )
        for c in s.alternatives():
            row = {"pair": f"{a}-{b}", "k": orig.k.name, "outcome_before": int(orig.outcome),
                   "anchor": anchor, "anchor_model": getattr(pl.configs[anchor], stage_field(orig.k)),
                   "candidate": c.name, "selectable": c.selectable, "reason": c.reason}
            if c.selectable:
                p = s.propose(c.name)
                after = nrmsd(p.phase1)
                row.update(
                    k_after=p.phase1.k.name if p.phase1.k else None, outcome_after=int(p.phase1.outcome),
                    nrmsd_k_before=before[orig.k.name], nrmsd_k_after=after[orig.k.name],
                    nrmsd_ac_before=before["AC"], nrmsd_ac_after=after["AC"],
                    yield_anchor=pl.annual_yield_kwh[anchor], yield_other=pl.annual_yield_kwh[other],
                    yield_after=annual_yield_kwh(p.result),
                )
            rows.append(row)

json.dump({"tau": tau.value, "yields": pl.annual_yield_kwh, "rows": rows}, sys.stdout, default=str, indent=1)
