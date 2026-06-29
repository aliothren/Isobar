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


# --------------------------------------------------------------------------
def build_flows(output_dir, layer_name=""):
    """Return (flows, per_crossbar_cost, grid_shape, xb_coord).

    flows: list of dicts {level, src, dst, volume, distance} -- the pairwise links.
    per_crossbar_cost: array[n_crossbars] of volume*distance summed along its path
                       (input down + output up) -> the position-dependent cost.
    """
    r = cbs.report(output_dir, layer_name)  # also prints the aggregate report
    nM = r["n_macros"]
    cores_per_macro = r["n_cores"] // nM
    xbars_per_core = r["n_crossbars"] // r["n_cores"]
    nX = r["n_crossbars"]

    # per-crossbar in/out volumes (words). Inputs are multicast DOWN, outputs UP.
    stats_path = os.path.join(output_dir, "timeloop-mapper.stats.txt")
    txt = open(stats_path).read()
    in_per_xb = cbs._per_tensor_volume(txt, "row_drivers") / nX
    out_per_xb = cbs._per_tensor_volume(txt, "adc") / nX

    xb_coord, core_coord, macro_coord, die_coord, gshape = \
        nested_floorplan(nM, cores_per_macro, xbars_per_core)

    flows = []
    per_xb = np.zeros(nX)

    gid = 0
    for m in range(nM):
        mc = macro_coord[m]
        # glb(die) <-> macro : carries the whole subtree's traffic
        subtree_xbars = cores_per_macro * xbars_per_core
        vol_m = (in_per_xb + out_per_xb) * subtree_xbars
        d = _manh(die_coord, mc)
        flows.append({"level": "glb<->macro", "src": "glb", "dst": f"macro{m}",
                      "volume": vol_m, "distance": d})
        for c in range(cores_per_macro):
            cc = core_coord[(m, c)]
            vol_c = (in_per_xb + out_per_xb) * xbars_per_core
            dc = _manh(mc, cc)
            flows.append({"level": "macro<->core", "src": f"macro{m}",
                          "dst": f"core{m}.{c}", "volume": vol_c, "distance": dc})
            for x in range(xbars_per_core):
                xc = xb_coord[gid]
                vol_x = in_per_xb + out_per_xb
                dx = _manh(cc, xc)
                flows.append({"level": "core<->crossbar", "src": f"core{m}.{c}",
                              "dst": f"xb{gid}", "volume": vol_x, "distance": dx})
                # this crossbar's position-dependent cost = volume * full path length
                path = _manh(xc, cc) + _manh(cc, mc) + _manh(mc, die_coord)
                per_xb[gid] = vol_x * path
                gid += 1
    return flows, per_xb, gshape, xb_coord


# --------------------------------------------------------------------------
def summarize_and_plot(output_dir, layer_name="", out_png=None):
    flows, per_xb, gshape, xb_coord = build_flows(output_dir, layer_name)

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

    # per-crossbar position-dependent cost
    print("\n-- per-crossbar communication cost (volume x path-to-glb) --")
    print(f"  min  = {per_xb.min():,.0f}   max = {per_xb.max():,.0f}"
          f"   max/min = {per_xb.max()/max(per_xb.min(),1):.2f}x")
    print(f"  (same per-crossbar VOLUME everywhere, but cost varies {per_xb.max()/max(per_xb.min(),1):.1f}x "
          "by POSITION -- the crossbar-aware effect)")

    # heatmap of the crossbar floorplan colored by communication cost
    gx, gy = gshape
    grid = np.full((gy, gx), np.nan)
    for gid, (x, y) in xb_coord.items():
        grid[int(y), int(x)] = per_xb[gid]
    if out_png is None:
        out_png = os.path.join(os.path.dirname(output_dir.rstrip("/")),
                               "..", "analysis", f"crossbar_comm_{layer_name or 'layer'}.png")
        out_png = "/home/workspace/analysis/crossbar_comm_heatmap.png"
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.figure(figsize=(10, 4))
    im = plt.imshow(grid, cmap="hot", origin="lower", aspect="auto")
    plt.colorbar(im, label="comm cost (volume x distance)")
    plt.title(f"{layer_name} per-crossbar communication cost on the floorplan\n"
              "(blocks = macros/cores; brighter = costs more by position)")
    plt.xlabel("crossbar x"); plt.ylabel("crossbar y")
    plt.tight_layout(); plt.savefig(out_png, dpi=120); plt.close()
    print(f"\nPNG  -> {out_png}")
    return flows, per_xb
