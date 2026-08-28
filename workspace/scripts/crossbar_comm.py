"""
Per-pair (crossbar <-> crossbar / node <-> node) communication model.

Turns the AGGREGATE per-level traffic + communication structure (from
crossbar_stats) into an EXPLICIT physical flow model:

  1. Give every node a coordinate on a nested floorplan
     (macros in a grid, cores within a macro, crossbars within a core).
  2. Walk the communication tree implied by the mapping:
       - inputs  flow DOWN  glb -> macro -> core -> crossbar  (multicast 1->N)
       - outputs flow UP    crossbar -> core -> macro -> glb   (reduction N->1)
     Each tree edge is a (src_node -> dst_node, volume, distance) pair.
  3. Aggregate to:
       - per-EDGE traffic and traffic*distance (the actual pairwise links),
       - per-CROSSBAR communication cost (volume * path length to glb) -- this
         VARIES BY POSITION even though Timeloop's per-crossbar volume is uniform,
         which is exactly the crossbar-aware effect,
       - a crossbar floorplan heatmap of that cost.

This is the bridge from "aggregate bus traffic" to "which crossbar talks to
which, how much, how far." Volumes are exact (from the run); the per-pair split
follows the multicast/reduction tree + the chosen placement.
"""
import os
import re
import csv
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import crossbar_stats as cbs


# --------------------------------------------------------------------------
def nested_floorplan(n_macros, cores_per_macro, xbars_per_core):
    """Assign every crossbar a global (x, y) on a nested grid, and return the
    centroids of cores / macros / die too. Returns dicts keyed by index."""
    def grid(n):  # near-square arrangement
        c = int(np.ceil(np.sqrt(n)))
        return c, int(np.ceil(n / c))
    MX, MY = grid(n_macros)
    CX, CY = grid(cores_per_macro)
    XX, XY = grid(xbars_per_core)

    xb_coord = {}        # global crossbar id -> (x, y)
    core_coord = {}      # (macro, core) -> centroid
    macro_coord = {}     # macro -> centroid
    gid = 0
    for m in range(n_macros):
        mx, my = m % MX, m // MX
        for c in range(cores_per_macro):
            cx, cy = c % CX, c // CX
            cxs, cys = [], []
            for x in range(xbars_per_core):
                xx, xy = x % XX, x // XX
                gx = (mx * CX + cx) * XX + xx
                gy = (my * CY + cy) * XY + xy
                xb_coord[gid] = (gx, gy)
                cxs.append(gx); cys.append(gy)
                gid += 1
            core_coord[(m, c)] = (np.mean(cxs), np.mean(cys))
        mcs = [core_coord[(m, c)] for c in range(cores_per_macro)]
        macro_coord[m] = (np.mean([p[0] for p in mcs]),
                          np.mean([p[1] for p in mcs]))
    die_coord = (np.mean([p[0] for p in macro_coord.values()]),
                 np.mean([p[1] for p in macro_coord.values()]))
    return xb_coord, core_coord, macro_coord, die_coord, (MX*CX*XX, MY*CY*XY)


