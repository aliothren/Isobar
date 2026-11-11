"""Fig. 3 and Fig. 4 data. Fig. 3(a): the silicon seating reference (Simba,
one layer on four chiplets at five separations) with the model's resource
bound and protocol estimate. Fig. 3(b) and Fig. 4: the BookSim candidate
libraries (three offload pools: one-layer prefill, one-layer decode,
two-layer prefill; one on-chip pool for the equal-word-hops example), every
candidate's analytic score, word-hops and BookSim completion time against
the library's default fill, the exact word-hops equivalence groups, and the
mapping each metric selects from each pool (lowest score, exact ties broken
by the sorted candidate id) with its BookSim regret. Fig. 3(c) reads the
timing exports of run_timing.py, Fig. 3(d) those of
run_search_trajectories.py.

    python3 scripts/export_fig3_fig4.py
      -> results/exports/silicon_reference.csv, booksim_candidate_costs.csv, booksim_library_summary.csv,
         equivalent_candidate_groups.csv, booksim_selection_by_objective.csv, validation_protocols.json
"""
import json
import os
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import booksim_bridge as bb                # noqa: E402
from scripts import export_common as V                  # noqa: E402
from scripts import paths                               # noqa: E402
from scripts import run_booksim_libraries as D          # noqa: E402

# (scenario, library file under results/booksim/)
LIBS = [("offload6x6", "offload/library_offload6x6.json"), ("offload_decode6x6", "offload/library_offload_decode6x6.json"),
        ("offload2_8x8", "offload/library_offload2_8x8.json"), ("layer6x6", "onchip/library_layer6x6.json")]


def cclass(n):
    if n in ("sequential", "compact_fill"):
        return "default fill"
    if n.startswith("random_s"):
        return "random"
    if n.startswith("sa_"):
        return "search endpoint (" + n[3:].rsplit("_s", 1)[0] + ")"
    if n.startswith("traj_"):
        return "trajectory sample (full objective, seed 0)"
    return "named rule"


def silicon():
    t1 = json.load(open(paths.SIMBA_SEATING))
    rows = []
    for i, r in enumerate(t1["rows"]):
        rows.append({"seating_index": i, "seating_chiplets_xy": json.dumps(r["seating"]), "longest_pair_hops": r["max_hops"], "position_label": "adjacent" if i == 0 else f"{int(r['max_hops'])} hops",
                     "measured_norm": r["measured_norm"], "measured_source": "Shao et al., MICRO'19, section 4.6, Fig. 9 (res4a_branch1, 4 chiplets, far/near seatings): execution time relative to the adjacent seating, read from the figure",
                     "bound_series_raw_s": r["latency_max_end_s"], "bound_series_norm": r["ratio_max_end"], "bound_series_definition": "resource service lower bound: compute + max(serialization, busiest resource / B) + propagation, end of the last hand-off",
                     "protocol_series_raw_s": r["latency_pess_s"], "protocol_series_norm": r["ratio_pess"], "protocol_series_definition": "protocol execution estimate: round-serialized packets at 17 flits / 128 B, hop latency per packet, no overlap across rounds",
                     "sum_end_raw_s": r["latency_sum_end_s"], "sum_end_norm": r["ratio_sum_end"], "compute_s": r["compute_s"], "serialization_s": r["serialization_s"], "propagation_s": r["prop_s"], "packet_term_s": r["packet_term_s"], "busiest_words": r["busiest_words"],
                     "normalisation": "each series / its own value at the adjacent seating (index 0)", "layer": t1["layer"], "frozen_split": json.dumps(t1["frozen_split"]),
                     "source_record": os.path.relpath(paths.SIMBA_SEATING, WS)})
    return rows, {"ratio_bound": t1["ratio_far_bound"], "ratio_protocol": t1["ratio_far_protocol"], "measured_far": t1["rows"][-1]["measured_norm"]}


