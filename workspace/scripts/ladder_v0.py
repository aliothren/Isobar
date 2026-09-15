"""S2 closeout item 5 (C64-c): LADDER TABLE V0 -- the official baseline
readings, spec section 10 S2 ship + the section 6 guardrail's
feasible-seed pool, in one artifact.

Declared table (pre-registered in FIXLIST before the run):
  2.7B class (the A4/S4 payload, frozen per-op account, mu = prefill
  one-hot, singleton cuts as shipped by every generator):
    T_single at three cells -- safe (GRS 12.5 GB/s, device_scale 1),
    weak-D2D (0.4 GB/s, from the standing 4-point anchor set),
    fast-device (12.5 GB/s, device_scale 10, the O17-semantics value);
    plus T_pipe at the safe cell, E (cell-independent: energy carries
    no bandwidth/scale term), d2d_words (the placement-sensitive part).
  355M class (anchor-2 caliber, the stored-example bw):
    avg_hops, busiest_x (boundaries crossing the busiest wire),
    wire_ms, surplus_uJ.
Random rides at seed 0 (declared); every generator is deterministic.

Output: analysis/ladder_v0.json -- the table AND the seed pool (every
baseline's Pi serialized per class; spec section 6: every multi-start
seed set must contain at least one feasible named-baseline solution,
THIS file is that pool). Figure: analysis/ladder_v0.png.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import analyze_d2d as d2d
from scripts import fabric as fabric_mod
from scripts import llm_workload as lw
from scripts import search_baselines as sb
from scripts import search_eval as se

CELLS = (("safe", 12.5, 1.0), ("weak_d2d", 0.4, 1.0), ("fast_dev", 12.5, 10.0))
OUT_JSON = os.path.join(se.A, "ladder_v0.json")
OUT_PNG = os.path.join(se.A, "ladder_v0.png")


def run_2p7b():
    W = se.Workload2p7B()
    rows, pool = {}, {}
    for name in sb.NAMES:
        pi = sb.generate(name, W, seed=0)
        pool[name] = pi.to_json()
        r = {}
        for cell, bw, scale in CELLS:
            sc = se.score(pi, W, caliber="single", d2d_gbps=bw,
                          device_scale=scale)
            r[f"t_single_{cell}_s"] = sc.t_opt_s
            if cell == "safe":
                r["e_J"] = sc.e_J
                d = sc.per_phase["prefill"]["decomp"]
                r["d2d_words"] = d["d2d_words"]
                # the accounting review's column: busiest-link words
                # summed over boundaries / total words (D.4 line (a))
                r["d2d_busiest_words"] = d["d2d_busiest_words"]
                r["busiest_over_total"] = d["d2d_busiest_words"] / d["d2d_words"]
        r["t_pipe_safe_s"] = se.score(pi, W, caliber="pipe",
                                      d2d_gbps=12.5).t_opt_s
        rows[name] = r
    return rows, pool


def run_355m():
    stored = json.load(open(os.path.join(se.A, "d2d_impact.json")))
    base = fabric_mod.from_yaml(d2d.MULTI)
    W = se.Workload355M(d2d.with_link(base, "mesh",
                                      {"routing": "xy", "hub": "center"},
                                      stored["example_bw"]),
                        stored["example_bw"])
    words = stored["S"] * lw.GptConfig().d_model
    rows, pool = {}, {}
    for name in sb.NAMES:
        pi = sb.generate(name, W, seed=0)
        pool[name] = pi.to_json()
        d, occ = W.d2d(pi, "prefill")
        rows[name] = {
            "avg_hops": d["avg_die_hops"],
            "busiest_x": (occ["bottleneck"]["volume"] / words
                          if occ["bottleneck"] else 0.0),
            "wire_ms": occ["serialization_s"] * 1e3,
            "surplus_uJ": d["energy_J"] * 1e6}
    return rows, pool, stored["example_bw"]


def main():
    r27, pool27 = run_2p7b()
    r355, pool355, bw355 = run_355m()

    order = sorted(sb.NAMES, key=lambda n: r27[n]["t_single_safe_s"])
    print("LADDER TABLE V0 -- 2.7B class (sorted by safe-cell T_single)")
    print(f"{'baseline':16} {'T safe(ms)':>11} {'T weak(ms)':>11} "
          f"{'T fast(ms)':>11} {'T pipe(ms)':>11} {'E(J)':>8} {'d2d(Mw)':>9} "
          f"{'busy/tot':>9}")
    for n in order:
        r = r27[n]
        print(f"{n:16} {r['t_single_safe_s']*1e3:11.3f} "
              f"{r['t_single_weak_d2d_s']*1e3:11.2f} "
              f"{r['t_single_fast_dev_s']*1e3:11.3f} "
              f"{r['t_pipe_safe_s']*1e3:11.4f} {r['e_J']:8.4f} "
              f"{r['d2d_words']/1e6:9.1f} {r['busiest_over_total']:9.4f}")
    es = [r27[n]["e_J"] for n in sb.NAMES]
    print(f"E spread (max-min)/min = {(max(es)-min(es))/min(es)*100:.3f}%")
    for cell, _, _ in CELLS:
        ts = [r27[n][f"t_single_{cell}_s"] for n in sb.NAMES]
        print(f"T spread {cell:9}: max/min = {max(ts)/min(ts):.4f}")

    print(f"\nLADDER TABLE V0 -- 355M class (example bw {bw355})")
    print(f"{'baseline':16} {'avg_hops':>9} {'busiest_x':>10} "
          f"{'wire_ms':>9} {'surplus_uJ':>11}")
    for n in sorted(sb.NAMES, key=lambda n: r355[n]["wire_ms"]):
        r = r355[n]
        print(f"{n:16} {r['avg_hops']:9.2f} {r['busiest_x']:10.1f} "
              f"{r['wire_ms']:9.2f} {r['surplus_uJ']:11.2f}")

    json.dump({"note": "ladder table v0 + the section-6 feasible-seed "
                       "pool (C64-c closeout item 5)",
               "quantifier": "observed",
               "evaluation_set": "the 7 named seatings",
               "cells": [{"name": c, "d2d_gbps": b, "device_scale": s}
                         for c, b, s in CELLS],
               "table_2p7b": r27, "table_355m": r355,
               "bw_355m_example": bw355,
               "seed_pool": {"w2p7b": pool27, "w355m": pool355}},
              open(OUT_JSON, "w"), indent=1)
    print(f"\ntable + seed pool -> {OUT_JSON}")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # one baseline order for ALL THREE panels: the 2.7B T ladder
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    x = range(len(order))
    for cell, _, _ in CELLS:
        ts = [r27[n][f"t_single_{cell}_s"] for n in order]
        best = min(ts)
        axes[0].plot(x, [(t / best - 1.0) * 100 for t in ts], marker="o",
                     label=cell)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(order, rotation=35, ha="right", fontsize=8)
    axes[0].set_ylabel("T_single excess over cell best (%)")
    axes[0].set_title("2.7B: the T ladder per cell\n(busiest-link hand-off "
                      "term: seating moves T through link sharing)",
                      fontsize=9)
    axes[0].legend(fontsize=8)
    axes[1].bar(x, [r27[n]["busiest_over_total"] for n in order],
                color="#888")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(order, rotation=35, ha="right", fontsize=8)
    axes[1].set_ylabel("busiest-link words / total words")
    axes[1].set_title("how much of each hand-off stacks on one link\n"
                      "(total words are seat-invariant; this ratio is not)",
                      fontsize=9)
    axes[2].bar(x, [r355[n]["wire_ms"] for n in order], color="#4a7")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(order, rotation=35, ha="right", fontsize=8)
    axes[2].set_ylabel("wire serialization (ms)")
    axes[2].set_title(f"355M: wire time @ {bw355} w/cyc\n(same order: "
                      "the 2.7B T ladder)", fontsize=9)
    fig.suptitle("ladder table v0 (C64-c item 5): the seven named "
                 "baselines, official readings", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    print(f"figure -> {OUT_PNG}")


if __name__ == "__main__":
    main()
