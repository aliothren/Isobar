"""Fig. 3 / Fig. 4 data (Isobar_next_tasks sections 3.3, 3.4): the silicon
seating reference (Simba T1), the per-candidate BookSim libraries with a
common baseline per library, the exact word-hops equivalence groups, the
selection-by-objective audit (stable candidate id rule) and the per-stage
tie diagnostics (analytic resources + targeted BookSim re-runs per stage).

    E3_KAPPA_AN=2 python3 scripts/v7_fig3_fig4_validation.py [--no-booksim]
      -> analysis/v7/silicon_reference.csv, booksim_candidate_costs.csv, booksim_library_summary.csv,
         equivalent_candidate_groups.csv, booksim_selection_by_objective.csv, booksim_tie_diagnostics.csv,
         runtime_summary.csv / runtime_samples.csv / runtime_environment.json (renamed columns), validation_protocols.json
"""
import argparse
import csv
import json
import os
import shutil
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v7_common as V                      # noqa: E402
from scripts import v6_common as C                      # noqa: E402
from scripts import v3_discrim as D                     # noqa: E402
from scripts import cimsim_cli as cli                   # noqa: E402
from scripts import search_eval as se                   # noqa: E402
from scripts import search_space as ss                  # noqa: E402

A = os.path.join(WS, "analysis")
LIBS = [("offload6x6", "v3/e3_offload/library_offload6x6.json"), ("offload_decode6x6", "v3/e3_offload/library_offload_decode6x6.json"), ("offload2_8x8", "v3/e3_offload/library_offload2_8x8.json"),
        ("layer6x6", "v3/e3_k2/library_layer6x6.json"), ("layers2_8x8", "v3/e3_k2/library_layers2_8x8.json"), ("layer12x12", "v3/e3_k2/library_layer12x12.json"), ("decode6x6", "v3/e3_k2/library_decode6x6.json"), ("mech4x4", "v3/e3_k2/library_mech4x4.json")]
SCEN = {"layer6x6": dict(grid=(6, 6), L=1, phase="prefill"), "layers2_8x8": dict(grid=(8, 8), L=2, phase="prefill"), "layer12x12": dict(grid=(12, 12), L=1, phase="prefill"), "decode6x6": dict(grid=(6, 6), L=1, phase="decode"),
        "offload6x6": dict(grid=(6, 6), L=1, phase="prefill", offload=True), "offload_decode6x6": dict(grid=(6, 6), L=1, phase="decode", offload=True), "offload2_8x8": dict(grid=(8, 8), L=2, phase="prefill", offload=True)}


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
    t1 = json.load(open(os.path.join(A, "simba_t1.json")))
    rows = []
    for i, r in enumerate(t1["rows"]):
        rows.append({"seating_index": i, "seating_chiplets_xy": json.dumps(r["seating"]), "longest_pair_hops": r["max_hops"], "position_label": "adjacent" if i == 0 else f"{int(r['max_hops'])} hops",
                     "measured_norm": r["measured_norm"], "measured_source": "Shao et al., MICRO'19, section 4.6, Fig. 9 (res4a_branch1, 4 chiplets, far/near seatings): execution time relative to the adjacent seating, read from the figure",
                     "bound_series_raw_s": r["latency_max_end_s"], "bound_series_norm": r["ratio_max_end"], "bound_series_definition": "resource service lower bound: compute + max(serialization, busiest resource / B) + propagation, end of the last hand-off",
                     "protocol_series_raw_s": r["latency_pess_s"], "protocol_series_norm": r["ratio_pess"], "protocol_series_definition": "protocol execution estimate: round-serialized packets at 17 flits / 128 B, hop latency per packet, no overlap across rounds (latency_pess)",
                     "sum_end_raw_s": r["latency_sum_end_s"], "sum_end_norm": r["ratio_sum_end"], "compute_s": r["compute_s"], "serialization_s": r["serialization_s"], "propagation_s": r["prop_s"], "packet_term_s": r["packet_term_s"], "busiest_words": r["busiest_words"],
                     "normalisation": "each series / its own value at the adjacent seating (index 0)", "layer": t1["layer"], "frozen_split": json.dumps(t1["frozen_split"]), "source_record": "analysis/simba_t1.json; protocol analysis/SIMBA_PREREG.md (T1)"})
    return rows, {"T1b_ratio_bound": t1["T1b_ratio"], "T1b_ratio_protocol": t1["T1b_ratio_pess"], "T1b_band": t1["T1b_band"], "measured_far": t1["rows"][-1]["measured_norm"]}


def libraries():
    costs, summ, groups, sel = [], [], [], []
    for lid, rel in LIBS:
        lib = json.load(open(os.path.join(A, rel))); c = lib["candidates"]
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


