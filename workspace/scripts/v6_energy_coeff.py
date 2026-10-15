"""Follow-up P2 (section 9.3): the digital compute energy coefficient
(1 pJ per counted op, the subsystem-equivalent figure) re-priced at
0.25 / 0.5 / 1 / 2 / 4 x on the stored layouts of the selected records:
the dynamic energy by component, its change, and the communication share.
No new evaluation: E(k) = E(1) + (k - 1) x L x E_unit_compute(1) per layout.

    python3 scripts/v6_energy_coeff.py  -> analysis/v6/energy_coefficient_sweep.csv
"""
import csv
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v6_common as C                       # noqa: E402

FACTORS = (0.25, 0.5, 1.0, 2.0, 4.0)
TARGETS = [("e9_confirm", "opt6.7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"), ("e9_confirm", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"),
           ("e9_confirm", "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"), ("e9_confirm", "gemma7b_decode512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"),
           ("e9_head", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK4TH"), ("e9_hub", "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK4"),
           ("e9_hub", "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcornerK1"), ("e9_hub", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcornerK1")]


def main():
    rows = []
    for unit, cid in TARGETS:
        try:
            rec = C.find_record(unit, cid)
        except KeyError:
            print("missing", unit, cid); continue
        W = C.workload_from_record(rec); phase = rec["spec"]["phase"]; L = W.cfg.n_layers
        u = W.unit_terms(phase)
        unit_J = u["compute_J"] * L; kv_J = u["kv_J"] * L
        layouts = {"strongest": (rec["strongest"], rec["candidates"][rec["strongest"]]), "representative": (rec["search"]["headline"], rec["search"]["runs"][rec["search"]["headline"]]),
                   "default": ("sequential", rec["candidates"].get("sequential"))}
        for role, (name, row) in layouts.items():
            if row is None:
                continue
            E1 = row["E_J"]; Ecomm = row["E_comm_J"]
            cim_dig = E1 - unit_J - kv_J - Ecomm
            for k in FACTORS:
                Ek = E1 + (k - 1) * unit_J
                rows.append({"unit": unit, "config_id": cid, "layout_role": role, "layout": name, "factor": k, "pj_per_op": k * 1.0, "E_total_J": Ek, "E_cim_plus_digital_J": cim_dig, "E_unit_compute_J": unit_J * k,
                             "E_kv_J": kv_J, "E_interconnect_J": Ecomm, "E_comm_share": Ecomm / Ek, "E_unit_share": unit_J * k / Ek, "dE_vs_factor1": Ek / E1 - 1,
                             "coefficient_scope": "digital compute subsystem equivalent (unit MACs and softmax ops); CIM, K/V and interconnect unchanged"})
        base = {k: [r for r in rows if r["config_id"] == cid and r["factor"] == k] for k in FACTORS}
        for k in FACTORS:
            s = [r for r in base[k] if r["layout_role"] == "strongest"][0]; p = [r for r in base[k] if r["layout_role"] == "representative"][0]
            rows.append({"unit": unit, "config_id": cid, "layout_role": "representative vs strongest", "layout": f"{p['layout']} vs {s['layout']}", "factor": k, "pj_per_op": k, "E_total_J": p["E_total_J"] - s["E_total_J"],
                         "E_cim_plus_digital_J": "", "E_unit_compute_J": "", "E_kv_J": "", "E_interconnect_J": p["E_interconnect_J"] - s["E_interconnect_J"], "E_comm_share": "", "E_unit_share": "",
                         "dE_vs_factor1": p["E_total_J"] / s["E_total_J"] - 1, "coefficient_scope": "difference; dE_vs_factor1 here = selected layout's energy relative to the strongest fill at this factor"})
    with open(os.path.join(C.V6, "energy_coefficient_sweep.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    for r in rows:
        if r["layout_role"] == "representative vs strongest" and r["factor"] in (0.25, 1.0, 4.0):
            print(f"{r['config_id'][:52]:52s} x{r['factor']:<4g} selected vs strongest dE {r['dE_vs_factor1']*100:+.2f}%")
    for r in rows:
        if r["layout_role"] == "strongest" and r["factor"] == 1.0:
            print(f"{r['config_id'][:52]:52s} comm share {r['E_comm_share']*100:.1f}% unit share {r['E_unit_share']*100:.1f}% (x1); unit share at x4 {[x for x in rows if x['config_id']==r['config_id'] and x['layout_role']=='strongest' and x['factor']==4.0][0]['E_unit_share']*100:.1f}%")
    print("->", C.V6)


if __name__ == "__main__":
    main()
