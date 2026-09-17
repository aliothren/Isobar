"""Item 3: the seating-search gain under an outside judge, on a SHRUNK
COMPLETE instance -- see the FIXLIST pre-registration for the protocol.

    python3 scripts/b3_shrunk_rerank.py -> analysis/b3_shrunk_rerank.json
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import b3_booksim_cost_probe as pr
from scripts import booksim_bridge as bb
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_linkage as sl
from scripts import search_sa as sa

OUT = os.path.join(se.A, "b3_shrunk_rerank.json")
SCALE = 1.0 / 16
CELLS = {"weak": 0.4, "grs": 12.5}
RULES = ("sequential", "clustered", "snake", "random", "least_manhattan",
         "nmap_greedy", "heaviest_first")


def spearman(a, b):
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        for rank, i in enumerate(order):
            r[i] = rank
        return r
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb)


def booksim_cycles(W, pi):
    """Per-boundary BookSim cycles at the volume scale (bandwidth-free)."""
    out = []
    for name, fl in pr.boundary_flows(W, pi):
        pk = [(s, d, bb.packets_for(w * SCALE)) for s, d, w in fl if w > 0]
        r = bb.run_batch(pk, k=6)
        out.append((name, r["cycles"], sum(p for _, _, p in pk),
                    {k: r[k] for k in ("packet_latency_avg", "network_latency_avg",
                                       "flit_latency_avg", "hops_avg") if k in r}))
    return out


def main():
    W = pr.shrunk_workload()
    n_slots = W.fab.level("die").per_parent
    cands = {n: sb.generate(n, W, seed=0) for n in RULES}
    for s in (1, 2, 3, 4):
        cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
    # SA winners on this instance
    for cell, bw in CELLS.items():
        starts = {n: cands[n] for n in sl.SEATING_SEEDS}
        rungs = {n: se.score(p, W, caliber="single", d2d_gbps=bw).t_opt_s
                 for n, p in starts.items()}
        t0 = (max(rungs.values()) - min(rungs.values())) / 20.0
        sched = sa.Schedule(t0=t0, alpha=0.996, steps=1200)
        for i, name in enumerate(sorted(starts)):
            if cell == "grs" and name != "random":
                continue
            J = sl.SessionJ(W, starts[name], "t", bw)
            r = sa.anneal(J, starts[name], n_slots, sched, seed=i)
            cands[f"sa_{cell}_from_{name}"] = r.best_pi
    print(f"{len(cands)} candidates; BookSim per candidate ...")

    rows = {}
    for name, pi in cands.items():
        t = time.perf_counter()
        cyc = booksim_cycles(W, pi)
        rows[name] = {"booksim": [{"boundary": b, "cycles": c, "packets": p, **st}
                                  for b, c, p, st in cyc],
                      "booksim_cycles_total": sum(c for _, c, _, _ in cyc),
                      "pi": pi.to_json(),
                      "booksim_wall_s": time.perf_counter() - t, "cells": {}}
        for cell, bw in CELLS.items():
            sc = se.score(pi, W, caliber="single", d2d_gbps=bw)
            d = sc.per_phase["prefill"]["decomp"]
            cycle_s = (bb.FLIT_PAYLOAD_B / SCALE) / (bw * 1e9)
            h_book = rows[name]["booksim_cycles_total"] * cycle_s
            rows[name]["cells"][cell] = {
                "ours_T_s": sc.t_opt_s, "ours_H_s": d["d2d_serial_s"],
                "layers_s": d["layers_s"], "prop_s": d["propagation_s"],
                "booksim_H_s": h_book,
                "booksim_T_s": d["layers_s"] + d["propagation_s"] + h_book,
                "booksim_over_ours_H": h_book / d["d2d_serial_s"]}
        print(f"  {name:22} BookSim {rows[name]['booksim_cycles_total']:8d} cyc "
              f"({rows[name]['booksim_wall_s']:.0f} s) | weak ours "
              f"{rows[name]['cells']['weak']['ours_T_s']*1e3:7.2f} ms, BookSim "
              f"{rows[name]['cells']['weak']['booksim_T_s']*1e3:7.2f} ms, "
              f"H ratio {rows[name]['cells']['weak']['booksim_over_ours_H']:.3f}")

    out = {"note": __doc__.strip(), "scale": SCALE, "grid": "6x6, 34 dies",
           "layers": W.cfg.n_layers, "rows": rows, "cells": {}}
    for cell in CELLS:
        names = list(rows)
        ours = [rows[n]["cells"][cell]["ours_T_s"] for n in names]
        book = [rows[n]["cells"][cell]["booksim_T_s"] for n in names]
        ratios = [rows[n]["cells"][cell]["booksim_over_ours_H"] for n in names]
        rnd = [n for n in names if n == "random" or n.startswith("random_s")]
        strongest = min(rnd, key=lambda n: rows[n]["cells"][cell]["ours_T_s"])
        winners = [n for n in names if n.startswith(f"sa_{cell}_")]
        best_sa = min(winners, key=lambda n: rows[n]["cells"][cell]["ours_T_s"])
        g_ours = 1 - rows[best_sa]["cells"][cell]["ours_T_s"] / rows[strongest]["cells"][cell]["ours_T_s"]
        g_book = 1 - rows[best_sa]["cells"][cell]["booksim_T_s"] / rows[strongest]["cells"][cell]["booksim_T_s"]
        out["cells"][cell] = {
            "spearman_T": spearman(ours, book),
            "top1_ours": names[ours.index(min(ours))],
            "top1_booksim": names[book.index(min(book))],
            "H_ratio_min": min(ratios), "H_ratio_max": max(ratios),
            "bound_holds_everywhere": min(ratios) >= 1.0,
            "strongest_random_under_ours": strongest,
            "sa_winner_under_ours": best_sa,
            "pair_gain_ours_pct": g_ours * 100,
            "pair_gain_booksim_pct": g_book * 100,
            "pair_sign_agrees": (g_ours > 0) == (g_book > 0)}
        c = out["cells"][cell]
        print(f"[{cell}] Spearman(T) {c['spearman_T']:.3f}; top-1 ours "
              f"{c['top1_ours']} / BookSim {c['top1_booksim']}; H ratio "
              f"{c['H_ratio_min']:.3f}..{c['H_ratio_max']:.3f} (bound holds: "
              f"{c['bound_holds_everywhere']}); PAIR {best_sa} vs {strongest}: "
              f"gain ours {c['pair_gain_ours_pct']:.3f}% / BookSim "
              f"{c['pair_gain_booksim_pct']:.3f}% (sign agrees: "
              f"{c['pair_sign_agrees']})")
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
