"""
Per-crossbar compute / communication statistics (crossbar-aware analysis).

Derives, from one CiMLoop run (the MLX die hierarchy), what a SINGLE crossbar
does and how much it communicates, plus the per-level bus traffic and the
communication STRUCTURE (which spatial levels multicast inputs vs reduce
outputs). This is the foundation for crossbar-aware placement/cost modeling.

What is DIRECT vs DERIVED (be honest):
  * Per-crossbar compute / I/O  : direct (total / number of crossbars). This is
    the per-crossbar AVERAGE -- Timeloop treats same-type instances symmetrically,
    so there is no per-instance variation to report.
  * Per-level bus traffic       : direct (Total scalar accesses per interconnect).
  * Communication structure     : derived from the mapping -- which workload dim
    is spread at each spatial level tells us multicast (distinct outputs, inputs
    shared) vs reduction (C/R/S summed) vs bit-slice.
  * Per-pair (crossbar->crossbar) traffic matrix is NOT produced here; it needs
    the structure below + a placement (see placement_aware.py). The structure +
    group sizes computed here are exactly the inputs for that next step.

Hierarchy markers (MLX die: die->macro->core->crossbar) -- the fanout of these
components gives the instance counts:
    router        -> one per macro      (n_macros)
    input_buffer  -> one per core       (n_cores)
    weight_drivers-> one per crossbar   (n_crossbars)
Adjust LEVEL_MARKERS if you rename levels.

Usage:
    from scripts import crossbar_stats as cbs
    cbs.report(result.output_dir)          # after run_mlx_layer(..., MLX_DIE_CONFIG)
"""
import os
import re
from scripts import placement_aware as pa

CIM_ROWS = 256
CIM_COLS = 256
WEIGHT_BITS_PER_CELL = 4

# component whose fanout == number of instances at each grouping level
LEVEL_MARKERS = {"macro": "router", "core": "input_buffer", "crossbar": "weight_drivers"}

# workload-dim -> communication meaning when that dim is SPATIAL at a level
DIM_CLASS = {
    "C": "reduction",   "R": "reduction",   "S": "reduction",   # MAC sum -> N->1
    "M": "distinct",    "P": "distinct",    "Q": "distinct",    "N": "distinct",  # inputs shared -> 1->N
    "X": "bit-slice",   "Y": "bit-slice",   "Z": "bit-slice",   # shift-add reduction
    "G": "distinct",
}


def _total_computes(stats_text):
    m = re.search(r"Computes\s*=\s*(\d+)", stats_text)
    return int(m.group(1)) if m else None


def _per_tensor_volume(stats_text, comp):
    """Total scalar accesses for one component (already summed over instances)."""
    m = re.search(rf"=== {comp} ===\s*\n\s*Total scalar accesses\s*:\s*(\d+)", stats_text)
    return int(m.group(1)) if m else 0


def parse_mapping_levels(mapping_text):
    """Return ordered list of (level_name, [(dim, factor, spatial_axis)]) for each
    inter_*_spatial level, i.e. the spatial tiling structure."""
    levels = []
    cur = None
    for line in mapping_text.splitlines():
        s = line.strip().strip("|").strip()
        m_lvl = re.match(r"(inter_\w+_spatial)\b", s)
        if m_lvl:
            cur = (m_lvl.group(1), [])
            levels.append(cur)
            continue
        m_loop = re.search(r"for (\w+) in \[0:(\d+)[^)]*\)\s*\(Spatial-([XY])\)", s)
        if m_loop and cur is not None:
            cur[1].append((m_loop.group(1), int(m_loop.group(2)), m_loop.group(3)))
    return levels


def hierarchy(output_dir):
    """Quiet: just the instance counts (n_macros / n_cores / n_crossbars) from a
    run, without printing the full report. Used by the auto-saved comm dump."""
    stats_path = os.path.join(output_dir, "timeloop-mapper.stats.txt")
    levels = pa.perceive(stats_path)
    def fanout(name):
        return levels.get(name, {}).get("fanout", 0)
    n_macros = fanout(LEVEL_MARKERS["macro"]) or 1
    n_cores = fanout(LEVEL_MARKERS["core"]) or 1
    n_crossbars = fanout(LEVEL_MARKERS["crossbar"]) or 1
    return {"n_macros": n_macros, "n_cores": n_cores,
            "n_crossbars": n_crossbars, "levels": levels}


