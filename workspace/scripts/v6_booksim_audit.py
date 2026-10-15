"""Follow-up P0 (section 5.1): the offloaded BookSim libraries re-audited
for ties and the actual selection rule.

    python3 scripts/v6_booksim_audit.py  -> analysis/v6/booksim_selection_audit.csv, booksim_tie_sets.csv, validation_protocols.json
"""
import csv
import glob
import json
import os
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v3_discrim as d3                 # noqa: E402
from scripts import booksim_bridge as bb             # noqa: E402

V6 = os.path.join(WS, "analysis", "v6")
LIBS = sorted(glob.glob(os.path.join(WS, "analysis", "v3", "e3_offload", "library_*.json"))) + sorted(glob.glob(os.path.join(WS, "analysis", "v3", "e3_k2", "library_*.json")))


def tie_set(c, names, key, tol):
    vals = {n: c[n][key] for n in names}
    best = min(vals.values())
    if tol == "exact":
        return [n for n in names if vals[n] == best]
    if tol == "float":
        return [n for n in names if abs(vals[n] - best) <= 1e-9 * max(1.0, abs(best))]
    return [n for n in names if round(vals[n], 6) == round(best, 6)]


def main():
    os.makedirs(V6, exist_ok=True)
    audit, ties = [], []
    for p in LIBS:
        lib = json.load(open(p)); scen = lib["scenario"]; src = os.path.relpath(p, WS)
        c = lib["candidates"]; names = sorted(c)
        bs_names = [n for n in names if c[n].get("booksim_cycles")]
        if not bs_names:
            continue
        ref = {n: c[n]["booksim_cycles"] for n in bs_names}; best_ref = min(ref.values())
        for key in ("A_full", "A_links", "word_hops", "max_hops", "mean_hops"):
            vals = [c[n][key] for n in bs_names]
            rho = d3.spearman(vals, [ref[n] for n in bs_names]) if len(set(vals)) > 1 else None
            for tol in ("exact", "float", "rounded6"):
                ts = tie_set(c, bs_names, key, tol)
                regs = sorted(ref[n] / best_ref - 1 for n in ts)
                pick_stable = sorted(ts)[0]                       # the declared deployable rule: lowest score, then the stable candidate id
                pick_first = ts[0]                                 # first in library order
                ties.append({"library": scen, "source": src, "objective": key, "tie_definition": tol, "min_score": min(c[n][key] for n in bs_names), "tie_set_size": len(ts),
                             "tie_members": ";".join(ts), "regret_min": regs[0], "regret_median": statistics.median(regs), "regret_max": regs[-1],
                             "selected_by_stable_id": pick_stable, "regret_selected_stable_id": ref[pick_stable] / best_ref - 1, "selected_first_in_library": pick_first, "regret_selected_first": ref[pick_first] / best_ref - 1})
            ts = tie_set(c, bs_names, key, "exact")
            sa = [n for n in bs_names if n.startswith(f"sa_{key.replace('A_full', 'full').replace('A_links', 'links_only')}")]
            audit.append({"library": scen, "source": src, "objective": key, "n_candidates": len(names), "n_with_booksim": len(bs_names), "spearman_vs_booksim": rho,
                          "inversions_vs_booksim": d3.inversions(vals, [ref[n] for n in bs_names]) if len(set(vals)) > 1 else None,
                          "selection_regret_stable_id": ref[sorted(ts)[0]] / best_ref - 1, "tie_set_size_exact": len(ts),
                          "search_endpoints": ";".join(sa), "search_endpoint_regret_min": (min(ref[n] / best_ref - 1 for n in sa) if sa else ""), "search_endpoint_regret_max": (max(ref[n] / best_ref - 1 for n in sa) if sa else ""),
                          "booksim_over_bound_min": min(c[n]["booksim_over_bound"] for n in bs_names), "booksim_over_bound_median": statistics.median(c[n]["booksim_over_bound"] for n in bs_names), "booksim_over_bound_max": max(c[n]["booksim_over_bound"] for n in bs_names),
                          "analytic_kappa": lib.get("kappa"), "booksim_c": lib.get("kappa_booksim"), "offload": "offload" in scen})
    with open(os.path.join(V6, "booksim_selection_audit.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(audit[0].keys())); w.writeheader(); w.writerows(audit)
    with open(os.path.join(V6, "booksim_tie_sets.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ties[0].keys())); w.writeheader(); w.writerows(ties)
    proto = {"booksim": {"topology": "cmesh (concentrated mesh) for kappa 4 / c = 4; mesh for kappa 1", "k": "grid side", "n": 2, "c": 4, "xr_yr": 2,
                         "routing": "dor_no_express (cmesh) / dor (mesh)", "allocators": "wavefront sw and vc for cmesh (iSLIP starves shared outputs); default for mesh",
                         "packet": f"{bb.PACKET_FLITS} flits = {bb.PACKET_PAYLOAD_B:.0f} B payload ({bb.FLIT_PAYLOAD_B:.0f} B per flit)", "vc_buf_size": 34,
                         "hop_latency": f"{bb.HOP_CHANNEL_CYCLES} channel cycles (vendored patch 0002) + {bb.HOP_ROUTER_CYCLES} router cycles = {bb.HOP_CHANNEL_CYCLES + bb.HOP_ROUTER_CYCLES} per hop",
                         "injection": "batch mode, bernoulli at rate 1.0 (every packet offered at cycle 0)", "timing": "Overall min batch duration (cycles) per hand-off, summed over the hand-offs (serial semantics)",
                         "volume_scale": "layer instances 0.01 of the words, decode instances 1.0", "effective_port_capacity": "c = 4 terminal channels per node = kappa 4 x link; a unit node has the same 4 terminals (its interface = 4 mesh links in the offload libraries)",
                         "bound": "max over direction-keyed channel loads, injection and ejection loads in flit cycles; booksim_over_bound = batch duration / bound"},
             "analytic": {"kappa": 4, "offload_unit_interface": "4 x B_mesh (so that BookSim's terminals express it)", "objective_A_full": "sum over hand-offs of the busiest resource in words (links, die ports, unit ports)"},
             "selection_rule": "lowest analytic score; exact ties broken by the stable candidate id (sorted name, first); the rule uses deployment-time information only",
             "tie_definitions": {"exact": "equal floats", "float": "within 1e-9 relative", "rounded6": "equal after rounding to 6 decimals (export rounding)"},
             "kappa_2_vs_4": "the kappa 4 analytic objective is the like-for-like comparison with the c = 4 simulation; kappa 2 is the main system's objective and is compared as a resource-bound check (analysis/v4/e3_align)"}
    json.dump(proto, open(os.path.join(V6, "validation_protocols.json"), "w"), indent=1)
    for a in audit:
        if a["objective"] in ("A_full", "word_hops"):
            print(f"{a['library']:18s} {a['objective']:9s} n {a['n_with_booksim']} rho {a['spearman_vs_booksim']:.3f} regret(stable id) {a['selection_regret_stable_id']*100:.1f}% ties {a['tie_set_size_exact']} endpoints {a['search_endpoint_regret_min'] if a['search_endpoint_regret_min']=='' else round(a['search_endpoint_regret_min']*100,1)}-{a['search_endpoint_regret_max'] if a['search_endpoint_regret_max']=='' else round(a['search_endpoint_regret_max']*100,1)}%")
    print("->", V6)


if __name__ == "__main__":
    main()
