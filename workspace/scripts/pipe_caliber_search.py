"""S8-B: the existing pipe caliber as a search objective. What it is:
t_pipe = max over segments of (segment layers x layer_s + the segment's
own hand-off sum) -- a steady-state initiation-interval estimate, no
fill/drain, no cross-segment resource sharing, cut fee zero; every
generated seating carries 32 single-layer segments (the fixed pipeline
strategy this round). Throughput = 1/II. Cells: 24x24 at kappa 1 and 4,
0.4 GB/s. Per cell: baselines under both calibers; the serial-selected
endpoints (S8-A) re-scored in pipe; a pipe-objective search (3 seeds from
random); cross-scoring; timing.

    python3 scripts/pipe_caliber_search.py -> analysis/pipe_caliber_search.json
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import kappa_geometry_sweep as kg
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_linkage as sl
from scripts import search_sa as sa
from scripts import search_space as ss

OUT = os.path.join(se.A, "pipe_caliber_search.json")
KAPPAS = (1.0, 4.0)
BW = 0.4
SEEDS = (0, 1, 2)
STEPS, ALPHA = 1200, 0.996


def both(W, pi):
    s = se.score(pi, W, caliber="single", d2d_gbps=BW)
    d = s.per_phase["prefill"]["decomp"]
    return {"T_single_s": s.t_opt_s, "II_pipe_s": d["t_pipe_interval_s"],
            "throughput_per_s": 1.0 / d["t_pipe_interval_s"],
            "n_segments": len(d["stage_s"]),
            "busiest_stage_index": max(range(len(d["stage_s"])), key=lambda k: d["stage_s"][k])}


def spearman(a, b):
    def rk(x):
        o = sorted(range(len(x)), key=lambda i: x[i])
        r = [0] * len(x)
        for k, i in enumerate(o):
            r[i] = k
        return r
    ra, rb = rk(a), rk(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    return (sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
            / ((sum((x - ma) ** 2 for x in ra) ** 0.5) * (sum((y - mb) ** 2 for y in rb) ** 0.5)))


def main():
    W = kg.workload((24, 24))
    n_slots = W.fab.level("die").per_parent
    sweep = json.load(open(os.path.join(se.A, "kappa_geometry_sweep.json")))["cells"]
    out = {"note": __doc__.strip(), "bw_gbps": BW, "cells": {}}
    for kappa in KAPPAS:
        W.port_ratio = kappa
        cands = {n: sb.generate(n, W, seed=0) for n in kg.RULES}
        for s in (1, 2, 3, 4):
            cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
        base_names = list(cands)
        serial_ends = {k: ss.Pi.from_json(v["best_pi"])
                       for k, v in sweep[f"24x24/k{kappa:g}"]["runs"].items()}
        cands.update({f"serial_{k}": v for k, v in serial_ends.items()})
        # pipe-objective search
        # the declared 20 ms is for the T_single objective; the pipe
        # objective is rescaled by the ratio of the rung spans so the two
        # searches run at the same relative temperature
        rT = {n: both(W, cands[n])["T_single_s"] for n in kg.RULES}
        rP = {n: both(W, cands[n])["II_pipe_s"] for n in kg.RULES}
        t0 = sl.SEATING_SCHED[BW].t0 * ((max(rP.values()) - min(rP.values()))
                                       / (max(rT.values()) - min(rT.values())))
        sched = sa.Schedule(t0=t0, alpha=ALPHA, steps=STEPS)
        runs, step_t = {}, []
        for s in SEEDS:
            J = sl.SessionJ(W, cands["random"], "t", BW, caliber="pipe")
            t = time.perf_counter()
            r = sa.anneal(J, cands["random"], n_slots, sched, seed=7919 * s + 5)
            dt = time.perf_counter() - t
            runs[f"pipe_random_s{s}"] = {"start_II": r.start_j, "best_II": r.best_j,
                                         "accepted": r.accepted, "wall_s": dt,
                                         "ms_per_step": dt / STEPS * 1e3,
                                         "best_pi": r.best_pi.to_json()}
            cands[f"pipe_random_s{s}"] = r.best_pi
        rows = {n: both(W, pi) for n, pi in cands.items()}
        T = {n: rows[n]["T_single_s"] for n in cands}
        II = {n: rows[n]["II_pipe_s"] for n in cands}
        sb_single = min(base_names, key=lambda n: T[n])
        sb_pipe = min(base_names, key=lambda n: II[n])
        ser = [n for n in cands if n.startswith("serial_")]
        pip = [n for n in cands if n.startswith("pipe_")]
        best_ser_single = min(ser, key=lambda n: T[n])
        best_ser_pipe = min(ser, key=lambda n: II[n])
        best_pip_pipe = min(pip, key=lambda n: II[n])
        best_pip_single = min(pip, key=lambda n: T[n])
        cell = {"t0_pipe_s": t0, "rows": rows, "runs": runs,
                "strongest_baseline_single": sb_single, "strongest_baseline_pipe": sb_pipe,
                "spearman_single_vs_pipe_over_baselines": spearman(
                    [T[n] for n in base_names], [II[n] for n in base_names]),
                "serial_endpoints_in_pipe": {
                    "best_by_pipe": best_ser_pipe,
                    "gain_pipe_vs_strongest_pct": (1 - II[best_ser_pipe] / II[sb_pipe]) * 100,
                    "gain_single_vs_strongest_pct": (1 - T[best_ser_single] / T[sb_single]) * 100},
                "pipe_endpoints": {
                    "best": best_pip_pipe,
                    "gain_pipe_vs_strongest_pct": (1 - II[best_pip_pipe] / II[sb_pipe]) * 100,
                    "throughput_gain_pct": (II[sb_pipe] / II[best_pip_pipe] - 1) * 100,
                    "II_spread_pct": (max(II[n] for n in pip) / min(II[n] for n in pip) - 1) * 100,
                    "cross_scored_single_gain_vs_strongest_pct": (1 - T[best_pip_single] / T[sb_single]) * 100},
                "selection_same_seating": cands[best_ser_pipe].seat == cands[best_pip_pipe].seat,
                "ms_per_pipe_step_median": statistics.median(v["ms_per_step"] for v in runs.values())}
        out["cells"][f"k{kappa:g}"] = cell
        c = cell
        print(f"[kappa {kappa:g}] strongest baseline: single {sb_single} ({T[sb_single]*1e3:.1f} ms), "
              f"pipe {sb_pipe} (II {II[sb_pipe]*1e3:.2f} ms); Spearman(single, pipe) over 11 baselines "
              f"{c['spearman_single_vs_pipe_over_baselines']:.3f}")
        print(f"   serial endpoints: single gain {c['serial_endpoints_in_pipe']['gain_single_vs_strongest_pct']:.2f}% | "
              f"re-scored in pipe: gain {c['serial_endpoints_in_pipe']['gain_pipe_vs_strongest_pct']:.2f}% ({best_ser_pipe})")
        print(f"   pipe endpoints (3 seeds): II gain {c['pipe_endpoints']['gain_pipe_vs_strongest_pct']:.2f}% "
              f"(throughput +{c['pipe_endpoints']['throughput_gain_pct']:.2f}%), spread {c['pipe_endpoints']['II_spread_pct']:.2f}%; "
              f"cross-scored in single: gain {c['pipe_endpoints']['cross_scored_single_gain_vs_strongest_pct']:.2f}%; "
              f"same seating as best serial endpoint: {c['selection_same_seating']}; "
              f"{c['ms_per_pipe_step_median']:.2f} ms per pipe step")
        print(f"   busiest stage of the strongest pipe baseline: layer {rows[sb_pipe]['busiest_stage_index']}; "
              f"II / (T_single/32) = {II[sb_pipe] / (T[sb_pipe] / 32):.3f}")
        del W.port_ratio
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