def _manh(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def level_max_hops(fabric=None, placement=None):
    """The WORST-case Manhattan hop count at each on-die tree level, computed
    from the ACTUAL placement (defaults reproduce the legacy nested floorplan).

    Used by the distance-LATENCY overlay: within a level all branches are
    parallel, so the longest branch (max hops) sets the critical path; across
    levels the path is in series (summed by position_aware_latency).
    Returns {link_name: max_hops}; the keys are the fabric links' names, which
    match HOP_LATENCY_NS. Hops are in GLOBAL leaf-grid units (as the legacy
    values 12/3/2 were) -- do not mix with the per-level slot units the energy
    overlay uses.
    """
    from scripts import fabric as fabric_mod
    from scripts import placement as placement_mod
    fab = fabric or fabric_mod.default()
    pl = (placement or placement_mod.sequential_fill(fab)).verify(fab)

    from scripts import interconnect as ic_mod
    out = {}
    for lv in _on_die_levels(fab)[-3:]:
        ic = ic_mod.build(fab, lv.name, pl)
        out[lv.link.name] = ic.max_hops() * fab.pitch(lv.name)
    return out


# --------------------------------------------------------------------------
def _on_die_levels(fab):
    """The three on-die tree levels (macro, core, crossbar) as fabric Levels.
    crossbar_comm models exactly this three-level tree; a deeper generalization
    is the CostModel's job (workstream B)."""
    meshed = [lv for lv in fab.levels if lv.mesh is not None]
    assert len(meshed) >= 3, "fabric needs >= 3 meshed levels for the on-die tree"
    return meshed


def build_flows(output_dir, layer_name="", verbose=True, fabric=None,
                placement=None, model="structured"):
    """Return (flows, per_crossbar_cost, grid_shape, xb_coord).

    flows: list of dicts {level, src, dst, volume, distance} -- the pairwise links.
    per_crossbar_cost: array[n_crossbars] of an active crossbar's attributable
                       volume x distance along its path (shared multicast volume
                       split among the leaves it serves; idle crossbars get 0).
    verbose=True prints the crossbar_stats aggregate report; False stays quiet
    (used by the auto-saved dump).

    Structure comes from `fabric`, coordinates from `placement` (defaults:
    models/fabric config + sequential_fill).

    model="structured" (default, v1): edge volumes from the mapping's real
    multicast/reduction structure via traffic.extract -- a multicast slice
    crosses an upper edge ONCE, idle instances carry zero.
    model="uniform" (v0): the legacy total/N division, kept ONLY as the
    comparison baseline for the v0->v1 re-baselining; not a fallback.
    """
    from scripts import fabric as fabric_mod
    from scripts import placement as placement_mod
    from scripts import traffic
    fab = fabric or fabric_mod.default()
    pl = (placement or placement_mod.sequential_fill(fab)).verify(fab)

    # stats parse: traffic volumes + the fabric-consistency sentinel
    r = cbs.report(output_dir, layer_name) if verbose \
        else cbs.hierarchy(output_dir)

    meshed = _on_die_levels(fab)
    lvl_m, lvl_c, lvl_x = meshed[-3], meshed[-2], meshed[-1]
    nM, cores_per_macro, xbars_per_core = \
        lvl_m.per_parent, lvl_c.per_parent, lvl_x.per_parent
    nX = fab.count_below(lvl_x.name)

    stats_path = os.path.join(output_dir, "timeloop-mapper.stats.txt")
    txt = open(stats_path).read()

    if model == "structured":
        ts = traffic.extract(output_dir, fab, stats_text=txt)
        ev = ts.edge_volumes()
        shares = ts.leaf_shares()
        fanouts = ts.active_fanouts()
        f_d = fanouts[0] if len(fanouts) == 4 else 1     # op spans f_d dies
        f_m, f_c, f_x = fanouts[-3:]
        vol_edge = {lv: ev[lv]["in"] + ev[lv]["out"]
                    for lv in (lvl_m.name, lvl_c.name, lvl_x.name)}
        # the two DIRECTIONS kept apart (O22/O23): inputs go down, outputs
        # (partial sums) come up
        vol_dn = {lv: ev[lv]["in"] for lv in (lvl_m.name, lvl_c.name, lvl_x.name)}
        vol_up = {lv: ev[lv]["out"] for lv in (lvl_m.name, lvl_c.name, lvl_x.name)}
        if len(fanouts) == 4:
            vol_edge["die"] = ev["die"]["in"] + ev["die"]["out"]
            vol_dn["die"], vol_up["die"] = ev["die"]["in"], ev["die"]["out"]
    elif model == "uniform":
        ts_u = traffic.extract(output_dir, fab, stats_text=txt)   # value units (C25)
        in_per_xb = ts_u.in_leaf * ts_u.n_active / nX
        out_per_xb = ts_u.out_leaf * ts_u.n_active / nX
        f_m, f_c, f_x = nM, cores_per_macro, xbars_per_core
        vol_edge = {lvl_m.name: (in_per_xb + out_per_xb) * cores_per_macro * xbars_per_core,
                    lvl_c.name: (in_per_xb + out_per_xb) * xbars_per_core,
                    lvl_x.name: in_per_xb + out_per_xb}
        vol_dn = {lvl_m.name: in_per_xb * cores_per_macro * xbars_per_core,
                  lvl_c.name: in_per_xb * xbars_per_core, lvl_x.name: in_per_xb}
        vol_up = {lvl_m.name: out_per_xb * cores_per_macro * xbars_per_core,
                  lvl_c.name: out_per_xb * xbars_per_core, lvl_x.name: out_per_xb}
        shares = {lvl_m.name: in_per_xb + out_per_xb,
                  lvl_c.name: in_per_xb + out_per_xb,
                  lvl_x.name: in_per_xb + out_per_xb}
    else:
        raise ValueError(f"unknown traffic model '{model}'")

    xb_coord = pl.leaf_coords(fab)
    gshape = fab.grid_shape()

    # Distances come from each level's SCHEME, in slot units, scaled to the
    # global leaf grid by that level's pitch. `star` reproduces the legacy
    # centroid-Manhattan values exactly (see tests/test_interconnect.py).
    from scripts import interconnect as ic_mod
    ics = {lv.name: ic_mod.build(fab, lv.name, pl) for lv in (lvl_m, lvl_c, lvl_x)}
    d_of = {lv.name: [ics[lv.name].hops(ic_mod.HUB, i) * fab.pitch(lv.name)
                      for i in range(lv.per_parent)]
            for lv in (lvl_m, lvl_c, lvl_x)}

    flows = []
    per_xb = np.zeros(nX)

    # Intra-op die-level flows (spatial_multi_die): the op's slices live on
    # f_d dies; each die's edge carries its unique input slice down and its
    # (un-merged) outputs up, exactly like every tree level below -- the v1
    # anchor is the die scheme's hub (the package attach point; an
    # output-owner-die refinement is a follow-up). The on-die tree flows
    # below describe ONE die (the dies are identical by construction).
    die_lv = fab.level("die")
    if model == "structured" and "die" in [getattr(sp, "level", None)
                                           for sp in ts.splits]:
        ic_die = ic_mod.build(fab, "die", pl)
        for d in range(die_lv.per_parent):
            d_on = d < f_d
            flows.append({"level": die_lv.link.name, "level_name": "die",
                          "node": d, "src": "package", "dst": f"die{d}",
                          "volume": vol_edge["die"] if d_on else 0.0,
                          "down": vol_dn["die"] if d_on else 0.0,
                          "up": vol_up["die"] if d_on else 0.0,
                          "distance": ic_die.hops(ic_mod.HUB, d)})

    gid = 0
    for m in range(nM):
        m_on = m < f_m
        d = d_of[lvl_m.name][m]
        flows.append({"level": lvl_m.link.name, "level_name": lvl_m.name,
                      "node": m, "src": "glb", "dst": f"macro{m}",
                      "volume": vol_edge[lvl_m.name] if m_on else 0.0,
                      "down": vol_dn[lvl_m.name] if m_on else 0.0,
                      "up": vol_up[lvl_m.name] if m_on else 0.0,
                      "distance": d})
        for c in range(cores_per_macro):
            c_on = m_on and c < f_c
            dc = d_of[lvl_c.name][c]
            flows.append({"level": lvl_c.link.name, "level_name": lvl_c.name,
                          "node": c, "src": f"macro{m}",
                          "dst": f"core{m}.{c}",
                          "volume": vol_edge[lvl_c.name] if c_on else 0.0,
                          "down": vol_dn[lvl_c.name] if c_on else 0.0,
                          "up": vol_up[lvl_c.name] if c_on else 0.0,
                          "distance": dc})
            for x in range(xbars_per_core):
                x_on = c_on and x < f_x
                dx = d_of[lvl_x.name][x]
                flows.append({"level": lvl_x.link.name, "level_name": lvl_x.name,
                              "node": x, "src": f"core{m}.{c}",
                              "dst": f"xb{gid}",
                              "volume": vol_edge[lvl_x.name] if x_on else 0.0,
                              "down": vol_dn[lvl_x.name] if x_on else 0.0,
                              "up": vol_up[lvl_x.name] if x_on else 0.0,
                              "distance": dx})
                if x_on:
                    per_xb[gid] = (shares[lvl_x.name] * dx
                                   + shares[lvl_c.name] * dc
                                   + shares[lvl_m.name] * d)
                gid += 1
    return flows, per_xb, gshape, xb_coord


def link_occupancy(flows, fabric, cycle_seconds, placement=None,
                   duplex=None, psum_bytes=None):
    """T2 static contention: per-RESOURCE occupancy time from the structured flows.

    Direction and width (O22/O23): a flow's DOWN component (inputs, 8-bit
    activations) and UP component (outputs = partial sums) are routed
    separately. On a full-duplex scheme (every point-to-point scheme; a bus
    is a shared medium) the two directions occupy different wires, so the
    resource key carries a direction tag. The up component is weighted by
    `psum_bytes` (default: the fabric's `psum_word_bytes`, 2.0 = 16-bit
    partial sums) because partial sums are wider than activations.
    `duplex=False` / `psum_bytes=1.0` reproduce the pre-O22/O23 accounting
    (both directions on one wire, everything at activation width) -- kept
    for the comparison tables, not as a fallback. Node-to-node flows
    (`nodes:(a,b)`, the D2D hand-offs) are one-directional activations.

    Each flow is routed by its level's SCHEME onto the resources it occupies
    (`Interconnect.path`), and every resource accumulates the traffic of every
    flow that crosses it. With `star` each hub->node edge has a private link, so
    no two flows ever meet and this reduces exactly to the pre-W2 per-flow form.
    With `mesh` the routes overlap on shared segments, which is what finally
    couples PLACEMENT to contention.

    Level-agnostic by construction -- die-to-die flows (tagged with
    `"nodes": (a, b)` instead of a hub-side `"node"`) feed this same function;
    llm_workload.die_to_die_activation produces them. Ownership rule: network links belong to this analytic tier
    (only we know per-resource loads; Timeloop has aggregate views only), while
    storage hub bandwidth belongs to Timeloop's native throttling (T1). The two
    tiers compose by MAX, never by sum -- both lower-bound the same
    serialization.

    Returns {"per_link": [{level, resource, direction, volume, seconds}],
    "serialization_s": float, "bottleneck": entry or None}. `volume` is in
    activation words after the width weighting. All zeros when no bandwidth
    is set (the shipped default).
    """
    from scripts import interconnect as ic_mod
    from scripts import placement as placement_mod
    pl = placement or placement_mod.sequential_fill(fabric)
    psum = (getattr(fabric, "psum_word_bytes", 2.0) if psum_bytes is None
            else float(psum_bytes))

    bw, level_of = {}, {}
    for lv in fabric.levels:
        if lv.link is not None:
            bw[lv.link.name] = lv.link.bandwidth_words_per_cycle
            level_of[lv.link.name] = lv.name

    ics, load, witness = {}, {}, {}
    for f in flows:
        b = bw.get(f["level"])
        if not b or f["volume"] <= 0:
            continue
        lname = f.get("level_name") or level_of.get(f["level"])
        if lname is None:
            continue
        if lname not in ics:
            ics[lname] = ic_mod.build(fabric, lname, pl)
        nodes = f.get("nodes")                # node-to-node flow (D2D: die L->L+1)
        node = f.get("node")                  # hub-to-node flow (the on-die tree)
        icl = ics[lname]
        split = icl.duplex if duplex is None else bool(duplex)
        if nodes is not None:                 # one-directional hand-off a->b
            comps = [(f["volume"], nodes, float(f.get("width", 1.0)))]   # width: partial sums (O13 row split)
        elif node is not None:                # inputs down, partial sums up
            down = f.get("down", f["volume"])
            up = f.get("up", 0.0)
            comps = [(down, (ic_mod.HUB, node), 1.0),
                     (up, (node, ic_mod.HUB), psum)]
        else:                                 # flow not tagged: treat as private
            key = f"{lname}/flow:{f['src']}->{f['dst']}"
            load[key] = load.get(key, 0.0) + f["volume"]
            witness.setdefault(key, (f["level"], f["src"], f["dst"], ""))
            continue
        for vol, (a, b), weight in comps:
            if vol <= 0:
                continue
            for r, tag in icl.path_directed(a, b):
                key = f"{lname}/{r}" + (f"/{tag}" if split and tag else "")
                load[key] = load.get(key, 0.0) + vol * weight
                witness.setdefault(key, (f["level"], f["src"], f["dst"],
                                         tag if split else ""))

    per_link = []
    for r, vol in load.items():
        lname = r.split("/", 1)[0]
        link_name = fabric.level(lname).link.name
        lv_bw = bw[link_name]
        lvl, src, dst, tag = witness[r]
        per_link.append({"level": lvl, "resource": r, "direction": tag,
                         "volume": vol,
                         "seconds": vol / lv_bw * cycle_seconds,
                         "src": src, "dst": dst})
    worst = max(per_link, key=lambda x: x["seconds"], default=None)
    return {"per_link": per_link,
            "serialization_s": worst["seconds"] if worst else 0.0,
            "bottleneck": worst}


# --------------------------------------------------------------------------
DEFAULT_COMM_DIR = "/home/workspace/analysis/comm"


def save_flows(output_dir, tag="layer", dest_dir=DEFAULT_COMM_DIR, verbose=False,
               fabric=None, placement=None):
    """Persist the DETAILED per-pair communication data for one run to files
    (the aggregate stats.txt is overwritten by the next run, so we snapshot here).

    Writes two files under dest_dir, named by `tag`:
      <tag>_comm.csv  -- one row per pairwise link (node<->node): level, src, dst,
                         volume (words), distance (hops), volume*distance.
      <tag>_comm.json -- structured: hierarchy shape, all flows, per-crossbar cost,
                         and the min/max/ratio position spread summary.
    Returns (csv_path, json_path). Safe to call after any die-hierarchy run.
    """
    flows, per_xb, gshape, xb_coord = build_flows(output_dir, tag, verbose=verbose,
                                                  fabric=fabric, placement=placement)
    os.makedirs(dest_dir, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", tag)  # qk^t -> qk_t

    csv_path = os.path.join(dest_dir, f"{safe}_comm.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["level", "src", "dst", "volume_words", "distance_hops",
                    "volume_x_distance"])
        for fl in flows:
            w.writerow([fl["level"], fl["src"], fl["dst"], int(round(fl["volume"])),
                        round(fl["distance"], 3), round(fl["volume"] * fl["distance"], 3)])

    per_xb = np.asarray(per_xb, dtype=float)
    payload = {
        "tag": tag,
        "grid_shape": [int(gshape[0]), int(gshape[1])],
        "n_crossbars": int(len(per_xb)),
        "n_flows": len(flows),
        "per_crossbar_cost": {
            "min": float(per_xb.min()), "max": float(per_xb.max()),
            "max_over_min": float(per_xb.max() / max(per_xb.min(), 1)),
        },
        "flows": [{"level": fl["level"], "src": fl["src"], "dst": fl["dst"],
                   "volume_words": float(fl["volume"]),
                   "distance_hops": float(fl["distance"])} for fl in flows],
        "per_crossbar": [{"id": gid, "x": float(xb_coord[gid][0]),
                          "y": float(xb_coord[gid][1]),
                          "cost_vol_x_path": float(per_xb[gid])}
                         for gid in range(len(per_xb))],
    }
    json_path = os.path.join(dest_dir, f"{safe}_comm.json")
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    return csv_path, json_path


# --------------------------------------------------------------------------
def summarize_and_plot(output_dir, layer_name="", out_png=None, fabric=None,
                       placement=None):
    flows, per_xb, gshape, xb_coord = build_flows(output_dir, layer_name,
                                                  fabric=fabric, placement=placement)

    # per-level aggregate traffic*distance (the pairwise-link cost by level)
    print("\n-- per-level pairwise-link cost (volume x distance) --")
    by_level = {}
    for f in flows:
        by_level.setdefault(f["level"], [0.0, 0.0])
        by_level[f["level"]][0] += f["volume"]
        by_level[f["level"]][1] += f["volume"] * f["distance"]
    print(f"  {'level':<18}{'total volume':>16}{'volume x distance':>20}")
    for lv, (vol, vd) in by_level.items():
        print(f"  {lv:<18}{vol:>16,.0f}{vd:>20,.0f}")

    # per-crossbar position-dependent cost (over ACTIVE crossbars; idle = 0)
    act = per_xb[per_xb > 0]
    lo, hi = (act.min(), act.max()) if len(act) else (0.0, 0.0)
    print("\n-- per-crossbar communication cost (volume x path-to-glb) --")
    print(f"  active {len(act)}/{len(per_xb)}   min = {lo:,.0f}   max = {hi:,.0f}"
          f"   max/min = {hi/max(lo,1):.2f}x")
    print("  (structured volumes: multicast attributed by share, idle "
          "crossbars zero -- position AND volume both vary)")

    if out_png is None:
        out_png = "/home/workspace/analysis/crossbar_comm_heatmap.png"
    _plot_heatmap({g: (xb_coord[g], per_xb[g]) for g in xb_coord},
                  gshape, fabric, layer_name, out_png)
    return flows, per_xb


def _plot_heatmap(cost_by_gid, gshape, fabric, layer_name, out_png):
    """Draw the floorplan heatmap. cost_by_gid: {gid: ((x, y), cost)}."""
    gx, gy = gshape
    grid = np.full((gy, gx), np.nan)
    for gid, ((x, y), cost) in cost_by_gid.items():
        grid[int(y), int(x)] = cost
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    # YlOrRd (light yellow -> dark red) deliberately avoids pure white and pure
    # black at the extremes, so the black hierarchy separators stay visible on
    # every cell. Semantics: DARKER = more expensive. Empty slots render gray.
    cmap = plt.cm.YlOrRd.copy()
    cmap.set_bad(color="#9aa0a6")
    # canvas follows the grid's aspect ratio (a 12x24 die must not be squashed
    # into a landscape frame)
    cell = 0.42
    plt.figure(figsize=(max(gx * cell + 2.8, 6.0), max(gy * cell + 1.6, 4.0)))
    im = plt.imshow(grid, cmap=cmap, origin="lower", aspect="equal")
    plt.colorbar(im, label="comm cost (volume x distance)", fraction=0.046, pad=0.06)

    # all three hierarchy levels get separators, by weight:
    # macro borders thick, core borders medium, crossbar borders hairline.
    from scripts import fabric as fabric_mod
    fb = fabric or fabric_mod.default()
    lm, lc, lx = _on_die_levels(fb)[-3:]
    core_w, core_h = lx.mesh                                  # one core block
    macro_w, macro_h = lc.mesh[0] * core_w, lc.mesh[1] * core_h
    ax = plt.gca()
    for step, lw in ((1, 0.25), (core_w, 1.0), (macro_w, 2.5)):
        for x in range(step, gx, step):
            ax.axvline(x - 0.5, color="k", lw=lw)
    for step, lw in ((1, 0.25), (core_h, 1.0), (macro_h, 2.5)):
        for y in range(step, gy, step):
            ax.axhline(y - 0.5, color="k", lw=lw)

    ax.set_title(f"{layer_name} per-crossbar communication cost\n"
                 "borders: thick=macro / medium=core / hairline=crossbar\n"
                 "darker = costlier position; gray = empty slot", fontsize=10)
    plt.xlabel("crossbar x"); plt.ylabel("crossbar y")
    plt.tight_layout(); plt.savefig(out_png, dpi=120); plt.close()
    print(f"\nPNG  -> {out_png}")


def replot_heatmap(json_path, out_png, fabric=None):
    """Re-render the heatmap from a saved comm dump (analysis/comm/*_comm.json)
    WITHOUT re-simulating -- style iterations cost seconds, not mapper minutes.
    The dump must come from the same fabric the borders are drawn for."""
    with open(json_path) as f:
        d = json.load(f)
    cost_by_gid = {p["id"]: ((p["x"], p["y"]), p["cost_vol_x_path"])
                   for p in d["per_crossbar"]}
    _plot_heatmap(cost_by_gid, tuple(d["grid_shape"]), fabric,
                  d.get("tag", "layer"), out_png)
