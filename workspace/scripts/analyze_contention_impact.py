"""What changes once contention is modelled: schemes and layouts, in real units.

Contention was added in W1 (a serialization term entering the critical path by
max) and made scheme-aware in W2. On the shipped config no link carries a
bandwidth, so the term is identically zero and nothing moves. This script turns
it ON at a stated operating point and measures what actually changes:

  A -- SAME traffic, SAME layout, four wiring schemes.
  B -- SAME scheme (mesh), three physical layouts.
  C -- where the congestion physically sits (segment load map).

Method: one real mapper run supplies the traffic (ffn1, prefill, S=512); every
scheme/layout/bandwidth combination is re-scored analytically from those same
flows, so the comparison isolates the interconnect and costs one simulation
rather than dozens.

REGIME NOTE: bandwidths are placeholders (DR-2). The MULTIPLIERS between
schemes and between layouts at a given bandwidth are the result; the absolute
latency axis moves with calibration.

Usage (container):
    python3 scripts/analyze_contention_impact.py              # full run
    python3 scripts/analyze_contention_impact.py --maps-only  # segment maps only
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
from scripts import figstyle as fs
from scripts import fabric as fabric_mod
from scripts import interconnect as ic
from scripts import llm_workload as lw
from scripts import placement as placement_mod

OUT = "/home/workspace/analysis"
BW_SWEEP = [float(2 ** k) for k in range(10, 21)]     # words/cycle
BW_POINT = 16384.0                                    # operating point for the table

SCHEMES = [("star", {}, "star (private links)"),
           ("mesh", {"routing": "xy", "hub": "center"}, "mesh (XY routed)"),
           ("h_tree", {"branching": 4}, "h-tree (k=4)"),
           ("bus", {}, "bus (one shared medium)")]

LAYOUTS = [("2x4, glb at centre", {"routing": "xy", "hub": "center"}, None),
           ("2x4, glb at corner", {"routing": "xy", "hub": "corner"}, None),
           ("3x3, glb at centre", {"routing": "xy", "hub": "center"}, (3, 3))]   # comparison: the earlier default


def variant(base, topology, params, bw, mesh=None):
    """base fabric with the MACRO level's scheme / mesh / bandwidth swapped."""
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


def serialization(flows, fab, cyc):
    return cc.link_occupancy(flows, fab, cyc,
                             placement_mod.sequential_fill(fab))