def libraries():
    costs, summ, groups, sel = [], [], [], []
    for lid, rel in LIBS:
        lib = json.load(open(os.path.join(paths.BOOKSIM, rel))); c = lib["candidates"]
        base = "sequential" if "sequential" in c else "compact_fill"
        names = list(c)
        has_bs = [n for n in names if c[n].get("booksim_cycles") is not None]
        b = c[base]
        for n in names:
            r = c[n]
            costs.append({"scenario_id": lid, "candidate_id": n, "candidate_class": cclass(n), "analytic_full_score_words": r["A_full"], "analytic_links_only_words": r["A_links"], "analytic_handoff_time_s": r["handoff_T_s"], "T_s": r["T_s"], "H_s": r["H_s"],
                          "word_hops": r["word_hops"], "max_hops": r["max_hops"], "mean_hops": r["mean_hops"], "logical_payload_words": r["words"], "n_flows": r["n_flows"], "booksim_cycles": r.get("booksim_cycles", ""), "bound_cycles": r.get("bound_cycles", ""),
                          "booksim_over_bound": r.get("booksim_over_bound", ""), "booksim_packets": r.get("booksim_packets", ""), "baseline_id": base,
                          "analytic_normalized": r["A_full"] / b["A_full"], "booksim_normalized": (r["booksim_cycles"] / b["booksim_cycles"]) if r.get("booksim_cycles") and b.get("booksim_cycles") else "",
                          "word_hops_normalized": r["word_hops"] / b["word_hops"], "is_library_start": n == lib["start"], "source": rel})
        # summary
        xs = [c[n]["A_full"] for n in has_bs]; ys = [c[n]["booksim_cycles"] for n in has_bs]
        ob = [c[n]["booksim_over_bound"] for n in has_bs if c[n].get("booksim_over_bound")]
        summ.append({"scenario_id": lid, "source": rel, "grid": "x".join(map(str, lib["grid"])), "n_layers": lib["L"], "phase": lib["phase"], "only_handoff": lib["only_handoff"], "offload": lid.startswith("offload"), "analytic_kappa": lib["kappa"], "booksim_concentration": lib["kappa_booksim"],
                      "volume_scale_in_booksim": lib["scale"], "n_candidates": len(names), "n_with_booksim": len(has_bs), "baseline_id": base, "library_start": lib["start"],
                      "spearman_A_full_vs_booksim": D.spearman(xs, ys) if has_bs else "", "spearman_word_hops_vs_booksim": D.spearman([c[n]["word_hops"] for n in has_bs], ys) if has_bs else "",
                      "inversions_A_full": D.inversions(xs, ys) if has_bs else "", "booksim_over_bound_min": min(ob) if ob else "", "booksim_over_bound_median": statistics.median(ob) if ob else "", "booksim_over_bound_max": max(ob) if ob else "",
                      "candidate_classes": "default fill; named rules (seed 0); random_s0..49; search endpoints sa_{full,links_only,word_hops,max_hops}_s0..2 from the library start; trajectory samples of the full search seed 0"})
        # exact word-hops groups (same logical payload)
        by = {}
        for n in has_bs:
            by.setdefault((c[n]["word_hops"], c[n]["words"], c[n]["n_flows"]), []).append(n)
        gi = 0
        for (wh, w, nf), mem in sorted(by.items()):
            if len(mem) < 2:
                continue
            gi += 1
            bs = {n: c[n]["booksim_cycles"] for n in mem}; af = {n: c[n]["A_full"] for n in mem}
            for n in sorted(mem, key=lambda n: af[n]):
                groups.append({"scenario_id": lid, "group_id": f"{lid}:wh{gi}", "candidate_id": n, "candidate_class": cclass(n), "exact_word_hops": wh, "logical_payload_words": w, "n_flows": nf, "group_size": len(mem),
                               "analytic_full_score_words": af[n], "analytic_full_score_over_group_min": af[n] / min(af.values()), "booksim_cycles": bs[n], "booksim_over_group_min": bs[n] / min(bs.values()),
                               "group_booksim_span": max(bs.values()) / min(bs.values()) - 1, "group_analytic_span": max(af.values()) / min(af.values()) - 1, "max_hops": c[n]["max_hops"],
                               "topology": f"{lib['grid'][0]}x{lib['grid'][1]} mesh, XY (dor) routing; BookSim cmesh c={lib['kappa_booksim']}", "analytic_kappa": lib["kappa"], "equivalence": "exact integer word-hops and identical logical payload / flow count (tol 0)", "source": rel})
        # selection by objective (stable id rule)
        best_bs = min(has_bs, key=lambda n: c[n]["booksim_cycles"]) if has_bs else None
        for obj in ("A_full", "A_links", "word_hops", "max_hops"):
            vals = {n: c[n][obj] for n in has_bs}
            m = min(vals.values()); ties = sorted(n for n in has_bs if vals[n] == m)
            pick = ties[0]
            regs = sorted(c[n]["booksim_cycles"] / c[best_bs]["booksim_cycles"] - 1 for n in ties)
            ends = [n for n in has_bs if n.startswith("sa_full_s")]
            er = [c[n]["booksim_cycles"] / c[best_bs]["booksim_cycles"] - 1 for n in ends]
            sel.append({"scenario_id": lid, "objective": obj, "selected_id_stable_rule": pick, "selected_score": m, "min_score_tie_set_size": len(ties), "min_score_tie_members": ";".join(ties),
                        "booksim_best_id": best_bs, "booksim_best_cycles": c[best_bs]["booksim_cycles"], "regret_selected": c[pick]["booksim_cycles"] / c[best_bs]["booksim_cycles"] - 1, "tie_regret_min": regs[0], "tie_regret_median": statistics.median(regs), "tie_regret_max": regs[-1],
                        "full_search_endpoints": ";".join(ends), "full_endpoint_regret_min": min(er) if er else "", "full_endpoint_regret_max": max(er) if er else "",
                        "rule": "lowest analytic score; exact ties broken by the stable candidate id (sorted name, first)", "source": rel})
    return costs, summ, groups, sel


