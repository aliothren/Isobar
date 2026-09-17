"""S8-A: port-capacity ratio kappa x package geometry, six cells.
See the FIXLIST pre-registration (S8-A) for the protocol.

    python3 scripts/kappa_geometry_sweep.py -> analysis/kappa_geometry_sweep.json + .png
"""
import dataclasses as dc
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import llm_workload as lw
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_linkage as sl
from scripts import search_sa as sa

OUT = os.path.join(se.A, "kappa_geometry_sweep.json")
PNG = os.path.join(se.A, "kappa_geometry_sweep.png")
GRIDS = ((24, 24), (12, 48))
KAPPAS = (1.0, 2.0, 4.0)
BWS = (0.4, 12.5)
RULES = ("sequential", "clustered", "snake", "random", "least_manhattan",
         "nmap_greedy", "heaviest_first")
STARTS = ("clustered", "random", "snake")
SEEDS = (0, 1, 2)
STEPS, ALPHA = 1200, 0.996


def workload(grid):
    W0 = se.Workload2p7B()
    levels = [dc.replace(l, mesh=tuple(grid)) if l.name == "die" else l
              for l in W0.fab.levels]
    return se.Workload2p7B(fabric=dc.replace(W0.fab, name=f"mesh{grid[0]}x{grid[1]}",
                                             levels=levels).validate())


