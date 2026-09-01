"""Does spatial_multi_die RAISE the D2D placement stakes? (follow-up of C12)

Before C12 the only die-level traffic was the inter-layer hidden state
(0.52M words per boundary, prefill S=512): placement touched nothing in a
single pass and up to ~2x throughput in the pipelined mode. A spatially split
op adds INTRA-OP die flows -- for the 4-die probe, 14.4M words per die edge,
~28x heavier -- and they sit on the op's own critical path, no pipelining
needed. This script keeps the op and its mapping fixed and moves only WHERE
its four dies sit on the 6x4 package grid.

Usage (container): CIMSIM_FABRIC=models/fabric/mlx300_multidie.yaml is set
internally; one mapper run, all placements re-scored analytically.
"""
import dataclasses
import os
import sys

sys.path.insert(0, "/home/workspace")
os.environ.setdefault("CIMSIM_FABRIC",
                      "/home/workspace/models/fabric/mlx300_multidie.yaml")

import scripts.crossbar_comm as cc
from scripts import fabric as fabric_mod
from scripts import interconnect as ic
from scripts import llm_workload as lw
from scripts import mlx_system as mlx
from scripts import placement as pm

BW = [256.0, 4096.0, 65536.0]
PJ = 10.0e-12                      # die link, Simba GRS measured-band midpoint


def with_bw(fab, bw):
    return dataclasses.replace(fab, levels=[
        dataclasses.replace(l, link=dataclasses.replace(
            l.link, bandwidth_words_per_cycle=bw)) if l.name == "die" else l
        for l in fab.levels]).validate()


def placed(fab, slots4):
    """Logical dies 0..3 on the given physical slots; rest fill the remainder."""
    seq = pm.sequential_fill(fab)
    rest = [s for s in seq.slots["die"] if s not in slots4]
    return dataclasses.replace(
        seq, slots={**seq.slots, "die": list(slots4) + rest}).verify(fab)


def main():
    fab = mlx.FABRIC
    big = lw.Op("probe", "static", P=64, C=2048, M=16384)
    print(f"probe: {lw.dies_for_op(big)} dies; one mapper run ...", flush=True)
    r = lw.run_op(big, overcapacity="spatial_multi_die", save_comm=False)
    res = r["result"]
    flows, _, _, _ = cc.build_flows(res.output_dir, verbose=False, fabric=fab)
    dvol = max(f["volume"] for f in flows if f["level_name"] == "die")
    comp = r["compute_latency_s"]
    print(f"  compute {comp*1e3:.3f} ms | intra-op die edge {dvol/1e6:.2f} M words "
          f"(inter-layer boundary is {512*1024/1e6:.2f} M -- the intra-op "
          f"edge is {dvol/(512*1024):.0f}x HEAVIER)\n")

    # the mesh hub (package anchor) on the 6x4 grid
    hub = ic.build(fab, "die", pm.sequential_fill(fab)).hub_coord()
    print(f"  package anchor at {hub}\n")

    PLACES = [
        ("clustered at anchor", sorted(
            [(x, y) for y in range(4) for x in range(6)],
            key=lambda s: abs(s[0]-hub[0]) + abs(s[1]-hub[1]))[:4]),
        ("top row (default)", [(0, 0), (1, 0), (2, 0), (3, 0)]),
        ("one column", [(0, 0), (0, 1), (0, 2), (0, 3)]),
        ("four corners", [(0, 0), (5, 0), (0, 3), (5, 3)]),
    ]

    hdr = (f"{'die-set placement':22}{'busiest wire':>13}{'mean hops':>10}"
           f"{'surplus E':>11}")
    for bw in BW:
        hdr += f"{f'op lat @{bw:,.0f}':>15}"
    print(hdr)
    rows = []
    for label, slots4 in PLACES:
        pl = placed(fab, slots4)
        m = ic.build(fab, "die", pl)
        act = [f for f in flows if f["level_name"] == "die" and f["volume"] > 0]
        hops = [m.hops(ic.HUB, f["node"]) for f in act]
        surplus = sum(f["volume"] * max(h - 1.0, 0.0) for f, h in zip(act, hops))
        row = (f"{label:22}"
               f"{max(_loads(flows, with_bw(fab, 256.0), pl).values())/dvol:>12.1f}x"
               f"{sum(hops)/len(hops):>10.2f}"
               f"{surplus*PJ*1e3:>9.2f} mJ")
        lats = {}
        for bw in BW:
            occ = cc.link_occupancy(flows, with_bw(fab, bw),
                                    res.cycle_seconds, pl)
            lats[str(int(bw))] = max(comp, occ["serialization_s"])
            row += f"{lats[str(int(bw))]*1e3:>13.2f} ms"
        print(row)
        rows.append({"label": label,
                     "busiest_x": max(_loads(flows, with_bw(fab, 256.0),
                                             pl).values()) / dvol,
                     "mean_hops": sum(hops) / len(hops),
                     "surplus_J": surplus * PJ, "lat_s": lats})

    print("\n  reference: the inter-layer boundary lever at the same grid was "
          "1x vs 2x busiest wire (snake vs sequential), surplus 0-0.44 mJ "
          "per PASS (23 boundaries)")

    import json
    with open(os.path.join("/home/workspace/analysis",
                           "multidie_placement.json"), "w") as f:
        act0 = next(f for f in flows
                    if f["level_name"] == "die" and f["volume"] > 0)
        json.dump({"fabric": fabric_mod.provenance(fab),
                   "op": {"C": 2048, "M": 16384, "dies": lw.dies_for_op(big)},
                   "compute_s": comp, "die_edge_words": dvol,
                   "die_edge_down": act0.get("down", dvol),
                   "die_edge_up": act0.get("up", 0.0),
                   "cycle_s": res.cycle_seconds,
                   "placements": [{k: v for k, v in r.items()} for r in rows]},
                  f, indent=1)
    print("JSON -> multidie_placement.json")


def _loads(flows, fab, pl):
    occ = cc.link_occupancy(flows, fab, fab.device.cycle_seconds, pl)
    return {e["resource"]: e["volume"] for e in occ["per_link"]
            if e["resource"].startswith("die/")}


if __name__ == "__main__":
    main()