def protocols(t1):
    return {"booksim": {"topology": "cmesh (concentrated mesh), c = 4 terminals per node", "k": "grid side", "n": 2, "c": 4, "xr_yr": 2,
                        "routing": "dor_no_express (dimension order)", "allocators": "wavefront switch and VC allocators",
                        "packet": f"{bb.PACKET_FLITS} flits = {bb.PACKET_PAYLOAD_B:.0f} B payload ({bb.FLIT_PAYLOAD_B:.0f} B per flit)", "vc_buf_size": 34,
                        "hop_latency": f"{bb.HOP_CHANNEL_CYCLES} channel cycles + {bb.HOP_ROUTER_CYCLES} router cycles = {bb.HOP_CHANNEL_CYCLES + bb.HOP_ROUTER_CYCLES} per hop",
                        "injection": "batch mode, every packet offered at cycle 0", "timing": "batch completion cycles per hand-off, summed over the hand-offs (serial execution)",
                        "volume_scale": "prefill instances 0.01 of the words, decode instances 1.0",
                        "effective_port_capacity": "c = 4 terminal channels per node = 4 x the link; a digital-unit node has the same 4 terminals",
                        "bound": "max over channel loads, injection and ejection loads in flit cycles; booksim_over_bound = batch duration / bound"},
            "analytic": {"offload_libraries": "kappa 4 (CIM ports and the digital interface at 4 x B_mesh, as BookSim's terminals)",
                         "onchip_library": "kappa 2; attention on one CIM die per layer",
                         "objective_A_full": "sum over hand-offs of the busiest resource in words (links, die ports, unit ports)"},
            "selection_rule": "lowest analytic score; exact ties broken by the sorted candidate id; uses deployment-time information only",
            "baseline": "the library's default fill (sequential): analytic_normalized = A_full / A_full(baseline), booksim_normalized = cycles / cycles(baseline)",
            "silicon_reference": {"source": "Shao et al., MICRO'19 section 4.6 Fig. 9 (Simba, res4a_branch1 on 4 chiplets, far/near seatings)",
                                  "series": ["measured (figure reading)", "resource service lower bound", "protocol execution estimate (round-serialized packets)"],
                                  "normalisation": "each series / its adjacent-seating value", **t1},
            "code_version": V.code_version()}


def main():
    os.makedirs(V.EXPORTS, exist_ok=True)
    srows, t1 = silicon(); V.write_csv("silicon_reference.csv", srows)
    costs, summ, groups, sel = libraries()
    V.write_csv("booksim_candidate_costs.csv", costs); V.write_csv("booksim_library_summary.csv", summ)
    V.write_csv("equivalent_candidate_groups.csv", groups); V.write_csv("booksim_selection_by_objective.csv", sel)
    V.write_json("validation_protocols.json", protocols(t1))
    spans = {g["group_id"]: g["group_booksim_span"] for g in groups}
    top = max(spans, key=spans.get)
    print(f"largest exact word-hops group: {top} BookSim span {spans[top]*100:.1f}% (members: {[g['candidate_id'] for g in groups if g['group_id'] == top]})")
    for s in summ:
        print(f"  {s['scenario_id']:18s} n {s['n_candidates']} rho {s['spearman_A_full_vs_booksim']:.3f} BookSim/bound {s['booksim_over_bound_min']:.2f}-{s['booksim_over_bound_max']:.2f}")
    for s in sel:
        if s["objective"] in ("A_full", "word_hops"):
            print(f"  {s['scenario_id']:18s} {s['objective']:9s} pick {s['selected_id_stable_rule']:22s} ties {s['min_score_tie_set_size']} regret {s['tie_regret_min']*100:.1f}-{s['tie_regret_max']*100:.1f}% BookSim best {s['booksim_best_id']}")


if __name__ == "__main__":
    main()
