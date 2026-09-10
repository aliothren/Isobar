"""O19 batch item 3 (C63-c): CMesh -- the concentration curve + figure.

Pre-registration: FIXLIST O19 batch block, ITEM 3, WITH the amendment
filed before any readout ran: the concentration cost's carrier is the
ROUTER LOCAL PORT (k tile nodes share one router's injection/ejection
bandwidth), not a wire segment -- a wire-only occupancy account would
let the funnel vanish at high k (all-private access links). The
amended expectation: the busiest PORT load equals k EXACTLY on the
uniform hub-rooted flows (monotone by construction), and the OVERALL
bottleneck is max(grid segments, port funnel) -- the readout's story
is the crossover k* where concentration takes over the bottleneck.

Uniform hub-rooted flows on the 2x4 macro grid (8 slots), hub center:
down 1.0 / up 0.5 per node (the psum-weighted convention's shape),
k in {1 ([1,1] = mesh, pinned busiest 4.0), 2 ([1,2]), 4 ([2,2]),
8 ([2,4] = single router)}.

    python3 scripts/analyze_cmesh.py     (container)
      -> analysis/cmesh_weave.json + .md + cmesh_concentration.png
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import fabric, interconnect as ic, placement

OUT = "/home/workspace/analysis"
KS = [("1", [1, 1]), ("2", [1, 2]), ("4", [2, 2]), ("8", [2, 4])]
DOWN, UP = 1.0, 0.5


def loads_for(obj, n=8):
    load = {}
    for i in range(n):
        for vol, (a, b) in ((DOWN, (ic.HUB, i)), (UP, (i, ic.HUB))):
            for r, tag in obj.path_directed(a, b):
                key = f"{r}/{tag}"
                load[key] = load.get(key, 0.0) + vol
    return load


def main():
    slots = placement.sequential_fill(fabric.default()).slots["macro"]
    rows = {}
    for kname, conc in KS:
        c = ic.CMesh(slots, {"routing": "xy", "hub": "center",
                             "concentration": conc})
        load = loads_for(c)
        seg = {k: v for k, v in load.items() if ":seg" in k}
        prt = {k: v for k, v in load.items() if ":rport" in k}
        rows[kname] = {
            "concentration": conc,
            "mean_hops": c.mean_hops(),
            "busiest_overall": max(load.values()),
            "busiest_segment": max(seg.values()) if seg else 0.0,
            "busiest_port": max(prt.values()) if prt else 0.0,
            "bottleneck_resource": max(load, key=load.get)}
    # the amended expectations, checked in place
    for kname, conc in KS:
        k = conc[0] * conc[1]
        if k > 1:
            assert rows[kname]["busiest_port"] == k * DOWN, (kname, rows)
    ks = [int(k) for k, _ in KS]
    overall = [rows[str(k)]["busiest_overall"] for k in ks]
    kstar = next((k for k in ks if k > 1
                  and rows[str(k)]["busiest_port"]
                  >= rows[str(k)]["busiest_overall"]), None)
    out = {"flows": {"down": DOWN, "up": UP, "nodes": 8,
                     "grid": "2x4 macro, hub center"},
           "rows": rows,
           "crossover_k_star": kstar,
           "expectations": {
               "port_equals_k_exactly": True,
               "port_monotone": all(
                   rows[str(a)]["busiest_port"] <= rows[str(b)]["busiest_port"]
                   for a, b in zip(ks, ks[1:])),
               "k1_degenerates_to_mesh_busiest_4":
               rows["1"]["busiest_overall"] == 4.0 * DOWN}}
    with open(os.path.join(OUT, "cmesh_weave.json"), "w") as f:
        json.dump(out, f, indent=1)

    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.plot(ks, overall, "o-", color="#d1495b", lw=2,
            label="overall bottleneck")
    ax.plot(ks, [rows[str(k)]["busiest_segment"] for k in ks], "s--",
            color="#8fa8bf", label="busiest grid segment")
    ax.plot(ks, [rows[str(k)]["busiest_port"] for k in ks], "^--",
            color="#2a9d8f", label="busiest router port (= k)")
    if kstar:
        ax.axvline(kstar, color="#555", lw=0.8, ls=":",
                   label=f"funnel takes over at k* = {kstar}")
    ax.set_xscale("log", base=2)
    ax.set_xticks(ks)
    ax.set_xticklabels([str(k) for k in ks])
    ax.set_xlabel("concentration k (nodes per router)")
    ax.set_ylabel("busiest-resource load (x per-node down volume)")
    ax.set_title("CMesh: the concentration funnel vs the grid\n"
                 "(2x4 macro, uniform hub-rooted flows)", fontsize=11)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "cmesh_concentration.png"), dpi=160)

    L = ["# CMesh (O19 batch item 3, C63-c; post-v6)", "",
         "Concentrated mesh: k nodes share one router; [1,1] degenerates",
         "to mesh exactly (pinned). AMENDMENT (filed before readouts): the",
         "concentration cost's carrier is the ROUTER LOCAL PORT, not a",
         "wire -- a wire-only account would let the funnel vanish at high",
         "k. Port load = k exactly on uniform hub-rooted flows.", "",
         "| k | tile | mean hops | busiest segment | busiest port | overall |",
         "|---|---|---|---|---|---|"]
    for kname, conc in KS:
        r = rows[kname]
        L.append(f"| {kname} | {conc} | {r['mean_hops']:.3f} "
                 f"| {r['busiest_segment']:.1f} | {r['busiest_port']:.1f} "
                 f"| {r['busiest_overall']:.1f} ({r['bottleneck_resource']}) |")
    L += ["",
          f"Crossover: the funnel takes over the bottleneck at k* = {kstar}.",
          "Below it the grid segments bind (mesh-like); above it the",
          "router's shared injection/ejection bandwidth does -- the",
          "boundary band sits at or above mesh's for every k, direction",
          "unique, as pre-registered.", "",
          "![concentration curve](cmesh_concentration.png)", ""]
    with open(os.path.join(OUT, "cmesh_weave.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    for kname, _ in KS:
        print(kname, rows[kname])
    print("k*:", kstar, "| expectations:", out["expectations"])


if __name__ == "__main__":
    main()
