"""Fig. 7(c) data: the bandwidth response of the frozen Gemma layout pair.

Gemma-7B, 512-token prefill, the reference configuration of Fig. 5 (36x36
XY mesh, kappa = 2, central digital unit); the best baseline random_s209
and the search layout sa_random_best_s5 frozen, re-priced at mesh
bandwidths 0.2-12.5 GB/s (log-spaced, plus the 0.4 GB/s working point and
the envelope ends). The die ports scale with the mesh at kappa (the
stored dport / kappa term), the hub capacity, K/V and digital compute
resources stay at the reference setting, so H(B) = P + sum over
hand-offs of max(link / B, die port / B, hub / C_hub). Outputs the
communication saving eta, the baseline communication share r0 and the
backbone saving G at every point, with G = eta r0 checked.

    python3 scripts/v7_fig7_bandwidth_response.py
      -> analysis/v7/gemma_bandwidth_response.csv, gemma_bandwidth_response.json
"""
import csv
import json
import os
import sys

import numpy as np

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v7_common as V                      # noqa: E402
from scripts import v6_common as C                      # noqa: E402


def Hf(row):
    return row["H_s"] + row["prop_s"]


def main():
    rec = C.find_record(*V.GEMMA_REF)
    Ch = rec["attention"]["unit"]["link_bandwidth_gbps"] * 1e9
    R = rec["N_s"] + rec["F_s"]
    lib = rec["candidates"]; runs = rec["search"]["runs"]
    base_id, rep_id = rec["strongest"], rec["search"]["headline"]
    assert (base_id, rep_id) == ("random_s209", "sa_random_best_s5"), (base_id, rep_id)
    base, rep = lib[base_id], runs[rep_id]
    # the envelope of the six reference layouts at the reference rate (Fig. 1's set)
    pb = list(csv.DictReader(open(os.path.join(V.V7, "phase_boundary_curves.csv"))))
    setup = json.load(open(os.path.join(V.V7, "phase_setup.json")))
    s_ref = setup["intra_die"]["s_ref_mrows_per_s"]
    row = min(pb, key=lambda r: abs(float(r["s_mrows_per_s"]) - s_ref))
    B_lo, B_hi = float(row["B_minus_seven_rules_gbps"]), float(row["B_plus_seven_rules_gbps"])
    Bs = sorted(set([round(float(b), 6) for b in np.logspace(np.log10(0.2), np.log10(12.5), 61)]
                    + [0.4, round(B_lo, 6), round(B_hi, 6)]))
    out = []
    for B in Bs:
        hb, hs = V.H_of(base, B, Ch), V.H_of(rep, B, Ch)
        eta = 1 - hs / hb; r0 = hb / (R + hb); G = 1 - (R + hs) / (R + hb)
        assert abs(G - eta * r0) < 1e-12
        bb, bs = V.H_binding(base, B, Ch), V.H_binding(rep, B, Ch)
        out.append({"B_mesh_gbps": B, "R_s": R, "H_baseline_s": hb, "H_search_s": hs, "T_baseline_s": R + hb,
                    "T_search_s": R + hs, "eta_comm": eta, "r0": r0, "G": G, "G_check_eta_r0": eta * r0,
                    "baseline_binding_link": bb["link"], "baseline_binding_die_port": bb["die port"],
                    "baseline_binding_hub_port": bb["hub port"], "search_binding_link": bs["link"],
                    "search_binding_die_port": bs["die port"], "search_binding_hub_port": bs["hub port"],
                    "is_B_ref": abs(B - 0.4) < 1e-9, "in_envelope": B_lo - 1e-9 <= B <= B_hi + 1e-9})
    V.write_csv("gemma_bandwidth_response.csv", out)
    V.write_json("gemma_bandwidth_response.json", {
        "config_id": rec["config_id"], "protocol_id": V.protocol_id(rec), "record": V.record_path(V.GEMMA_REF[0]),
        "layout_pair": {"baseline": base_id, "search": rep_id,
                        "H_at_B_ref_s": {"baseline": Hf(base), "search": Hf(rep)}},
        "bandwidth_scaling": "mesh link rate B per direction; die ports at kappa x B (kappa = %s); hub capacity %.1f GB/s, "
                             "K/V and digital compute at the reference setting; layouts and routes frozen; H(B) = "
                             "propagation + sum over hand-offs of max(link words / B, die-port words / (kappa B), "
                             "hub words / C_hub)" % (rec["spec"]["kappa"], Ch / 1e9),
        "B_range_gbps": [Bs[0], Bs[-1]], "n_points": len(Bs), "B_ref_gbps": 0.4,
        "envelope": {"source": "analysis/v7/phase_boundary_curves.csv at s_ref (the six-layout set of Fig. 1(b))",
                     "candidate_set": setup["package"]["candidate_set"]["seven_rules"]["members"],
                     "s_ref_mrows_per_s": s_ref, "B_minus_gbps": B_lo, "B_plus_gbps": B_hi,
                     "rule_at_B_minus": row["B_minus_seven_rules_rule"], "rule_at_B_plus": row["B_plus_seven_rules_rule"]},
        "R_s": R, "code_version": V.code_version()})
    print(f"{len(out)} points, eta {min(r['eta_comm'] for r in out):.4f}-{max(r['eta_comm'] for r in out):.4f}, "
          f"r0 {out[-1]['r0']:.4f}-{out[0]['r0']:.4f}, G {min(r['G'] for r in out):.4f}-{max(r['G'] for r in out):.4f}; "
          f"envelope {B_lo:.4f}-{B_hi:.4f} GB/s")


if __name__ == "__main__":
    main()
