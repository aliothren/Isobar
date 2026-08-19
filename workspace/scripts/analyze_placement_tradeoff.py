"""Energy and latency do NOT rank placements the same way.

The scheme/layout sweep (analyze_contention_impact.py) answers "how much does
contention move the latency". It cannot answer the question that actually
decides a floorplan: does the cheapest layout also happen to be the fastest?

The two costs are driven by DIFFERENT statistics of the same routed traffic:

    energy  ~ SUM over flows of volume x distance      -> mean hub-to-node hops
    latency ~ MAX over resources of volume / bandwidth -> peak link occupancy

A design that spreads traffic over many short wires and one that funnels it
down a few long ones can trade places between those two. This script measures
both for every (scheme, layout) from ONE mapper run and plots them together:

  1. energy-vs-latency scatter with the Pareto front -- the trade-off, if any.
  2. per-link load distribution -- the whole vector behind each point, which
     is where the SUM/MAX divergence physically lives.

Energy is the full system energy with the router term re-priced by the
variant's mean hops (placement_aware.position_aware_cost), so the y axis has a
real denominator instead of a comm-only ratio.

REGIME NOTE: bandwidth (DR-2) and reference_hops (DR-4) are placeholders. The
ORDERING and the SPREAD between variants are the result.

Usage (container): python3 scripts/analyze_placement_tradeoff.py
"""
import dataclasses
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import scripts.crossbar_comm as cc
from scripts import fabric as fabric_mod
from scripts import interconnect as ic
from scripts import llm_workload as lw
from scripts import mlx_system as mlx
from scripts import placement as placement_mod
from scripts import placement_aware as pa

OUT = "/home/workspace/analysis"
BW_POINT = 16384.0

# (key, topology, params, mesh, pretty label)
VARIANTS = [
    ("star/3x3",     "star",   {},                                  None,   "star, 3x3"),
    ("mesh/3x3c",    "mesh",   {"routing": "xy", "hub": "center"},  None,   "mesh, 3x3 centre"),
    ("mesh/3x3corner", "mesh", {"routing": "xy", "hub": "corner"},  None,   "mesh, 3x3 corner"),
    ("mesh/2x4c",    "mesh",   {"routing": "xy", "hub": "center"},  (2, 4), "mesh, 2x4 centre"),
    ("htree/3x3",    "h_tree", {"branching": 4},                    None,   "h-tree k=4"),
    ("bus/centre",   "bus",    {"driver": "center"},                None,   "bus, centre driver"),
    ("bus/corner",   "bus",    {"driver": "corner"},                None,   "bus, corner driver"),
]

# `star` is an idealized switch with unlimited internal bandwidth: it is the
# CONTENTION LOWER BOUND, not a realizable design at this radix (its area /
# wiring cost is not modelled here). Keep it on the plot as the bound, but do
# not let it define the Pareto front for the realizable schemes.
IDEALIZED = {"star/3x3"}


def variant(base, topology, params, bw, mesh=None):
    levels = []
    for lv in base.levels:
        if lv.name == "macro":
            lv = dataclasses.replace(
                lv, mesh=mesh or lv.mesh,
                link=dataclasses.replace(lv.link, topology=topology,
                                         params=params,
                                         bandwidth_words_per_cycle=bw))
        levels.append(lv)
    return dataclasses.replace(base, name="variant", levels=levels).validate()