def stage_diag(targets, with_booksim):
    """targets: [(scenario_id, [candidate ids], reason)]. Per candidate per hand-off: analytic resources and (optionally) BookSim per stage."""
    bb = None
    if with_booksim:
        from scripts import booksim_bridge as bb_
        bb = bb_
    out = []
    libs = {lid: json.load(open(os.path.join(A, rel))) for lid, rel in LIBS}
    for lid, cands, reason in targets:
        lib = libs[lid]; c = lib["candidates"]; kappa = lib["kappa"]; k = lib["grid"][0]; scale = lib["scale"]
        if lid == "mech4x4":
            W = D.make_W((4, 4), 1, kappa=kappa)
            base = D.lw.block_chain(W.cfg, W.S, "prefill", on_chip=True, max_dies=10 ** 6)
            names = [e["name"] for e in base]; prev_e, e = base[names.index("ffn1")], base[names.index("ffn2")]
            hand = lambda pi: [("ffn2@L0", se._one_boundary_flows(prev_e, e, list(pi[0]), list(pi[1]), W.fab))]
            parse = lambda s: json.loads(s)
        else:
            sc = SCEN[lid]
            W = D.make_W(sc["grid"], sc["L"], kappa=kappa, phase=sc["phase"], offload=sc.get("offload", False))
            hand = lambda pi: cli.handoff_flows(W, pi, sc["phase"])
            parse = ss.Pi.from_json
        icl = W.die_ic
        for n in cands:
            pi = parse(c[n]["pi"])
            hs = hand(pi)
            tot_bs = 0
            for into, fl in hs:
                loads = se.resource_loads(fl, icl, ports=True, kappa=kappa)
                items = sorted(loads.items(), key=lambda kv: -kv[1])
                links = [v for kk, v in loads.items() if kk[0] != "port"]
                ports = [v for kk, v in loads.items() if kk[0] == "port"]
                hops = [int(round(icl.hops(*f["nodes"]))) for f in fl]
                words = sum(f["volume"] * f["width"] for f in fl)
                row = {"scenario_id": lid, "diagnostic_set": reason, "candidate_id": n, "candidate_class": cclass(n), "into": into, "n_flows": len(fl), "payload_words": words,
                       "busiest_resource": " ".join(map(str, items[0][0])), "busiest_words": items[0][1], "busiest_kind": "port" if items[0][0][0] == "port" else "link",
                       "second_resource": " ".join(map(str, items[1][0])) if len(items) > 1 else "", "second_words": items[1][1] if len(items) > 1 else "", "second_over_busiest": (items[1][1] / items[0][1]) if len(items) > 1 else "",
                       "busiest_link_words": max(links) if links else 0, "busiest_port_words_over_kappa": max(ports) if ports else 0, "n_links_used": len(links), "mean_link_words": (sum(links) / len(links)) if links else 0,
                       "link_concentration_busiest_over_mean": (max(links) / (sum(links) / len(links))) if links else "", "links_within_90pct_of_busiest": sum(1 for v in links if v >= 0.9 * max(links)) if links else 0,
                       "max_hops": max(hops) if hops else 0, "word_hops": int(sum(round(f["volume"] * f["width"]) * h for f, h in zip(fl, hops))), "propagation_s": (max(hops) if hops else 0) * se.NS_PER_HOP_D2D * 1e-9,
                       "analytic_stage_service_words": items[0][1], "analytic_kappa": kappa}
                if bb is not None and scale is not None:
                    agg = {}
                    for f in fl:
                        a, b2 = f["nodes"]; agg[(a, b2)] = agg.get((a, b2), 0.0) + f["volume"] * f["width"]
                    flows = [(a, b2, bb.packets_for(w * scale)) for (a, b2), w in agg.items()]
                    bound = max(bb.flit_bounds(flows, k=k, kappa=lib["kappa_booksim"]).values())
                    cyc = bb.run_batch(flows, k=k, kappa=lib["kappa_booksim"])["cycles"]
                    row.update({"booksim_stage_cycles": cyc, "booksim_stage_bound_cycles": bound, "booksim_stage_over_bound": cyc / bound if bound else "", "booksim_packets": sum(x for _, _, x in flows)})
                    tot_bs += cyc
                out.append(row)
            if bb is not None and scale is not None:
                rec_tot = c[n].get("booksim_cycles")
                for r in out:
                    if r["scenario_id"] == lid and r["candidate_id"] == n:
                        r["booksim_total_rerun_cycles"] = tot_bs; r["booksim_total_recorded_cycles"] = rec_tot; r["rerun_matches_record"] = (rec_tot == tot_bs)
    return out


