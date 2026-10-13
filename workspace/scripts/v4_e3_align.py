"""Next-round item 1.2: the E3 analytic side and the BookSim side under the
same port ratio.

The e3_k2 libraries were scored analytically at kappa 2 and simulated in
BookSim as a concentrated mesh with c = 4 terminals per die (cmesh needs a
square concentration). This script re-scores every saved candidate and
every ablation endpoint analytically at kappa 1, 2 and 4 from its saved
seating (no new search, no new BookSim run), and records per hand-off
whether a port is the binding resource, so that

  - the kappa 4 analytic value is compared with the kappa 4 BookSim run as
    the like-for-like validation (rho, inversions, selection regret);
  - the kappa 2 and kappa 4 analytic values are compared candidate by
    candidate (port binding, ordering, selection) to say where the kappa
    2 main system and the kappa 4 simulation coincide and where not;
  - the candidate counts (total, with a valid BookSim result) are taken
    from the libraries themselves;
  - the ablation tables are regenerated with every computable field and
    an explicit "n/a" where no simulator run exists.

The ref544 library stores no seatings (its candidates are 544-die layouts
scored by the full analytic model as an internal comparison); it is listed
with its recorded values only and is not counted as an external
validation.

    python3 scripts/v4_e3_align.py   -> analysis/v4/e3_align/{candidates.csv, scenarios.md, ablation.md, summary.json}
"""
import csv
import glob
import json
import os
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import cimsim_cli as cli            # noqa: E402
from scripts import llm_workload as lw           # noqa: E402
from scripts import search_eval as se            # noqa: E402
from scripts import search_space as ss           # noqa: E402
from scripts import v3_discrim as d3             # noqa: E402
from scripts import v3_sweep as v3               # noqa: E402

E3 = os.path.join(v3.V3, "e3_k2")
OUT = os.path.join(WS, "analysis", "v4", "e3_align")
KAPPAS = (1.0, 2.0, 4.0)
BW = d3.BW


def handoff_flows_for(lib, W, pi_json):
    """Flow lists per hand-off of a saved candidate."""
    if lib["scenario"] == "mech4x4":
        base = lw.block_chain(W.cfg, W.S, "prefill", on_chip=True, max_dies=10 ** 6)
        names = [e["name"] for e in base]
        prev_e, e = base[names.index("ffn1")], base[names.index("ffn2")]
        pc = json.loads(pi_json)
        return [se._one_boundary_flows(prev_e, e, list(pc[0]), list(pc[1]), W.fab)]
    pi = ss.Pi.from_json(pi_json)
    only = lib.get("only_handoff")
    return [fl for n, fl in cli.handoff_flows(W, pi, lib["phase"]) if (only is None or n.split("@")[0] == only)]


def score_at(handoffs, icl, kappa):
    """A (busiest-resource words summed over hand-offs) and the number of
    hand-offs whose binding resource is a port, at this port ratio."""
    A, nport, nh = 0.0, 0, 0
    for fl in handoffs:
        loads = se.resource_loads(fl, icl, ports=True, kappa=kappa)
        key = max(loads, key=loads.get)
        A += loads[key]
        nport += key[0] == "port"
        nh += 1
    return A, nport, nh


