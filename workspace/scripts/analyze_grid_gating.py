"""Which variable gates the hub-position lever? (C28, from the 2026-08-28 notes)

The 2x4 switch (C27) took the buffer-position lever from 1.67x (3x3, one
empty slot) to 1.00x. "3x3 vs 2x4" mixes two variables -- the ASPECT RATIO
(square vs elongated) and the OCCUPANCY STRUCTURE (an empty slot vs a filled
grid) -- and either could be the gate. This script separates them: the same
traffic (the frozen ffn1 macro edges, values, direction-split, 16-bit
partial sums) and the same mapping, only the macro grid and the hub position
change:

    3x3 one empty slot | 2x4 filled | 4x4 (8 of 16 slots) | 2x8 (8 of 16 slots)

4x4 is the deciding cell: filled-in-shape AND square. If its lever returns,
the gate is the aspect ratio (a square hub splits the traffic four ways, an
elongated grid fills a column either way); if 4x4 also reads 1.00x, the gate
is the traffic asymmetry created by the empty slot and "square" is not the
condition. 4x4 and 2x8 have 16 slots for 8 macros, so WHICH 8 slots is a
variable of its own: two natural fillings (half-fill = the first rows,
checkerboard) are run and reported separately, never averaged.

The same sweep is repeated with the heaviest-talker experiment of group 13
(one macro's traffic x4, moved through every slot): the soft-placement lever
(max / min busiest wire over the heavy talker's position) is reported per
grid and hub, because the same gate may govern it.

Outputs: analysis/grid_gating.json, analysis/grid_gating.png; pinned in
tests/test_grid_gating.py. Closed-form (link_occupancy on frozen flows).

Usage (container): python3 scripts/analyze_grid_gating.py
"""
import dataclasses
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import scripts.crossbar_comm as cc
from scripts import anchors as an
from scripts import fabric as fabric_mod
from scripts import interconnect as ic
from scripts import placement as pm
from scripts import traffic

OUT = "/home/workspace/analysis"
FIX = "/home/workspace/tests/fixtures"
CYC = an.CYCLE_S
BW = 16384.0
HEAVY = 4.0

GRIDS = [("3x3, one empty slot", (3, 3), "half"),
         ("2x4, filled", (2, 4), "half"),
         ("4x4, half-fill (rows 0-1)", (4, 4), "half"),
         ("4x4, checkerboard", (4, 4), "checker"),
         ("2x8, half-fill (row 0)", (2, 8), "half"),
         ("2x8, checkerboard", (2, 8), "checker")]
HUBS = [("centre", {"routing": "xy", "hub": "center"}),
        ("corner", {"routing": "xy", "hub": "corner"})]


def variant(base, mesh, params):
    levels = []
    for lv in base.levels:
        if lv.name == "macro":
            lv = dataclasses.replace(lv, mesh=mesh,
                                     link=dataclasses.replace(lv.link, topology="mesh", params=params,
                                                              bandwidth_words_per_cycle=BW))
        levels.append(lv)
    return dataclasses.replace(base, name=f"gate-{mesh[0]}x{mesh[1]}", levels=levels).validate()


def star_variant(base):
    levels = [dataclasses.replace(lv, link=dataclasses.replace(lv.link, topology="star", params={},
                                                              bandwidth_words_per_cycle=BW))
              if lv.name == "macro" else lv for lv in base.levels]
    return dataclasses.replace(base, name="gate-star", levels=levels).validate()


def placement_for(fab, mesh, filling):
    """8 macros on the grid: half-fill = row-major first 8 slots (sequential
    fill); checkerboard = the 8 even-parity slots."""
    seq = pm.sequential_fill(fab)
    if filling == "half":
        return seq
    X, Y = mesh
    tbl = [(float(x), float(y)) for y in range(Y) for x in range(X) if (x + y) % 2 == 0][:8]
    assert len(tbl) == 8, (mesh, len(tbl))
    return dataclasses.replace(seq, slots={**seq.slots, "macro": tbl}).verify(fab)


def ffn1_flows(fab, heavy=None):
    """The frozen ffn1 macro edges (values, down + up), one flow per macro;
    `heavy` = the logical macro whose traffic is x4."""
    ts = traffic.extract(fabric=fab,
                         mapping_text=open(os.path.join(FIX, "ffn1_prefill_map.txt")).read(),
                         stats_text=open(os.path.join(FIX, "ffn1_prefill_stats.txt")).read())
    ev = ts.edge_volumes()["macro"]
    fl = []
    for m in range(8):
        k = HEAVY if m == heavy else 1.0
        fl.append({"level": "glb<->macro", "level_name": "macro", "node": m,
                   "src": "glb", "dst": f"macro{m}", "volume": (ev["in"] + ev["out"]) * k,
                   "down": ev["in"] * k, "up": ev["out"] * k, "distance": 0.0})
    return fl