def flows_by_boundary(W, pi, phase="prefill"):
    base = lw.block_chain(W.cfg, W.S, phase, on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    chain, seating = [], {}
    for li in range(W.cfg.n_layers):
        for e in base:
            n = f"{e['name']}@L{li}"
            chain.append({**e, "name": n})
            seating[n] = list(pi.seat[n])
    fb = lw.block_die_flows(chain, seating, W.fab)
    return [fb[e["name"]] for e in chain[1:]]


def terms(W, pi, kappa):
    """(A with ports/kappa, wire-only A, port floor / kappa) in words."""
    fls = flows_by_boundary(W, pi)
    a = sum(se.busiest_link_words(fl, W.die_ic, kappa=kappa) for fl in fls)
    wire = sum(se.busiest_link_words(fl, W.die_ic, ports=False) for fl in fls)
    floor = 0.0
    for fl in fls:
        inj, ej = {}, {}
        for f in fl:
            w = f["volume"] * f["width"]
            inj[f["nodes"][0]] = inj.get(f["nodes"][0], 0.0) + w
            ej[f["nodes"][1]] = ej.get(f["nodes"][1], 0.0) + w
        floor += max(max(inj.values()), max(ej.values())) / kappa
    return a, wire, floor


def binding(a, wire, floor):
    if abs(a - floor) < 1e-9 * a and abs(a - wire) < 1e-9 * a:
        return "port=link"
    if abs(a - floor) < 1e-9 * a:
        return "port"
    if abs(a - wire) < 1e-9 * a:
        return "link"
    return "mixed"


def main():
    out = {"note": __doc__.strip(), "grids": GRIDS, "kappas": KAPPAS, "bws": BWS,
           "cells": {}}
    for grid in GRIDS:
        W = workload(grid)
        n_slots = W.fab.level("die").per_parent
        cands = {n: sb.generate(n, W, seed=0) for n in RULES}
        for s in (1, 2, 3, 4):
            cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
        for kappa in KAPPAS:
            W.port_ratio = kappa
            key = f"{grid[0]}x{grid[1]}/k{kappa:g}"
            t_cell = time.perf_counter()
            local = dict(cands)
            # the DECLARED schedule of the standing seating legs at 0.4 GB/s
            # (item 4 / search_linkage.SEATING_SCHED): t0 = 20 ms. The S6
            # span/20 rule is NOT used here -- on this instance it is ~4.5x
            # hotter and turns most of the budget into a random walk
            # (recorded in FIXLIST, S8-A superseded).
            t0 = sl.SEATING_SCHED[0.4].t0
            sched = sa.Schedule(t0=t0, alpha=ALPHA, steps=STEPS)
            runs = {}
            for i, start in enumerate(sorted(STARTS)):
                for s in SEEDS:
                    J = sl.SessionJ(W, local[start], "t", 0.4)
                    r = sa.anneal(J, local[start], n_slots, sched, seed=1000003 * s + i)
                    nm = f"sa_{start}_s{s}"
                    local[nm] = r.best_pi
                    runs[nm] = {"start": start, "sa_seed": s, "start_j": r.start_j,
                                "best_j": r.best_j, "accepted": r.accepted,
                                "best_pi": r.best_pi.to_json()}
            rows = {}
            for n, pi in local.items():
                a, wire, floor = terms(W, pi, kappa)
                row = {"A_words": a, "wire_only_words": wire, "floor_words": floor,
                       "A_over_floor": a / floor, "binding": binding(a, wire, floor),
                       "T_s": {}}
                for bw in BWS:
                    row["T_s"][str(bw)] = se.score(pi, W, caliber="single",
                                                   d2d_gbps=bw).t_opt_s
                rows[n] = row
            R = (se.score(local["random"], W, caliber="single", d2d_gbps=1.0)
                 .per_phase["prefill"]["decomp"])
            R_s = R["layers_s"] + R["propagation_s"]
            a_min = min(rows[n]["A_words"] for n in RULES)
            a_max = max(rows[n]["A_words"] for n in RULES)
            base_names = list(RULES) + [f"random_s{s}" for s in (1, 2, 3, 4)]
            ends = [n for n in local if n.startswith("sa_")]
            cell = {"t0_s": t0, "R_s": R_s,
                    "B_minus_gbps": a_min / R_s / 1e9, "B_plus_gbps": a_max / R_s / 1e9,
                    "A_min_rule": min(RULES, key=lambda n: rows[n]["A_words"]),
                    "A_max_rule": max(RULES, key=lambda n: rows[n]["A_words"]),
                    "rows": rows, "runs": runs, "per_bw": {},
                    "wall_s": time.perf_counter() - t_cell}
            for bw in BWS:
                T = {n: rows[n]["T_s"][str(bw)] for n in local}
                strongest = min(base_names, key=lambda n: T[n])
                best_end = min(ends, key=lambda n: T[n])
                e = [T[n] for n in ends]
                cell["per_bw"][str(bw)] = {
                    "strongest_baseline": strongest, "T_strongest_s": T[strongest],
                    "best_endpoint": best_end, "T_best_endpoint_s": T[best_end],
                    "endpoint_min_s": min(e), "endpoint_median_s": statistics.median(e),
                    "endpoint_max_s": max(e),
                    "endpoint_spread_pct": (max(e) / min(e) - 1) * 100,
                    "gain_vs_strongest_pct": (1 - T[best_end] / T[strongest]) * 100,
                    "gain_vs_random_seed0_pct": (1 - T[best_end] / T["random"]) * 100,
                    "endpoint_binding": rows[best_end]["binding"],
                    "endpoint_A_over_floor": rows[best_end]["A_over_floor"]}
            out["cells"][key] = cell
            c4 = cell["per_bw"]["0.4"]
            c12 = cell["per_bw"]["12.5"]
            print(f"[{key}] B- {cell['B_minus_gbps']:.3f} B+ {cell['B_plus_gbps']:.3f} | "
                  f"floor {rows['random']['floor_words']/1e6:.1f}M | strongest@0.4 "
                  f"{c4['strongest_baseline']} ({rows[c4['strongest_baseline']]['binding']}, "
                  f"A/floor {rows[c4['strongest_baseline']]['A_over_floor']:.3f}) | endpoint "
                  f"{c4['best_endpoint']} ({c4['endpoint_binding']}, A/floor "
                  f"{c4['endpoint_A_over_floor']:.3f}) | gain vs strongest 0.4: "
                  f"{c4['gain_vs_strongest_pct']:.2f}%  12.5: {c12['gain_vs_strongest_pct']:.2f}% | "
                  f"endpoints spread {c4['endpoint_spread_pct']:.2f}% | {cell['wall_s']:.0f} s")
        del W.port_ratio
    # the hardware gain of kappa itself, separately
    for grid in GRIDS:
        g = f"{grid[0]}x{grid[1]}"
        ref = out["cells"][f"{g}/k1"]["per_bw"]
        for kappa in KAPPAS[1:]:
            c = out["cells"][f"{g}/k{kappa:g}"]
            c["hardware_gain_of_kappa_pct"] = {
                bw: (1 - c["per_bw"][bw]["T_strongest_s"] / ref[bw]["T_strongest_s"]) * 100
                for bw in ("0.4", "12.5")}
            print(f"  hardware gain of kappa={kappa:g} on {g} (best baseline vs kappa=1): "
                  f"0.4: {c['hardware_gain_of_kappa_pct']['0.4']:.2f}%  12.5: "
                  f"{c['hardware_gain_of_kappa_pct']['12.5']:.2f}%")
    json.dump(out, open(OUT, "w"), indent=1)

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.8))
    for ax, bw in zip(axes, ("0.4", "12.5")):
        for gi, grid in enumerate(GRIDS):
            g = f"{grid[0]}x{grid[1]}"
            ys = [out["cells"][f"{g}/k{k:g}"]["per_bw"][bw]["gain_vs_strongest_pct"]
                  for k in KAPPAS]
            ax.plot(KAPPAS, ys, "-o", label=f"{g}: gain vs strongest baseline")
            ys2 = [out["cells"][f"{g}/k{k:g}"]["per_bw"][bw]["gain_vs_random_seed0_pct"]
                   for k in KAPPAS]
            ax.plot(KAPPAS, ys2, ":", color=ax.lines[-1].get_color(),
                    label=f"{g}: vs random seed 0")
        ax.set_xscale("log", base=2)
        ax.set_xticks(KAPPAS)
        ax.set_xticklabels([f"{k:g}" for k in KAPPAS])
        ax.set_xlabel("port / link capacity ratio κ")
        ax.set_ylabel("whole-model latency reduction (%)")
        ax.set_title(f"{bw} GB/s", fontsize=9)
        ax.grid(alpha=0.2)
        ax.legend(fontsize=6.5)
    fig.suptitle("S8-A: seating-search gain per port ratio and geometry (search per cell, "
                 "3 starts × 3 seeds)", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(PNG, dpi=150)
    print(f"-> {OUT}\n-> {PNG}")


if __name__ == "__main__":
    main()