def main():
    os.makedirs(OUT, exist_ok=True)
    rows, scen_md, summary = [], [], {}
    for f in sorted(glob.glob(os.path.join(E3, "library_*.json"))):
        lib = json.load(open(f))
        name = lib["scenario"]
        cands = lib["candidates"]
        n_total = len(cands)
        n_bs = sum(1 for c in cands.values() if c.get("booksim_cycles"))
        if name == "ref544" or all(c.get("pi") is None for c in cands.values()):
            summary[name] = {"n_total": n_total, "n_booksim": n_bs, "note": "no seatings stored; recorded analytic values only (internal comparison, not an external validation)"}
            scen_md.append(f"| {name} | {n_total} | {n_bs} | internal (full analytic model) | | | | | | |")
            continue
        grid, L, phase = tuple(lib["grid"]), lib["L"] or 1, lib["phase"]
        W = {k: d3.make_W(grid, L, kappa=k, phase=phase) for k in KAPPAS}
        icl = W[2.0].die_ic
        per = {}
        for cname, c in cands.items():
            hs = handoff_flows_for(lib, W[2.0], c["pi"])
            rec = {"scenario": name, "candidate": cname, "n_handoffs": len(hs), "booksim_cycles": c.get("booksim_cycles"),
                   "bound_cycles": c.get("bound_cycles"), "A_full_recorded_k2": c["A_full"], "word_hops": c["word_hops"], "max_hops": c["max_hops"]}
            for k in KAPPAS:
                A, nport, nh = score_at(hs, icl, k)
                rec[f"A_k{k:g}"] = A; rec[f"port_bound_handoffs_k{k:g}"] = nport
            per[cname] = rec
            rows.append(rec)
        names = list(per)
        bs_names = [n for n in names if per[n]["booksim_cycles"]]
        ref = [per[n]["booksim_cycles"] for n in bs_names]
        stats = {"n_total": n_total, "n_booksim": len(bs_names), "grid": grid, "L": L, "phase": phase}
        # consistency of the re-scoring with the recorded kappa 2 value
        stats["max_rel_err_recorded_k2"] = max(abs(per[n]["A_k2"] / per[n]["A_full_recorded_k2"] - 1) for n in names if per[n]["A_full_recorded_k2"])
        for k in KAPPAS:
            vals = [per[n][f"A_k{k:g}"] for n in bs_names]
            stats[f"rho_booksim_A_k{k:g}"] = d3.spearman(vals, ref) if len(set(vals)) > 1 else "n/a (constant)"
            stats[f"inversions_booksim_A_k{k:g}"] = d3.inversions(vals, ref) if len(set(vals)) > 1 else "n/a"
            best_ref = min(ref)
            pick = min(bs_names, key=lambda n: (per[n][f"A_k{k:g}"], n))
            picks = [n for n in bs_names if per[n][f"A_k{k:g}"] == per[pick][f"A_k{k:g}"]]
            regs = [per[n]["booksim_cycles"] / best_ref - 1 for n in picks]
            stats[f"regret_A_k{k:g}"] = {"selected": pick, "tie_set": len(picks), "min": min(regs), "max": max(regs)}
            stats[f"port_bound_candidates_k{k:g}"] = sum(1 for n in names if per[n][f"port_bound_handoffs_k{k:g}"])
            stats[f"port_bound_handoffs_k{k:g}"] = sum(per[n][f"port_bound_handoffs_k{k:g}"] for n in names)
        # kappa 2 vs kappa 4 analytic: equality candidate by candidate, ordering, selection
        eq = sum(1 for n in names if abs(per[n]["A_k2"] - per[n]["A_k4"]) <= 1e-9 * max(1.0, per[n]["A_k2"]))
        o2 = sorted(names, key=lambda n: (per[n]["A_k2"], n)); o4 = sorted(names, key=lambda n: (per[n]["A_k4"], n))
        stats["k2_vs_k4"] = {"candidates_equal": eq, "of": len(names), "same_full_order": o2 == o4,
                             "rho": d3.spearman([per[n]["A_k2"] for n in names], [per[n]["A_k4"] for n in names]),
                             "same_selected": o2[0] == o4[0], "max_rel_diff": max(abs(per[n]["A_k4"] / per[n]["A_k2"] - 1) for n in names)}
        summary[name] = stats
        f_ = lambda v: f"{v:.3f}" if isinstance(v, float) else str(v)
        scen_md.append(f"| {name} | {n_total} | {len(bs_names)} | BookSim c=4 | {f_(stats['rho_booksim_A_k4'])} | {f_(stats['rho_booksim_A_k2'])} | {f_(stats['rho_booksim_A_k1'])} | "
                       f"{stats['port_bound_candidates_k2']} / {stats['port_bound_candidates_k4']} / {stats['port_bound_candidates_k1']} | "
                       f"{stats['k2_vs_k4']['candidates_equal']} of {len(names)}, same order {stats['k2_vs_k4']['same_full_order']}, same pick {stats['k2_vs_k4']['same_selected']} | "
                       f"k4 {stats['regret_A_k4']['min']*100:.1f} to {stats['regret_A_k4']['max']*100:.1f}%, k2 {stats['regret_A_k2']['min']*100:.1f} to {stats['regret_A_k2']['max']*100:.1f}% |")
    with open(os.path.join(OUT, "candidates.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    # ablations: re-score endpoints at kappa 1/2/4, fill every computable field
    abl_md = ["# E3 ablations at the main port ratio, regenerated\n",
              "Gains are against the strongest candidate of the instance's own library at kappa 2 (analytic, A at B = 0.4 GB/s plus the layer terms where the instance has them); "
              "BookSim columns exist only for the instances that were simulated (c = 4, wavefront); 'n/a' marks a field that has no simulator run, not a missing computation. "
              "Statistic: per seed the best over the three starts, then the median (and the best) over the five seeds, as in the V3 records. Overhead vs full = that median (or best) against the full objective's.\n"]
    for f in sorted(glob.glob(os.path.join(E3, "ablation_*.json"))) + sorted(glob.glob(os.path.join(v3.V3, "e3", "ablation_ref_k*.json"))):
        d = json.load(open(f))
        for cname, rec in d.items():
            lib_name = cname.replace("_k2", "").replace("_k1", "").replace("_k4", "")
            libp = os.path.join(E3, f"library_{lib_name}.json")
            lib = json.load(open(libp)) if os.path.exists(libp) else None
            n_dies = rec.get("n_dies")
            Wk = None
            if lib and lib["scenario"] != "ref544":
                grid, L, phase = tuple(lib["grid"]), lib["L"] or 1, lib["phase"]
                Wk = {k: d3.make_W(grid, L, kappa=k, phase=phase) for k in KAPPAS}
                if n_dies is None:
                    n_dies = 10 if lib["scenario"] == "mech4x4" else None
            elif cname.startswith("ref_"):          # the 544-die reference ablation: full 24x24 layouts, every hand-off
                lib = {"scenario": "ref", "phase": "prefill", "only_handoff": None}
                Wk = {k: d3.make_W((24, 24), 32, kappa=k, phase="prefill") for k in KAPPAS}
            runs = rec["runs"]
            by_obj = {}
            for rn, r in runs.items():
                by_obj.setdefault(r["objective"], []).append(r)
            vk = "T_s" if "T_s" in next(iter(runs.values())) else "A_full"      # the 4x4 instance records the hand-off load A, not a latency
            unit, scale = ("ms", 1e3) if vk == "T_s" else ("words", 1.0)
            abl_md.append(f"### {cname}: {n_dies if n_dies is not None else '?'} dies, strongest {rec['strongest']}, steps {rec.get('steps', 1200)}, kappa {rec.get('kappa')}\n")
            abl_md.append(f"| objective | runs | median ({unit}) | gain vs strongest (median) | gain (best) | overhead vs full (median) | overhead vs full (best) | A at kappa 2 / 4 of the median endpoint (words) | port-bound hand-offs at kappa 2 / 4 | BookSim median cycles | BookSim gain vs strongest | BookSim overhead vs full |")
            abl_md.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
            def per_seed_best(rs, key):
                by_seed = {}
                for r in rs:
                    if r.get(key) is None:
                        continue
                    if r["seed"] not in by_seed or r[key] < by_seed[r["seed"]][key]:
                        by_seed[r["seed"]] = r
                return by_seed
            # protocol statistic: per seed the best over the starts, then the median over seeds (the V3 record's summary)
            fs = per_seed_best(by_obj["full"], vk)
            full_T = sorted(r[vk] for r in fs.values()); full_med, full_best = statistics.median(full_T), min(full_T)
            fb = per_seed_best(by_obj["full"], "booksim_cycles"); full_bs = sorted(r["booksim_cycles"] for r in fb.values())
            for obj, rs in by_obj.items():
                ps = per_seed_best(rs, vk)
                Ts = sorted(r[vk] for r in ps.values())
                med, best = statistics.median(Ts), min(Ts)
                tb = rec["T_base_s"] if vk == "T_s" else rec["A_base"]
                r_med = min(ps.values(), key=lambda r: abs(r[vk] - med))
                a2 = a4 = p2 = p4 = "n/a (no seating stored)"
                if Wk is not None and r_med.get("pi"):
                    hs = handoff_flows_for(lib, Wk[2.0], r_med["pi"])
                    A2, pb2, _ = score_at(hs, Wk[2.0].die_ic, 2.0); A4, pb4, _ = score_at(hs, Wk[2.0].die_ic, 4.0)
                    a2, a4, p2, p4 = f"{A2:.0f}", f"{A4:.0f}", str(pb2), str(pb4)
                pb = per_seed_best(rs, "booksim_cycles")
                bs = sorted(r["booksim_cycles"] for r in pb.values())
                bs_med = statistics.median(bs) if bs else None
                sbc = rec.get("strongest_booksim_cycles")
                abl_md.append(f"| {obj} | {len(rs)} | {med*scale:.3f} | {(1-med/tb)*100:.2f}% | {(1-best/tb)*100:.2f}% | {(med/full_med-1)*100:+.2f}% | {(best/full_best-1)*100:+.2f}% | "
                              f"{a2} / {a4} | {p2} / {p4} | " + (f"{bs_med:.0f}" if bs_med else "n/a (no simulator run)") + " | "
                              + (f"{(1-bs_med/sbc)*100:.2f}%" if (bs_med and sbc) else "n/a") + " | "
                              + (f"{(bs_med/statistics.median(full_bs)-1)*100:+.2f}%" if (bs_med and full_bs) else "n/a") + " |")
            abl_md.append("")
    open(os.path.join(OUT, "ablation.md"), "w").write("\n".join(abl_md) + "\n")
    md = ["# E3 analytic side at kappa 1 / 2 / 4 against the BookSim c = 4 runs\n",
          "Every candidate's seating was re-scored analytically at the three port ratios; BookSim cycles are the recorded c = 4 runs (no new simulation). "
          "'Port-bound' counts candidates with at least one hand-off whose binding resource is an injection or ejection port at that ratio. "
          "The like-for-like validation column is rho(A at kappa 4, BookSim c = 4); the kappa 2 column is the main system's objective against the same runs.\n",
          "| scenario | candidates | with BookSim | reference | rho A(k4) vs BookSim | rho A(k2) vs BookSim | rho A(k1) vs BookSim | port-bound candidates k2 / k4 / k1 | kappa 2 vs 4 analytic | selection regret (BookSim) |",
          "|---|---|---|---|---|---|---|---|---|---|"] + scen_md
    md.append("")
    md.append("## Conditions fixed on both sides (recorded from `scripts/booksim_bridge.py` and `scripts/v3_discrim.py`)\n")
    md.append("- Traffic: the evaluator's own hand-off flows (producer die -> consumer die, words = volume x width), aggregated per (src, dst) pair, at 1/100 of the volume on the layer instances and at full volume on the decode instance; serial semantics, one BookSim batch per hand-off, cycles summed over the hand-offs of the candidate.")
    md.append("- Network: BookSim `cmesh`, k x k routers, n = 2, c = 4 terminals per router (xr = yr = 2), `dor_no_express` (dimension-order, no express channels), one packet of 17 flits = 128 B payload (8 B per flit), batch injection at rate 1.0 (every packet offered at cycle 0), vc_buf_size 34, channel latency 10 cycles (vendored patch 0002 makes cmesh honour it) plus the default 4-cycle input-queued router = 14 cycles per hop; `sw_allocator = vc_allocator = wavefront` (the default separable iSLIP starves a shared output under four local inputs, 1.37x the bound on a 3-flow test). The kappa = 1 corner runs use `mesh` with `dor` and the same packet, buffer and latency settings.")
    md.append("- Port ratio: on the analytic side kappa multiplies the per-die injection and ejection capacity (port load / (kappa B)); on the BookSim side a die is one router with c = kappa terminals, each terminal an injection/ejection channel of link bandwidth, and a flow's packets are spread over the c (terminal i -> terminal i) pairs. kappa 4 is the simulated value because cmesh needs a square concentration; the kappa 2 vs 4 columns above say on which candidates the two differ analytically.")
    md.append("- Reference bound: per hand-off the maximum over the direction-keyed channel loads, the injection loads and the ejection loads, in flit cycles; `booksim_over_bound` in the records is the batch duration divided by this bound (1.00 to 1.59 at c = 4).\n")
    for name, st in summary.items():
        if "k2_vs_k4" in st:
            md.append(f"- {name}: re-scoring reproduces the recorded kappa 2 values to {st['max_rel_err_recorded_k2']:.1e}; kappa 4 differs from kappa 2 on {st['k2_vs_k4']['of'] - st['k2_vs_k4']['candidates_equal']} of {st['k2_vs_k4']['of']} candidates "
                      f"(max relative difference {st['k2_vs_k4']['max_rel_diff']*100:.2f}%, rho {st['k2_vs_k4']['rho']:.4f}); port-bound hand-offs over all candidates: kappa 1 {st['port_bound_handoffs_k1']}, kappa 2 {st['port_bound_handoffs_k2']}, kappa 4 {st['port_bound_handoffs_k4']}; "
                      f"BookSim/bound (recorded) in `e3_k2/discriminability.json`.")
    open(os.path.join(OUT, "scenarios.md"), "w").write("\n".join(md) + "\n")
    json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), indent=1, default=str)
    print("->", OUT)


if __name__ == "__main__":
    main()
