"""A7 days 2-3 (C60): torus + ring join the registry -- the readouts.

Pre-registration: FIXLIST O19, A7 EXECUTION (rulings 1-4 + review
clauses 1-2). The folded models are the default (hops() = physical
length, router_hops() = crossing count); everything here is a
post-v6 SEPARATE readout -- no committed sweep output changes.

READOUTS
  A. on-die (macro level, 2x4 default + 3x3 comparison grid): the
     three-sentence portrait's numbers -- hub->node COUNT mean vs
     PHYSICAL mean vs max, mesh vs folded torus, centre vs corner hub;
     and the occupancy side on the uniform synthetic flows (the pinned
     8.27x family's machinery): peak-wire load and the corner/centre
     ratio, mesh vs torus (expectation: compresses toward 1).
  B. die level (6x8, 48 dies): the three stored orderings (snake /
     sequential rows / far-pairs adversarial) re-scored under folded
     ring and folded torus. GATE: the mesh count means must reproduce
     the stored avg_hops (1.0 / 1.745 / 6.553) before anything else is
     read. Expectation pre-written by ruling 2: the ordering spread
     NARROWS under ring; a widening is a recorded finding (a 1D cycle
     has a longer far end than a 2D mesh -- the pre-reg sentence "the
     ring removes the far end" is true against a CHAIN, the data
     decides against the mesh).

    host/container both fine (pure python + json):
    python3 scripts/analyze_torus_ring.py
      -> analysis/torus_ring.json + analysis/torus_ring.md
"""
import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.crossbar_comm as cc
from scripts import analyze_d2d as d2d
from scripts import anchors, fabric, interconnect as ic, placement

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
A = os.path.join(WS, "analysis")
VOL = 1.0


def _uniform_flows(n=8):
    return [{"level": "glb<->macro", "level_name": "macro", "node": m,
             "src": "glb", "dst": f"macro{m}", "volume": VOL,
             "distance": 0.0} for m in range(n)]


BW = 16_384.0                # the pinned tables' operating point (words/cycle)


def _with(base, topology, params, mesh=None):
    levels = []
    for lv in base.levels:
        if lv.name == "macro":
            lv = dataclasses.replace(
                lv, mesh=mesh or lv.mesh,
                link=dataclasses.replace(lv.link, topology=topology,
                                         params=params,
                                         bandwidth_words_per_cycle=BW))
        levels.append(lv)
    return dataclasses.replace(base, name=f"v-{topology}",
                               levels=levels).validate()


def _stats(icobj):
    n = len(icobj.slots)
    cnt = [icobj.router_hops(ic.HUB, i) for i in range(n)]
    phys = [icobj.hops(ic.HUB, i) for i in range(n)]
    return {"count_mean": sum(cnt) / n, "phys_mean": sum(phys) / n,
            "phys_max": max(phys)}


def on_die():
    out = {}
    f24 = fabric.default()
    f33 = fabric.from_yaml(os.path.join(WS, "models", "fabric",
                                        "mlx300_3x3.yaml"))
    for gname, base in (("2x4", f24), ("3x3", f33)):
        rows = {}
        for scheme in ("mesh", "torus"):
            for hub in ("center", "corner"):
                fab = _with(base, scheme, {"routing": "xy", "hub": hub})
                pl = placement.sequential_fill(fab)
                m = ic.build(fab, "macro", pl)
                st = _stats(m)
                occ = cc.link_occupancy(_uniform_flows(), fab,
                                        anchors.CYCLE_S, pl)
                st["peak_wire_vol"] = occ["bottleneck"]["volume"] / VOL
                st["serialization_s"] = occ["serialization_s"]
                # C59 identity holds on the physical length (point-to-point)
                for i in range(len(m.slots)):
                    assert m.energy_hops(ic.HUB, i) == m.hops(ic.HUB, i)
                rows[f"{scheme}/{hub}"] = st
        for scheme in ("mesh", "torus"):
            c, k = rows[f"{scheme}/center"], rows[f"{scheme}/corner"]
            rows[f"{scheme}_corner_over_center_peak"] = (
                k["peak_wire_vol"] / c["peak_wire_vol"])
        out[gname] = rows
    return out