def main():
    base = fabric_mod.default()
    print("running ffn1 (prefill, S=512) once ...", flush=True)
    r = lw.run_op(lw.Op("ffn1", "static", P=512, C=1024, M=4096), phase="prefill")
    res = r["result"]
    flows, _, _, _ = cc.build_flows(res.output_dir, verbose=False)
    cyc = res.cycle_seconds
    compute, write, prop = (r["compute_latency_s"], r["write_latency_s"],
                            r["dist_latency_s"])
    unit = flows[0]["volume"]
    stall_free = write + compute + prop
    print(f"  compute {compute*1e3:.3f} ms | one macro edge = {unit/1e6:.1f} M words")
    print(f"  system energy (position-blind) {res.energy*1e3:.4f} mJ\n")

    rows = []
    for key, topo, params, mesh, label in VARIANTS:
        fab = variant(base, topo, params, BW_POINT, mesh)
        pl = placement_mod.sequential_fill(fab)

        # --- latency side: peak resource occupancy
        occ = cc.link_occupancy(flows, fab, cyc, pl)
        lat = write + max(compute, occ["serialization_s"]) + prop
        macro_links = [e for e in occ["per_link"] if e["resource"].startswith("macro/")]
        loads = sorted((e["volume"] / unit for e in macro_links), reverse=True)

        # --- energy side: router term re-priced by THIS variant's mean hops
        cost = pa.position_aware_cost(r["levels"], mlx.LAYOUT,
                                      placement=pl, fabric=fab)
        energy = res.energy - cost["baseline"] + cost["position_aware"]
        mh = ic.build(fab, "macro", pl).mean_hops()

        rows.append({"key": key, "label": label, "mean_hops": mh,
                     "peak_x": max(loads) if loads else 0.0,
                     "sum_x": sum(loads), "n_links": len(loads),
                     "loads_x": loads,
                     "router_ratio": cost["ratio"],
                     "energy_J": energy, "energy_rel": energy / res.energy,
                     "latency_s": lat, "latency_rel": lat / stall_free})
        print(f"{label:22} mean_hops {mh:5.3f} | peak {max(loads) if loads else 0:4.1f}x"
              f" | sum {sum(loads):5.1f}x over {len(loads):2d} wires"
              f" | E {energy*1e3:8.4f} mJ ({energy/res.energy:5.3f}x)"
              f" | L {lat*1e3:7.2f} ms ({lat/stall_free:5.2f}x)")

    # ---------- Pareto front (minimise both)
    real = [d for d in rows if d["key"] not in IDEALIZED]

    def dominated(a):
        return any(b["energy_J"] <= a["energy_J"] and b["latency_s"] <= a["latency_s"]
                   and (b["energy_J"] < a["energy_J"] or b["latency_s"] < a["latency_s"])
                   for b in real)
    for d in rows:
        d["pareto"] = d["key"] not in IDEALIZED and not dominated(d)

    # how flat is the energy axis compared with the latency axis?
    es = [d["energy_J"] for d in rows]
    ls = [d["latency_s"] for d in rows]
    print(f"\n  energy  spread across all variants: {max(es)/min(es):.3f}x")
    print(f"  latency spread across all variants: {max(ls)/min(ls):.2f}x")
    ties = {}
    for d in rows:
        ties.setdefault(round(d["energy_J"], 12), []).append(d)
    for e, g in sorted(ties.items()):
        if len(g) > 1:
            lo = min(g, key=lambda d: d["latency_s"])
            hi = max(g, key=lambda d: d["latency_s"])
            print(f"  IDENTICAL energy ({e*1e3:.4f} mJ) for "
                  f"{', '.join(d['label'] for d in g)} -- latency spans "
                  f"{hi['latency_s']/lo['latency_s']:.2f}x "
                  f"({lo['latency_s']*1e3:.2f} -> {hi['latency_s']*1e3:.2f} ms)")
    print("\nPareto-optimal (no variant beats them on both):",
          ", ".join(d["label"] for d in rows if d["pareto"]))

    # rank disagreement
    by_e = [d["key"] for d in sorted(rows, key=lambda d: d["energy_J"])]
    by_l = [d["key"] for d in sorted(rows, key=lambda d: d["latency_s"])]
    print(f"  energy ranking : {' < '.join(by_e)}")
    print(f"  latency ranking: {' < '.join(by_l)}")

    base_comm = pa.position_aware_cost(
        r["levels"], mlx.LAYOUT,
        placement=placement_mod.sequential_fill(variant(base, "star", {}, BW_POINT)),
        fabric=variant(base, "star", {}, BW_POINT))["baseline"]

    # ---------- figure 1: energy vs latency
    fig, ax = plt.subplots(figsize=(8.4, 5.6))
    front = sorted([d for d in rows if d["pareto"]], key=lambda d: d["latency_s"])
    if len(front) > 1:
        ax.plot([d["latency_s"] * 1e3 for d in front],
                [d["energy_J"] * 1e3 for d in front],
                "-", color="0.6", lw=1.4, zorder=1, label="Pareto front")
    # the whole point: variants that cost the SAME energy, far apart in latency
    for e, g in ties.items():
        if len(g) < 2:
            continue
        lo = min(g, key=lambda d: d["latency_s"])
        hi = max(g, key=lambda d: d["latency_s"])
        ax.plot([lo["latency_s"] * 1e3, hi["latency_s"] * 1e3],
                [e * 1e3, e * 1e3], "--", color="#d1495b", lw=1.2, zorder=2)
        ax.annotate(f"same energy, {hi['latency_s']/lo['latency_s']:.2f}x latency",
                    (lo["latency_s"] * 1e3, e * 1e3),
                    textcoords="offset points", xytext=(14, -15), fontsize=8.5,
                    color="#d1495b", ha="left")
    for d in rows:
        ax.plot(d["latency_s"] * 1e3, d["energy_J"] * 1e3, "o", ms=11, zorder=3,
                mfc="#2a9d8f" if d["pareto"] else "#dfe6ee", mec="k", mew=1.1)
        ax.annotate(d["label"], (d["latency_s"] * 1e3, d["energy_J"] * 1e3),
                    textcoords="offset points", xytext=(9, 5), fontsize=9)
    ax.set_xscale("log")
    ax.set_xlim(min(d["latency_s"] for d in rows) * 1e3 * 0.82,
                max(d["latency_s"] for d in rows) * 1e3 * 1.75)
    ax.set_xlabel("op latency (ms)   -- set by PEAK link occupancy")
    ax.set_ylabel("system energy (mJ)   -- set by MEAN hop count")
    sec = ax.secondary_yaxis(
        "right", functions=(lambda y: (y * 1e-3 - res.energy + base_comm) / base_comm,
                            lambda y: (y * base_comm + res.energy - base_comm) * 1e3))
    sec.set_ylabel("router-level ratio (the level the change acts on)", fontsize=9)
    ax.set_title("The energy account cannot see the axis that moves latency 8x\n"
                 "ffn1 prefill S=512; filled = Pareto-optimal among realizable "
                 "schemes", fontsize=11)
    ax.grid(alpha=0.3, which="both")
    if len(front) > 1:
        ax.legend(fontsize=9, loc="best")
    plt.figtext(0.5, 0.012,
                "star is the contention LOWER BOUND (idealized switch, area not "
                "modelled), shown as a reference, not as a design.",
                ha="center", fontsize=8, color="0.35")
    p1 = os.path.join(OUT, "placement_energy_latency.png")
    plt.tight_layout(rect=[0, 0.045, 1, 1]); plt.savefig(p1, dpi=130); plt.close()
    print(f"PNG -> {p1}")

    # ---------- figure 2: per-link load distribution
    fig, ax = plt.subplots(figsize=(9.2, 5.2))
    n = len(rows)
    for i, d in enumerate(rows):
        loads = d["loads_x"]
        xs = [i + (j - (len(loads) - 1) / 2) * (0.72 / max(len(loads), 1))
              for j in range(len(loads))]
        w = 0.72 / max(len(loads), 1) * 0.85
        top = max(loads)
        ax.bar(xs, loads, w, color=["#d1495b" if v == top else "#8fa8bf"
                                    for v in loads])
        ax.text(i, max(loads) + 0.35, f"max {max(loads):.0f}x", ha="center",
                fontsize=9, color="#d1495b", fontweight="bold")
        ax.text(i, -0.9, f"{len(loads)} wire{'s' if len(loads) != 1 else ''}\n"
                          f"mean hops {d['mean_hops']:.2f}",
                ha="center", fontsize=8, color="0.4")
    ax.set_xticks(range(n))
    ax.set_xticklabels([d["label"] for d in rows], fontsize=9, rotation=12)
    ax.set_ylabel("traffic on one wire  (in units of one macro's edge)")
    ax.set_ylim(-1.6, max(max(d["loads_x"]) for d in rows) * 1.22)
    ax.set_title("Latency reads the tallest bar; energy reads the mean hop count\n"
                 "red = the wire that sets the latency; grey = idle capacity",
                 fontsize=11)
    ax.grid(alpha=0.25, axis="y")
    plt.figtext(0.5, 0.012,
                "Variants with the same mean hop count cost the same energy no "
                "matter how unevenly their traffic piles up.",
                ha="center", fontsize=8, color="0.35")
    p2 = os.path.join(OUT, "placement_link_loads.png")
    plt.tight_layout(rect=[0, 0.045, 1, 1]); plt.savefig(p2, dpi=130); plt.close()
    print(f"PNG -> {p2}")

    with open(os.path.join(OUT, "placement_tradeoff.json"), "w") as f:
        json.dump({"operating_point_words_per_cycle": BW_POINT,
                   "stall_free_latency_s": stall_free,
                   "position_blind_energy_J": res.energy,
                   "macro_edge_words": unit,
                   "energy_rank": by_e, "latency_rank": by_l,
                   "variants": rows}, f, indent=1)
    print("JSON -> placement_tradeoff.json")


if __name__ == "__main__":
    main()