def draw_segment_maps():
    """Pure geometry -- no mapper run needed. The 2x4 pair (the default,
    company-preferred fill-exact layout) is the MAIN figure; the 3x3 pair
    (the earlier default, one empty slot) exists for comparison only (C27)."""
    base = fabric_mod.default()
    figs = [("contention_segment_map.png",
             [("2x4, glb at centre", {"routing": "xy", "hub": "center"}, None),
              ("2x4, glb at corner", {"routing": "xy", "hub": "corner"}, None)]),
            ("contention_segment_map_3x3.png",   # comparison use only
             [("3x3, glb at centre", {"routing": "xy", "hub": "center"}, (3, 3)),
              ("3x3, glb at corner", {"routing": "xy", "hub": "corner"}, (3, 3))])]
    for fname, pair in figs:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
        for ax, (label, params, mesh) in zip(axes, pair):
            fab = variant(base, "mesh", params, BW_POINT, mesh)
            pl = placement_mod.sequential_fill(fab)
            m = ic.build(fab, "macro", pl)
            load = {}
            for i in range(fab.level("macro").per_parent):
                for res in m.path(ic.HUB, i):
                    load[res] = load.get(res, 0) + 1
            peak = max(load.values())
            for res, v in load.items():
                a, b = res.split("seg", 1)[1].split(")-(")
                p = tuple(float(z) for z in a.strip("()").split(","))
                q = tuple(float(z) for z in b.strip("()").split(","))
                ax.plot([p[0], q[0]], [p[1], q[1]], "-", lw=2 + 7 * v / peak,
                        color=plt.cm.YlOrRd(0.25 + 0.7 * v / peak),
                        solid_capstyle="round", zorder=1)
                ax.text((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, f"{v}x",
                        fontsize=9, ha="center", va="center", zorder=3,
                        bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.15))
            for i, sl in enumerate(pl.slots["macro"]):
                ax.plot(sl[0], sl[1], "s", ms=18, mfc="#dfe6ee", mec="k",
                        zorder=2)
                ax.text(sl[0], sl[1], str(i), fontsize=8, ha="center",
                        va="center", zorder=4)
            h = m.hub_coord()
            ax.plot(h[0], h[1], "*", ms=24, color="#1f77b4", zorder=5)
            ax.set_title(f"{label}\nbusiest wire carries {peak} macros' "
                         "traffic", fontsize=10)
            xs = [sl[0] for sl in pl.slots["macro"]] + [h[0]]
            ys = [sl[1] for sl in pl.slots["macro"]] + [h[1]]
            ax.set_xlim(min(xs) - 0.6, max(xs) + 0.6)
            ax.set_ylim(min(ys) - 0.6, max(ys) + 0.6)
            ax.set_aspect("equal"); ax.invert_yaxis(); ax.axis("off")
        fig.suptitle("Where the congestion actually is\n"
                     "die NoC segment load; star = the glb, squares = macros, "
                     "numbers = how many macros' traffic crosses that wire",
                     fontsize=11)
        path = os.path.join(OUT, fname)
        fig.tight_layout(rect=[0, 0, 1, 0.88]); fig.savefig(path, dpi=130)
        plt.close(fig)
        print(f"PNG -> {path}")