def runtime_files():
    """Copies of the v6 runtime files with the consistency column renamed and the speed-up as its own column."""
    out = []
    src = os.path.join(C.V6, "runtime_summary.csv")
    for r in csv.DictReader(open(src)):
        r = dict(r)
        r["incremental_relative_error"] = r.pop("incremental_vs_full_rel_err")
        r["full_over_incremental_speedup"] = float(r["full_eval_median_s"]) / float(r["incremental_median_s"])
        r["model"] = {"ref2p7b": "reference 2.7B (GPT-class, d 2560, 32 layers)", "opt6.7b": "OPT-6.7B", "gemma7b": "Gemma-7B", "opt13b": "OPT-13B"}[r["config_id"].split("_")[0]]
        r["init_definition"] = "account load + workload build (the CiMLoop mapper account is generated separately, once per (model, S), and is not part of this timing)"
        r["repeats"] = 7
        out.append(r)
    V.write_csv("runtime_summary.csv", out)
    shutil.copy(os.path.join(C.V6, "runtime_samples.csv"), os.path.join(V.V7, "runtime_samples.csv")); print("  analysis/v7/runtime_samples.csv (copy)")
    env = json.load(open(os.path.join(C.V6, "runtime_environment.json")))
    env["incremental_relative_error"] = "|J_incremental(final layout) - full score(final layout)| / J_incremental: a consistency check of the incremental update, not a timing"
    V.write_json("runtime_environment.json", env)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--no-booksim", action="store_true"); args = ap.parse_args()
    os.makedirs(V.V7, exist_ok=True)
    srows, t1 = silicon(); V.write_csv("silicon_reference.csv", srows)
    costs, summ, groups, sel = libraries()
    V.write_csv("booksim_candidate_costs.csv", costs); V.write_csv("booksim_library_summary.csv", summ); V.write_csv("equivalent_candidate_groups.csv", groups); V.write_csv("booksim_selection_by_objective.csv", sel)
    # the 81.8% group and the diagnostic targets
    spans = {}
    for g in groups:
        spans[g["group_id"]] = (g["group_booksim_span"], g["scenario_id"])
    top = max(spans.items(), key=lambda kv: kv[1][0])
    print(f"largest exact word-hops group span: {top[0]} {top[1][0]*100:.1f}% (members: {[g['candidate_id'] for g in groups if g['group_id']==top[0]]})")
    targets = []
    dec = [s for s in sel if s["scenario_id"] == "offload_decode6x6" and s["objective"] == "A_full"][0]
    targets.append(("offload_decode6x6", dec["min_score_tie_members"].split(";"), "offload decode minimum-analytic-score exact tie set"))
    m4 = [s for s in sel if s["scenario_id"] == "mech4x4" and s["objective"] == "A_full"][0]
    targets.append(("mech4x4", m4["min_score_tie_members"].split(";"), "4x4 hand-off minimum-analytic-score exact tie set (stable id pick)"))
    targets.append((top[1][1], [g["candidate_id"] for g in groups if g["group_id"] == top[0]], f"largest exact word-hops equivalence group ({top[0]})"))
    diag = stage_diag(targets, not args.no_booksim)
    V.write_csv("booksim_tie_diagnostics.csv", diag)
    runtime_files()
    prot = json.load(open(os.path.join(C.V6, "validation_protocols.json")))
    prot["silicon_reference"] = {"source": "Shao et al., MICRO'19 section 4.6 Fig. 9 (Simba, res4a_branch1 on 4 chiplets, far/near seatings)", "series": ["measured (figure reading)", "resource service lower bound", "protocol execution estimate (round-serialized packets)"], "normalisation": "each series / its adjacent-seating value", **t1}
    prot["booksim_candidate_costs"] = {"baseline": "the library's default fill (sequential; compact_fill on mech4x4): analytic_normalized = A_full / A_full(baseline), booksim_normalized = cycles / cycles(baseline)",
                                       "offload_libraries": "analytic kappa 4 = BookSim cmesh c 4; the unit interface = 4 mesh links; dor routing; 17-flit / 128 B packets; 10 + 4 cycles per hop; wavefront allocators; batch injection",
                                       "on_chip_libraries_e3_k2": "analytic kappa 2 (ports never bind beyond kappa 2), BookSim c 4; the ReRAM-attention setting of V3 (one attention die per layer)"}
    prot["tie_diagnostics"] = {"analytic": "per hand-off resource loads at the library's analytic kappa (links and die ports), concentration = busiest link / mean used link", "booksim_per_stage": "targeted re-run of the same batch per hand-off with the library's settings; the per-candidate sum is checked against the recorded total",
                               "equivalence_classes": "exact (tol 0 on integer word-hops with identical payload and flow count); displayed-rounding and tolerance ties are in analysis/v6/booksim_tie_sets.csv (tol 0 / 1e-3 / 5e-3 / 1e-2)"}
    prot["code_version"] = V.code_version()
    V.write_json("validation_protocols.json", prot)
    for s in summ:
        print(f"  {s['scenario_id']:18s} n {s['n_candidates']} rho {s['spearman_A_full_vs_booksim']:.3f} bs/bound {s['booksim_over_bound_min']:.2f}-{s['booksim_over_bound_max']:.2f}")
    for s in sel:
        if s["objective"] in ("A_full", "word_hops"):
            print(f"  {s['scenario_id']:18s} {s['objective']:9s} pick {s['selected_id_stable_rule']:22s} ties {s['min_score_tie_set_size']} regret {s['tie_regret_min']*100:.1f}-{s['tie_regret_max']*100:.1f}% booksim best {s['booksim_best_id']}")


if __name__ == "__main__":
    main()