def report(output_dir, layer_name=""):
    stats_path = os.path.join(output_dir, "timeloop-mapper.stats.txt")
    map_path = os.path.join(output_dir, "timeloop-mapper.map.txt")
    with open(stats_path) as f:
        stats_text = f.read()
    mapping_text = open(map_path).read() if os.path.exists(map_path) else ""

    levels = pa.perceive(stats_path)      # {name: {fanout, unit_pJ, volume, energy_J}}
    computes = _total_computes(stats_text)

    def fanout(name):
        return levels.get(name, {}).get("fanout", 0)

    n_macros = fanout(LEVEL_MARKERS["macro"]) or 1
    n_cores = fanout(LEVEL_MARKERS["core"]) or 1
    n_crossbars = fanout(LEVEL_MARKERS["crossbar"]) or 1

    print(f"\n================ CROSSBAR-AWARE REPORT {layer_name} ================")
    print(f"Hierarchy:  {n_macros} macros  x  {n_cores//max(n_macros,1)} cores/macro"
          f"  x  {n_crossbars//max(n_cores,1)} crossbars/core"
          f"   =  {n_crossbars} crossbars")

    # ---- per-crossbar compute & storage ----
    print("\n-- per CROSSBAR (average; instances are symmetric) --")
    if computes:
        print(f"  compute (1b-MACs)          : {computes/n_crossbars:,.0f}"
              f"   (total {computes:,})")
    print(f"  weight footprint           : {CIM_ROWS*CIM_COLS*WEIGHT_BITS_PER_CELL:,} bits"
          f"  ({CIM_ROWS}x{CIM_COLS} x {WEIGHT_BITS_PER_CELL}b)")

    # ---- per-crossbar I/O (from crossbar-level component volumes / n_crossbars) ----
    def per_crossbar(comp):
        return _per_tensor_volume(stats_text, comp) / n_crossbars
    print(f"  input words  (row_drivers) : {per_crossbar('row_drivers'):,.0f}")
    print(f"  weight writes(weight_drv)  : {per_crossbar('weight_drivers'):,.0f}")
    # output read-out happens per column; aggregate to per-crossbar
    adc_total = _per_tensor_volume(stats_text, "adc")
    print(f"  output reads (adc)         : {adc_total/n_crossbars:,.0f}")

    # ---- per-level bus traffic (direct) ----
    print("\n-- bus / interconnect traffic (whole layer, all instances) --")
    for comp in ["router", "glb", "main_memory"]:
        v = _per_tensor_volume(stats_text, comp)
        fo = fanout(comp) or 1
        tag = {"router": "inter-macro NoC", "glb": "on-die SRAM",
               "main_memory": "off-chip DRAM"}.get(comp, comp)
        print(f"  {comp:<12} ({tag:<16}) total={v:>14,}  per-instance={v//fo:>12,}")

    # ---- communication structure from the mapping ----
    print("\n-- communication structure per spatial level (from mapping) --")
    print(f"  {'level':<32}{'dims (factor)':<22}{'pattern'}")
    for lname, loops in parse_mapping_levels(mapping_text):
        if not loops:
            continue
        dims = " ".join(f"{d}={f}" for d, f, _ in loops)
        classes = {DIM_CLASS.get(d, "?") for d, _, _ in loops}
        if "reduction" in classes:
            patt = "REDUCTION (outputs summed N->1 across instances)"
        elif "distinct" in classes:
            patt = "distinct outputs / inputs shared (multicast 1->N)"
        else:
            patt = "bit-slice (shift-add reduction)"
        print(f"  {lname:<32}{dims:<22}{patt}")
    print("\n(Per-pair crossbar<->crossbar traffic = these groups + a placement;"
          " feed into placement_aware.)")
    return {"n_macros": n_macros, "n_cores": n_cores, "n_crossbars": n_crossbars,
            "computes": computes, "levels": levels}
