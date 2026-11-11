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

from scripts import crossbar_stats as cbs
from scripts import paths


def _manh(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def level_max_hops(fabric=None, placement=None):
    """The WORST-case Manhattan hop count at each on-die tree level, computed
    from the ACTUAL placement (defaults: the nested row-major floorplan).

    Used by the distance-LATENCY overlay: within a level all branches are
    parallel, so the longest branch (max hops) sets the critical path; across
    levels the path is in series (summed by position_aware_latency).
    Returns {link_name: max_hops}; the keys are the fabric links' names, which
    match HOP_LATENCY_NS. Hops are in GLOBAL leaf-grid units (12 / 3 / 2 for
    the reference die) -- do not mix with the per-level slot units the energy
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

    model="structured" (default): edge volumes from the mapping's real
    multicast/reduction structure via traffic.extract -- a multicast slice
    crosses an upper edge ONCE, idle instances carry zero.
    model="uniform": the total divided evenly over the N instances, a
    comparison baseline only; not a fallback.
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
        # the two DIRECTIONS kept apart: inputs go down, outputs
        # (partial sums) come up
        vol_dn = {lv: ev[lv]["in"] for lv in (lvl_m.name, lvl_c.name, lvl_x.name)}
        vol_up = {lv: ev[lv]["out"] for lv in (lvl_m.name, lvl_c.name, lvl_x.name)}
        if len(fanouts) == 4:
            vol_edge["die"] = ev["die"]["in"] + ev["die"]["out"]
            vol_dn["die"], vol_up["die"] = ev["die"]["in"], ev["die"]["out"]
    elif model == "uniform":
        ts_u = traffic.extract(output_dir, fab, stats_text=txt)   # value units
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
    # global leaf grid by that level's pitch. `star` gives the centroid
    # Manhattan distances of the nested floorplan exactly.
    from scripts import interconnect as ic_mod
    ics = {lv.name: ic_mod.build(fab, lv.name, pl) for lv in (lvl_m, lvl_c, lvl_x)}
    # flow distances are ENERGY-attribution quantities (they feed
    # the overlay column, the per-crossbar maps and the vol x dist dumps;
    # no latency consumer reads them) -- so they carry the energy wire
    # length: == hops for star/mesh, the full line for a bus.
    d_of = {lv.name: [ics[lv.name].energy_hops(ic_mod.HUB, i) * fab.pitch(lv.name)
                      for i in range(lv.per_parent)]
            for lv in (lvl_m, lvl_c, lvl_x)}

    flows = []
    per_xb = np.zeros(nX)

    # Intra-op die-level flows (spatial_multi_die): the op's slices live on
    # f_d dies; each die's edge carries its unique input slice down and its
    # (un-merged) outputs up, exactly like every tree level below; the
    # anchor is the die scheme's hub (the package attach point). The on-die tree flows
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
                          "distance": ic_die.energy_hops(ic_mod.HUB, d)})

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
                   duplex=None, psum_bytes=None, schedule_slack=None):
    """Static contention: per-RESOURCE occupancy time from the structured flows.

    What the number IS: for the given routing -- which wires each
    flow occupies is fixed by the scheme and the placement -- any schedule, a
    compile-time one included, spends at least volume / bandwidth on each
    wire. The busiest wire's occupancy is therefore the least serialization
    ANY schedule can reach: exact for private links (nothing shared) and for
    a shared bus (one resource, any work-conserving arbitration reaches it),
    a lower bound for a routed grid or tree, where the missing piece is
    queueing / arbitration of the flows that share a segment. Re-routing
    changes the per-wire volumes and is a search move, not a refinement of
    this number. A schedule that cannot reach the bound is expressed by the
    fabric's `schedule_slack` (>= 1, platform input; `schedule_slack=`
    overrides it), which multiplies every occupancy below.

    Direction and width: a flow's DOWN component (inputs, 8-bit
    activations) and UP component (outputs = partial sums) are routed
    separately. On a full-duplex scheme (every point-to-point scheme; a bus
    is a shared medium) the two directions occupy different wires, so the
    resource key carries a direction tag. The up component is weighted by
    `psum_bytes` (default: the fabric's `psum_word_bytes`, 2.0 = 16-bit
    partial sums) because partial sums are wider than activations.
    `duplex=False` / `psum_bytes=1.0` charge both directions to one wire and
    everything at activation width (for comparison only). Node-to-node flows
    (`nodes:(a,b)`, the D2D hand-offs) are one-directional activations.

    Each flow is routed by its level's SCHEME onto the resources it occupies
    (`Interconnect.path`), and every resource accumulates the traffic of every
    flow that crosses it. With `star` each hub->node edge has a private link, so
    no two flows ever meet and this reduces exactly to the per-flow form.
    With `mesh` the routes overlap on shared segments, which is what finally
    couples PLACEMENT to contention.

    Level-agnostic by construction -- die-to-die flows (tagged with
    `"nodes": (a, b)` instead of a hub-side `"node"`) feed this same function;
    objective.handoff_flows produces them. Ownership rule: network links belong to this analytic tier
    (only it knows per-resource loads; Timeloop has aggregate views only), while
    storage hub bandwidth belongs to Timeloop's native throttling. The two
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
    slack = (getattr(fabric, "schedule_slack", 1.0) if schedule_slack is None
             else float(schedule_slack))

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
            comps = [(f["volume"], nodes, float(f.get("width", 1.0)))]   # width: 2 for partial sums of a row-split producer
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
                         "seconds": vol / lv_bw * cycle_seconds * slack,
                         "src": src, "dst": dst})
    worst = max(per_link, key=lambda x: x["seconds"], default=None)
    return {"per_link": per_link,
            "serialization_s": worst["seconds"] if worst else 0.0,
            "bottleneck": worst, "schedule_slack": slack}


# --------------------------------------------------------------------------
DEFAULT_COMM_DIR = os.path.join(paths.RESULTS, "comm")


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

