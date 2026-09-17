"""S8 / notes section 7: same-budget objective ablation on the real 2.7B
mapping instance (24x24, 0.4 GB/s, kappa 1 and 4). Same searcher, same
start (random seed 0), same 3 seeds, same budget (1200 steps, alpha
0.996, t0 = the declared 20 ms for ours and, for each proxy, 20 ms
scaled by its rung span over ours' rung span -- the same relative
temperature). Objectives:
  ours        T_single (busiest resource over links AND ports, per
              boundary, summed; the evaluator's own latency)
  wire_only   the same with ports ignored (contention on ports unpriced)
  word_hops   sum over flows of words x hops (the distance / total-
              traffic proxy; E1's caliber on this instance)
  max_hops    sum over boundaries of the longest hop count (propagation
              only; contention ignored entirely)
Every endpoint is re-scored under ours (single) and under the pipe II,
and set beside the strongest baseline; regret = endpoint T / the
ours-endpoint T. Also the serial -> pipe contrast from S8-B is kept.

    python3 scripts/objective_ablation.py -> analysis/objective_ablation.json
"""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import kappa_geometry_sweep as kg
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_linkage as sl
from scripts import search_sa as sa

KAPPAS = tuple(float(x) for x in os.environ.get("ABL_KAPPAS", "1,4").split(","))
_SFX = "" if KAPPAS == (1.0, 4.0) else "_k" + "_".join(f"{k:g}" for k in KAPPAS)
OUT = os.path.join(se.A, f"objective_ablation{_SFX}.json")
BW = 0.4
SEEDS = (0, 1, 2)
STEPS, ALPHA = 1200, 0.996


class ProxyJ:
    """Full-recompute proxies (cheap enough: flows are rebuilt per call)."""

    def __init__(self, W, kind, kappa):
        self.W, self.kind, self.kappa = W, kind, kappa

    def __call__(self, pi):
        fls = kg.flows_by_boundary(self.W, pi)
        icl = self.W.die_ic
        if self.kind == "wire_only":
            return sum(se.busiest_link_words(fl, icl, ports=False) for fl in fls)
        if self.kind == "word_hops":
            return sum(f["volume"] * f["width"] * icl.hops(*f["nodes"])
                       for fl in fls for f in fl)
        if self.kind == "max_hops":
            return sum(max(icl.hops(*f["nodes"]) for f in fl) for fl in fls)
        raise ValueError(self.kind)


def main():
    W = kg.workload((24, 24))
    n_slots = W.fab.level("die").per_parent
    out = {"note": __doc__.strip(), "bw_gbps": BW, "cells": {}}
    for kappa in KAPPAS:
        W.port_ratio = kappa
        cands = {n: sb.generate(n, W, seed=0) for n in kg.RULES}
        for s in (1, 2, 3, 4):
            cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
        base = list(cands)
        objectives = {"ours": lambda pi0: sl.SessionJ(W, pi0, "t", BW),
                      "wire_only": lambda pi0: ProxyJ(W, "wire_only", kappa),
                      "word_hops": lambda pi0: ProxyJ(W, "word_hops", kappa),
                      "max_hops": lambda pi0: ProxyJ(W, "max_hops", kappa)}
        runs = {}
        JT = objectives["ours"](cands["random"])
        spanT = max(JT(cands[n]) for n in kg.RULES) - min(JT(cands[n]) for n in kg.RULES)
        for name, mk in objectives.items():
            J0 = mk(cands["random"])
            rungs = {n: J0(cands[n]) for n in kg.RULES}
            # the declared 20 ms for ours; every proxy at the SAME relative
            # temperature: t0 scaled by its rung span over ours' rung span
            t0 = sl.SEATING_SCHED[BW].t0 * (max(rungs.values()) - min(rungs.values())) / spanT
            sched = sa.Schedule(t0=t0, alpha=ALPHA, steps=STEPS)
            for s in SEEDS:
                J = mk(cands["random"])
                r = sa.anneal(J, cands["random"], n_slots, sched, seed=104729 * s + 7)
                key = f"{name}_s{s}"
                cands[key] = r.best_pi
                runs[key] = {"objective": name, "sa_seed": s, "t0": t0,
                             "start_j": r.start_j, "best_j": r.best_j, "accepted": r.accepted,
                             "best_pi": r.best_pi.to_json()}
        rows = {}
        for n, pi in cands.items():
            sc = se.score(pi, W, caliber="single", d2d_gbps=BW)
            d = sc.per_phase["prefill"]["decomp"]
            rows[n] = {"T_single_s": sc.t_opt_s, "II_pipe_s": d["t_pipe_interval_s"]}
        T = {n: rows[n]["T_single_s"] for n in cands}
        II = {n: rows[n]["II_pipe_s"] for n in cands}
        sb_single = min(base, key=lambda n: T[n])
        sb_pipe = min(base, key=lambda n: II[n])
        best_ours = min([n for n in cands if n.startswith("ours_")], key=lambda n: T[n])
        cell = {"strongest_baseline_single": sb_single, "strongest_baseline_pipe": sb_pipe,
                "rows": rows, "runs": runs, "per_objective": {}}
        print(f"[kappa {kappa:g}] strongest baseline single {sb_single} {T[sb_single]*1e3:.1f} ms; "
              f"ours endpoint {best_ours} {T[best_ours]*1e3:.1f} ms")
        print(f"   {'objective':10} {'T best (ms)':>11} {'median':>8} {'regret vs ours':>14} "
              f"{'gain vs strongest':>17} {'loss avoided by ours':>20} {'II gain':>8}")
        for name in objectives:
            ends = [n for n in cands if n.startswith(f"{name}_s")]
            Ts = [T[n] for n in ends]
            best = min(ends, key=lambda n: T[n])
            cell["per_objective"][name] = {
                "endpoints": ends, "T_best_s": min(Ts), "T_median_s": statistics.median(Ts),
                "T_max_s": max(Ts), "regret_vs_ours": T[best] / T[best_ours],
                "gain_vs_strongest_pct": (1 - T[best] / T[sb_single]) * 100,
                "loss_avoided_by_ours_pct": (T[best] / T[best_ours] - 1) * 100,
                "II_gain_vs_strongest_pct": (1 - min(II[n] for n in ends) / II[sb_pipe]) * 100}
            c = cell["per_objective"][name]
            print(f"   {name:10} {c['T_best_s']*1e3:11.1f} {c['T_median_s']*1e3:8.1f} "
                  f"{c['regret_vs_ours']:14.4f} {c['gain_vs_strongest_pct']:16.2f}% "
                  f"{c['loss_avoided_by_ours_pct']:19.2f}% {c['II_gain_vs_strongest_pct']:7.2f}%")
        out["cells"][f"k{kappa:g}"] = cell
        del W.port_ratio
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