def busiest(fab, pl, flows):
    occ = cc.link_occupancy(flows, fab, CYC, pl)
    return occ["serialization_s"], occ["bottleneck"]


def sharers(fab, pl, resource):
    """Which macros' hub paths cross the busiest resource (its segment key)."""
    import re
    m = ic.build(fab, "macro", pl)
    key = re.search(r"seg\([^)]*\)-\([^)]*\)", resource)
    seg = key.group(0) if key else resource
    return [i for i in range(8) if any(seg in r for r in m.path(ic.HUB, i))]


def main():
    base = fabric_mod.default()
    star = star_variant(base)
    one = busiest(star, pm.sequential_fill(star), ffn1_flows(star))[0]       # one macro edge's time
    rows, sweep = [], {}
    print(f"busiest wire in macro-edge units (star = {one*1e3:.4f} ms per edge at {BW:,.0f} w/c)\n")
    print(f"  {'grid':28} {'hub':7} {'busiest':>8} {'sharers':22} {'heavy min..max':>16} {'soft lever':>11}")
    for gname, mesh, filling in GRIDS:
        for hname, params in HUBS:
            fab = variant(base, mesh, params)
            pl = placement_for(fab, mesh, filling)
            ser, bn = busiest(fab, pl, ffn1_flows(fab))
            load = ser / one
            who = sharers(fab, pl, bn["resource"]) if bn else []
            hs = []
            for h in range(8):
                s, _ = busiest(fab, pl, ffn1_flows(fab, heavy=h))
                hs.append(s / one)
            m = ic.build(fab, "macro", pl)
            rows.append({"grid": gname, "mesh": list(mesh), "filling": filling, "hub": hname,
                         "hub_coord": list(m.hub_coord()), "slots": [list(s) for s in pl.slots["macro"]],
                         "busiest_x": load, "busiest_resource": bn["resource"] if bn else None,
                         "sharers": who, "heavy_x": hs,
                         "soft_lever": max(hs) / min(hs), "heavy_min": min(hs), "heavy_max": max(hs)})
            print(f"  {gname:28} {hname:7} {load:>7.2f}x {str(who):22} {min(hs):>7.2f}..{max(hs):<7.2f} {max(hs)/min(hs):>10.2f}x")
    # the lever per grid: corner / centre
    levers = {}
    for gname, mesh, filling in GRIDS:
        c = next(r for r in rows if r["grid"] == gname and r["hub"] == "centre")
        k = next(r for r in rows if r["grid"] == gname and r["hub"] == "corner")
        levers[gname] = {"centre_x": c["busiest_x"], "corner_x": k["busiest_x"],
                         "lever": k["busiest_x"] / c["busiest_x"],
                         "soft_lever_centre": c["soft_lever"], "soft_lever_corner": k["soft_lever"]}
    print("\n  hub-position lever (corner / centre) and the soft-placement lever per grid:")
    for g, v in levers.items():
        print(f"    {g:28} centre {v['centre_x']:.2f}x  corner {v['corner_x']:.2f}x  -> lever {v['lever']:.2f}x"
              f"  | heavy-talker lever centre {v['soft_lever_centre']:.2f}x, corner {v['soft_lever_corner']:.2f}x")
    # the gating verdict, computed, not assumed. Under dimension-order (xy)
    # routing a corner hub's exit wire carries every macro NOT in the hub's
    # own column: corner = N - H (H = occupied slots sharing the hub's x);
    # a centred hub splits four ways, so its busiest wire is the largest
    # quadrant share. The lever is (N - H) / centre_max: a 2-wide grid has
    # H = N/2, so the corner wire carries exactly what the centre's busiest
    # wire carries -> no lever, whatever the filling or the aspect ratio.
    for r in rows:
        if r["hub"] == "corner":
            hx = r["hub_coord"][0]
            H = sum(1 for s in r["slots"] if abs(s[0] - hx) < 1e-9)
            r["hub_column_slots"] = H
            r["corner_rule_x"] = 8 - H
            assert abs(r["corner_rule_x"] - r["busiest_x"]) < 1e-9, (r["grid"], r["corner_rule_x"], r["busiest_x"])
    two_wide = {g: levers[g]["lever"] for g, mesh, _ in GRIDS if mesh[0] == 2}
    wider = {g: levers[g]["lever"] for g, mesh, _ in GRIDS if mesh[0] > 2}
    rule_holds = all(abs(v - 1.0) < 1e-9 for v in two_wide.values()) and all(v > 1.0 + 1e-9 for v in wider.values())
    verdict = ("the grid's width along the routing's first axis (a 2-wide grid has no lever, wider grids do)"
               if rule_holds else "no single variable -- see the table")
    print(f"\n  corner rule (busiest = N - macros in the hub's column) holds in every cell")
    print(f"  levers: 2-wide {', '.join(f'{v:.2f}x' for v in two_wide.values())} | wider "
          f"{', '.join(f'{v:.2f}x' for v in wider.values())} -> gated by {verdict};"
          " neither squareness (the 4x2 half-fill block is not square and reads 1.50x) nor the empty"
          " slot (the 4x4 fillings have none and read 1.50x) is the condition")

    # ---------------- figure
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.9))
    names = [g for g, _, _ in GRIDS]
    x = np.arange(len(names))
    for k, (hname, _) in enumerate(HUBS):
        vals = [next(r["busiest_x"] for r in rows if r["grid"] == g and r["hub"] == hname) for g in names]
        axes[0].bar(x + (k - 0.5) * 0.36, vals, 0.34, color=["#2a9d8f", "#d1495b"][k], label=f"hub at {hname}")
        for i, v in enumerate(vals):
            axes[0].text(i + (k - 0.5) * 0.36, v + 0.08, f"{v:.2f}", ha="center", fontsize=7.5)
    for i, g in enumerate(names):
        axes[0].text(i, max(levers[g]["centre_x"], levers[g]["corner_x"]) + 0.6, f"lever {levers[g]['lever']:.2f}x",
                     ha="center", fontsize=8, fontweight="bold")
    axes[0].set_xticks(x); axes[0].set_xticklabels([n.replace(", ", "\n") for n in names], fontsize=7.5)
    axes[0].set_ylabel("busiest wire (macro-edge units)")
    axes[0].set_ylim(0, max(r["busiest_x"] for r in rows) * 1.35)
    axes[0].set_title("hub-position lever = corner / centre, per grid", fontsize=10)
    axes[0].legend(fontsize=8); axes[0].grid(alpha=0.25, axis="y")
    for k, (hname, _) in enumerate(HUBS):
        lo = [next(r["heavy_min"] for r in rows if r["grid"] == g and r["hub"] == hname) for g in names]
        hi = [next(r["heavy_max"] for r in rows if r["grid"] == g and r["hub"] == hname) for g in names]
        axes[1].bar(x + (k - 0.5) * 0.36, [h - l for l, h in zip(lo, hi)], 0.34, bottom=lo,
                    color=["#2a9d8f", "#d1495b"][k], alpha=0.85, label=f"hub at {hname}")
        for i, (l, h) in enumerate(zip(lo, hi)):
            axes[1].text(i + (k - 0.5) * 0.36, h + 0.1, f"{h/l:.2f}x", ha="center", fontsize=7.5)
    axes[1].set_xticks(x); axes[1].set_xticklabels([n.replace(", ", "\n") for n in names], fontsize=7.5)
    axes[1].set_ylabel("busiest wire, heavy talker x4 (min..max over its slot)")
    axes[1].set_title("soft-placement lever = max / min over the heavy talker's slot", fontsize=10)
    axes[1].legend(fontsize=8); axes[1].grid(alpha=0.25, axis="y")
    fig.suptitle(f"What gates the hub-position lever?  verdict: {verdict}\n"
                 "same traffic, same mapping; only the macro grid, its filling and the hub move "
                 "(4x4 / 2x8: 8 of 16 slots, two fillings reported separately)", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.9])
    p = os.path.join(OUT, "grid_gating.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f"PNG -> {p}")
    with open(os.path.join(OUT, "grid_gating.json"), "w") as f:
        json.dump({"fabric_base": fabric_mod.provenance(base), "bandwidth_words_per_cycle": BW,
                   "one_edge_s": one, "rows": rows, "levers": levers, "verdict": verdict}, f, indent=1)
    print("JSON -> grid_gating.json")


if __name__ == "__main__":
    main()