def main():
    base = fabric_mod.default()
    print("running ffn1 (prefill, S=512) once for the traffic ...", flush=True)
    r = lw.run_op(lw.Op("ffn1", "static", P=512, C=1024, M=4096), phase="prefill")
    flows, _, _, _ = cc.build_flows(r["output_dir"], verbose=False)
    cyc = r["result"].cycle_seconds
    compute, write, prop = (r["compute_latency_s"], r["write_latency_s"],
                            r["dist_latency_s"])
    unit = flows[0]["volume"]
    print(f"  compute {compute*1e3:.3f} ms | cycle {cyc*1e6:.3f} us | "
          f"{len(flows)} flows | one macro edge = {unit/1e6:.1f} M words\n")

    def latency(ser):
        return write + max(compute, ser) + prop

    stall_free = latency(0.0)
    hdr = (f"{'':24}{'busiest wire':>14}{'serialization':>15}"
           f"{'op latency':>13}{'vs stall-free':>15}")

    def measure(fab):
        occ = serialization(flows, fab, cyc)
        lat = latency(occ["serialization_s"])
        share = occ["bottleneck"]["volume"] / unit if occ["bottleneck"] else 0.0
        return occ, lat, share

    # ------------------------------------------------ A: schemes
    print(f"=== A. same traffic, same layout, different wiring scheme "
          f"(bandwidth {BW_POINT:,.0f} w/c) ===")
    print(hdr)
    A, rowsA = {}, []
    for topo, params, label in SCHEMES:
        occ, lat, share = measure(variant(base, topo, params, BW_POINT))
        rowsA.append({"scheme": topo, "label": label, "busiest_x": share,
                      "serial_s": occ["serialization_s"], "latency_s": lat,
                      "mult": lat / stall_free})
        print(f"{label:24}{share:>13.0f}x{occ['serialization_s']*1e3:>14.2f}ms"
              f"{lat*1e3:>12.2f}ms{lat/stall_free:>14.2f}x")
        A[label] = [latency(serialization(flows, variant(base, topo, params, bw),
                                          cyc)["serialization_s"]) / stall_free
                    for bw in BW_SWEEP]

    # ------------------------------------------------ B: layouts under mesh
    print(f"\n=== B. same scheme (mesh), different physical layout "
          f"(bandwidth {BW_POINT:,.0f} w/c) ===")
    print(hdr)
    B, rowsB = {}, []
    for label, params, mesh in LAYOUTS:
        occ, lat, share = measure(variant(base, "mesh", params, BW_POINT, mesh))
        rowsB.append({"layout": label, "busiest_x": share,
                      "serial_s": occ["serialization_s"], "latency_s": lat,
                      "mult": lat / stall_free})
        print(f"{label:24}{share:>13.0f}x{occ['serialization_s']*1e3:>14.2f}ms"
              f"{lat*1e3:>12.2f}ms{lat/stall_free:>14.2f}x")
        B[label] = [latency(serialization(
            flows, variant(base, "mesh", params, bw, mesh),
            cyc)["serialization_s"]) / stall_free for bw in BW_SWEEP]

    worst = max(rowsB, key=lambda d: d["latency_s"])
    best = min(rowsB, key=lambda d: d["latency_s"])
    print(f"\n  layout alone: {best['layout']} -> {worst['layout']} costs "
          f"{worst['latency_s']/best['latency_s']:.2f}x the op latency")

    # ------------------------------------------------ figures
    def sweep_fig(curves, title, path, note):
        plt.figure(figsize=(7.8, 5.2))
        for labels, ys in fs.group_identical(list(curves.items())):
            line, = plt.plot(BW_SWEEP, ys, "o-", ms=4, label=fs.merged_label(labels))
            if len(labels) > 1:
                k = len(BW_SWEEP) // 3
                plt.annotate(f"{len(labels)} curves identical", (BW_SWEEP[k], ys[k]), textcoords="offset points",
                             xytext=(6, 7), fontsize=6.5, color=line.get_color())
        plt.axvline(BW_POINT, color="0.55", ls=":", lw=1.2)
        plt.xscale("log", base=2); plt.yscale("log")
        plt.xlabel("link bandwidth (words / cycle)  --  PLACEHOLDER axis, DR-2")
        plt.ylabel("op latency  /  stall-free latency")
        plt.title(title, fontsize=11)
        plt.grid(alpha=0.3, which="both"); plt.legend(fontsize=9)
        plt.figtext(0.5, 0.01, note, ha="center", fontsize=8, color="0.35")
        plt.tight_layout(rect=[0, 0.04, 1, 1]); plt.savefig(path, dpi=130)
        plt.close()
        print(f"PNG -> {path}")

    sweep_fig(A, "The wiring scheme decides when the network becomes the bottleneck\n"
                 "(identical traffic, identical layout -- only the network differs)",
              os.path.join(OUT, "contention_by_scheme.png"),
              "1.0 = compute-bound. The knee is where the network takes over: star "
              "shares nothing, bus shares everything. Dotted line = the table's "
              "operating point.")
    sweep_fig(B, "The floorplan decides it too, once contention is modelled\n"
                 "(identical traffic, identical mesh NoC -- only the layout differs)",
              os.path.join(OUT, "contention_by_layout.png"),
              "Moving the glb to a corner, or stretching the die to 2x4, funnels "
              "more macros' traffic onto one wire.")

    # ------------------------------------------------ C: segment load maps
    draw_segment_maps()

    with open(os.path.join(OUT, "contention_impact.json"), "w") as f:
        json.dump({"fabric": fabric_mod.provenance(fabric_mod.default()),
                   "operating_point_words_per_cycle": BW_POINT,
                   "stall_free_latency_s": stall_free, "compute_s": compute,
                   "write_s": write, "prop_s": prop, "macro_edge_words": unit,
                   "by_scheme": rowsA, "by_layout": rowsB,
                   "sweep_bw": BW_SWEEP, "sweep_by_scheme": A,
                   "sweep_by_layout": B}, f, indent=1)
    print("JSON -> contention_impact.json")


if __name__ == "__main__":
    if "--maps-only" in sys.argv:
        draw_segment_maps()
    else:
        main()