def die_level():
    fabM = fabric.from_yaml(d2d.MULTI)                         # the 48-die fabric
    stored = {a["assignment"]: a["avg_hops"]
              for a in json.load(open(os.path.join(A, "d2d_impact.json")))
              ["assignments"]}
    pl = placement.sequential_fill(fabM)
    slots = pl.slots["die"]
    mesh_ic = ic.Mesh(slots, {"routing": "xy", "hub": "center"})
    ring_ic = ic.Ring(slots, {})
    torus_ic = ic.Torus(slots, {"routing": "xy", "hub": "center"})
    rows = {}
    for label, asg in d2d.assignments(fabM):
        pairs = list(zip(asg, asg[1:]))                        # 47 boundaries
        row = {}
        for name, obj in (("mesh", mesh_ic), ("ring", ring_ic),
                          ("torus", torus_ic)):
            cnt = sum(obj.router_hops(a, b) for a, b in pairs) / len(pairs)
            phys = sum(obj.hops(a, b) for a, b in pairs) / len(pairs)
            row[name] = {"count_mean": cnt, "phys_mean": phys}
        # GATE: mesh count reproduces the stored avg_hops
        assert abs(row["mesh"]["count_mean"] - stored[label]) < 1e-9, \
            (label, row["mesh"]["count_mean"], stored[label])
        rows[label] = row
    spread = {}
    for name in ("mesh", "ring", "torus"):
        for cal in ("count_mean", "phys_mean"):
            vals = [rows[k][name][cal] for k in rows]
            spread[f"{name}_{cal}"] = max(vals) / min(vals)
    # CALIBER CONFIRMATION (day-4 review ask): the count and phys spread
    # columns are identical NOT because one copied the other -- the phys
    # chain is walked independently through hops() -- but structurally:
    # BOTH axes of the 6x8 die grid are >= 3 wide, so both are folded
    # (fold 2,2) and every hop of every scheme carries the SAME uniform
    # scalar (torus/ring x2, mesh x1), which cancels in worst/best
    # ratios. Asserted elementwise; contrast the 2x4 macro grid, where
    # fold (1,2) is non-uniform and the two calibers genuinely differ.
    assert torus_ic._wraps == (True, True) and torus_ic._fold == (2.0, 2.0)
    for label, asg in d2d.assignments(fabM):
        for a, b in zip(asg, asg[1:]):
            for obj, fold in ((torus_ic, 2.0), (ring_ic, 2.0), (mesh_ic, 1.0)):
                c = obj.router_hops(a, b)
                if c > 0:
                    assert abs(obj.hops(a, b) / c - fold) < 1e-12
    return {"orderings": rows, "spread_worst_over_best": spread,
            "gate": "mesh count means reproduce stored avg_hops (asserted)",
            "phys_equals_count_spread_because": (
                "both die-grid axes are folded (fold 2,2), so physical "
                "length is a uniform scalar of the count for every scheme "
                "at this level and the scalar cancels in worst/best ratios; "
                "the phys chain is independent (asserted elementwise) and "
                "the flows cross both folded axes -- unlike the 2x4 macro "
                "grid, whose non-uniform fold (1,2) splits the calibers")}


def main():
    out = {"on_die": on_die(), "die_level": die_level()}

    o24, o33 = out["on_die"]["2x4"], out["on_die"]["3x3"]
    dl = out["die_level"]
    L = ["# Torus + ring readouts (A7 days 2-3, C60; post-v6)", "",
         "Folded models (ruling 4): hops() = physical length, router_hops()",
         "= crossing count; both grids' torus rows below are folded.", "",
         "## A. On-die portrait (hub->node; count / physical / occupancy)",
         "",
         "| grid | scheme/hub | count mean | phys mean | phys max | peak wire |",
         "|---|---|---|---|---|---|"]
    for gname, rows in (("2x4", o24), ("3x3", o33)):
        for key in ("mesh/center", "torus/center", "mesh/corner",
                    "torus/corner"):
            r = rows[key]
            L.append(f"| {gname} | {key} | {r['count_mean']:.4f} "
                     f"| {r['phys_mean']:.4f} | {r['phys_max']:.1f} "
                     f"| {r['peak_wire_vol']:.1f} |")
    L += ["",
          f"corner/centre PEAK ratio -- 2x4: mesh "
          f"{o24['mesh_corner_over_center_peak']:.2f} vs torus "
          f"{o24['torus_corner_over_center_peak']:.2f}; 3x3: mesh "
          f"{o33['mesh_corner_over_center_peak']:.2f} vs torus "
          f"{o33['torus_corner_over_center_peak']:.2f}.",
          "", "## B. Die level: 48-die ordering spread (worst/best)", "",
          "| caliber | mesh | ring | torus |", "|---|---|---|---|"]
    sp = dl["spread_worst_over_best"]
    for cal in ("count_mean", "phys_mean"):
        L.append(f"| {cal} | {sp[f'mesh_{cal}']:.2f}x "
                 f"| {sp[f'ring_{cal}']:.2f}x | {sp[f'torus_{cal}']:.2f}x |")
    L += ["", "| ordering | mesh count | ring count | torus count |",
          "|---|---|---|---|"]
    for k, row in dl["orderings"].items():
        L.append(f"| {k} | {row['mesh']['count_mean']:.3f} "
                 f"| {row['ring']['count_mean']:.3f} "
                 f"| {row['torus']['count_mean']:.3f} |")
    L.append("")
    with open(os.path.join(A, "torus_ring.json"), "w") as f:
        json.dump(out, f, indent=1)
    with open(os.path.join(A, "torus_ring.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    print("2x4 corner/centre peak: mesh",
          round(o24["mesh_corner_over_center_peak"], 3), "torus",
          round(o24["torus_corner_over_center_peak"], 3),
          "| 3x3: mesh", round(o33["mesh_corner_over_center_peak"], 3),
          "torus", round(o33["torus_corner_over_center_peak"], 3))
    print("die spread (count): mesh", round(sp["mesh_count_mean"], 2),
          "ring", round(sp["ring_count_mean"], 2),
          "torus", round(sp["torus_count_mean"], 2))


if __name__ == "__main__":
    main()
