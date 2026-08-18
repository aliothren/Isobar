"""
Placement / topology-aware cost overlay for CiMLoop.

Motivation
----------
CiMLoop (Timeloop) models communication TOPOLOGICALLY: it counts how much data
crosses each hierarchy boundary (multicast / reduction / link), but it treats
all instances of a component as physically interchangeable -- there are no
coordinates and no notion of "how far" two communicating instances are. So a
mapping that spreads data across physically-distant tiles costs the same as one
that keeps it local.

This module adds a thin, DECOUPLED layer on top of an existing CiMLoop run:

    perceive(stats) -> placement(prior) -> distance -> re-aggregate

It does NOT modify Timeloop's mapper or energy model. It reads the per-component
data-movement that CiMLoop already produced, assigns physical coordinates to the
instances (a placement prior), computes a distance for each communication event,
and reports a position-aware communication cost alongside the position-blind
baseline.

Pipeline
--------
1. perceive():  parse timeloop-mapper.stats.txt for, per component:
       fanout        (number of spatial instances)
       volume        (total scalar accesses == data movement)
       unit_pJ       (energy per access)
2. placement:   assign (x, y) coordinates to the `fanout` instances
                (place_grid is the default prior; swap in others to explore).
3. distance:    avg_hops() -- representative Manhattan distance for a
                reduction/multicast-to-center pattern.
4. overlay:     position_aware_comm = baseline_comm * avg_hops * hop_scale,
                where hop_scale comes from the LAYOUT config (per-level physical
                cost, e.g. cheap on-die NoC vs expensive die-to-die link).

Only components that have BOTH spatial fanout (>1) AND nonzero per-access energy
are affected -- in practice the interconnect components (e.g. `router`). The
zero-energy `inter_*_spatial` network markers and single-instance buffers
(glb, main_memory) are left at baseline.

This is a first prototype: the communication pattern is assumed
reduction/multicast-to-center, distance is average Manhattan, and the topology
is a 2D mesh. All of these are pluggable (see TODOs at the bottom).
"""

import os
import re
import math
from typing import Callable, Dict, List, Tuple

STATS_FILENAME = "timeloop-mapper.stats.txt"


# ---------------------------------------------------------------------------
# 1. Perceive: extract per-component (fanout, volume, unit_energy) from stats
# ---------------------------------------------------------------------------
def perceive(stats_path: str) -> Dict[str, dict]:
    """Parse a Timeloop stats.txt into
    {component_name: {fanout, unit_pJ, volume, energy_J}}.

    `energy_J` is the component's OWN reported energy, summed over its dataspaces
    (the `Energy (total)` lines). This is the position-blind communication energy the
    simulator actually charges, and it is what the distance overlay must scale.

    NOTE: do NOT reconstruct it as `volume * unit_pJ`. `Total scalar accesses` and
    `Vector access energy` are in different units -- the latter is per VECTOR access
    (Block size scalars, 128 for the router), and the scalar-access total aggregates
    dataspaces/encodings that do not all drive that energy. Multiplying the two
    overstates the real figure by ~3 orders of magnitude.
    """
    with open(stats_path, "r") as f:
        text = f.read()

    # A component's name heads TWO sections: the main body (Instances, Vector
    # access energy, per-dataspace Energy lines) and a trailing summary block
    # (Total scalar accesses). MERGE fields across same-name sections -- taking
    # only one section silently zeroes the other's fields.
    levels: Dict[str, dict] = {}
    parts = re.split(r"=== (\w+) ===", text)   # [pre, name1, body1, name2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        name, body = parts[i], parts[i + 1]
        e = levels.setdefault(name, {"fanout": 0, "unit_pJ": 0.0,
                                     "volume": 0, "energy_J": 0.0})
        inst = re.search(r"Instances\s*:\s*(\d+)", body)
        if inst:
            e["fanout"] = int(inst.group(1))
        ue = re.search(r"Vector access energy\s*:\s*([\d.eE+-]+)\s*pJ", body)
        if ue:
            e["unit_pJ"] = float(ue.group(1))
        vol = re.search(r"Total scalar accesses\s*:\s*(\d+)", body)
        if vol:
            e["volume"] = int(vol.group(1))
        # per-dataspace "Energy (total)" lines (exclude Temporal Reduction / Address
        # Generation variants, which do not start the line with "Energy (total)")
        e["energy_J"] += 1e-12 * sum(float(x) for x in re.findall(
            r"^\s*Energy \(total\)\s*:\s*([\d.eE+-]+)\s*pJ", body, re.M))
    # keep only real components (appeared in a main SPECS section)
    return {n: v for n, v in levels.items() if v["fanout"] > 0}


def perceive_result(result) -> Dict[str, dict]:
    """Convenience: perceive() from a run_mapper/run_layer result that carries
    `.output_dir` (requires the one-line patch in utils.run_mapper)."""
    if not getattr(result, "output_dir", None):
        raise ValueError(
            "result has no .output_dir -- patch run_mapper to set "
            "stats.output_dir = output_dir, and parse before the next run."
        )
    return perceive(os.path.join(result.output_dir, STATS_FILENAME))


# ---------------------------------------------------------------------------
# 2. Placement priors: assign coordinates to `n` instances
# ---------------------------------------------------------------------------
def place_grid(n: int) -> List[Tuple[float, float]]:
    """Default prior: near-square 2D mesh, row-major."""
    side = math.ceil(math.sqrt(n))
    return [(i % side, i // side) for i in range(n)]


def place_linear(n: int) -> List[Tuple[float, float]]:
    """Pessimistic prior: all instances on one line (unoptimized layout)."""
    return [(i, 0.0) for i in range(n)]


# (TODO: place_locality(...) -- cluster instances that communicate heavily.)


# ---------------------------------------------------------------------------
# 3. Distance model
# ---------------------------------------------------------------------------
def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# --- communication-pattern models: coords -> representative hops PER transfer ---
# Each returns an average hop count (>=1) so that
#     position_aware_energy = baseline_energy * hops * hop_scale
# stays comparable across patterns. We do NOT yet know the real topology, so
# these are PLUGGABLE: pick one per component in LAYOUT, or register your own.

def hops_to_center(coords):
    """Reduction-to-center / multicast-from-center: every instance talks to a
    single central point. hops = avg Manhattan distance to the centroid."""
    if len(coords) <= 1:
        return 1.0
    cx = sum(x for x, _ in coords) / len(coords)
    cy = sum(y for _, y in coords) / len(coords)
    return max(1.0, sum(_manhattan(c, (cx, cy)) for c in coords) / len(coords))


def hops_tree(coords):
    """Reduction TREE: hierarchical pairwise merge. hops = avg distance per
    merge step (cheaper than to-center for large fanout)."""
    pts = list(coords)
    total, n_merges = 0.0, 0
    while len(pts) > 1:
        nxt = []
        for i in range(0, len(pts) - 1, 2):
            total += _manhattan(pts[i], pts[i + 1]); n_merges += 1
            nxt.append(((pts[i][0] + pts[i + 1][0]) / 2,
                        (pts[i][1] + pts[i + 1][1]) / 2))
        if len(pts) % 2:
            nxt.append(pts[-1])
        pts = nxt
    return max(1.0, total / max(n_merges, 1))


def hops_all_to_all(coords):
    """All-to-all: every instance talks to every other. hops = avg pairwise
    Manhattan distance (worst case, e.g. unstructured exchange)."""
    n = len(coords)
    if n <= 1:
        return 1.0
    total = sum(_manhattan(coords[i], coords[j])
                for i in range(n) for j in range(i + 1, n))
    return max(1.0, total / (n * (n - 1) / 2))


def hops_neighbor(coords):
    """Nearest-neighbor / mesh-local: only adjacent instances communicate."""
    return 1.0


# Registry: name -> model. Add your own with DISTANCE_MODELS["foo"] = fn.
DISTANCE_MODELS = {
    "to_center": hops_to_center,   # reduction/multicast via a hub (default)
    "tree":      hops_tree,        # hierarchical reduction tree
    "all_to_all": hops_all_to_all, # unstructured all-to-all exchange
    "neighbor":  hops_neighbor,    # mesh-local nearest-neighbor
}

# Back-compat alias.
avg_hops = hops_to_center


# ---------------------------------------------------------------------------
# 4. Overlay: position-aware communication cost
# ---------------------------------------------------------------------------
# Name hints that identify an INTERCONNECT / network component (the only thing
# physical distance acts on). Compute units (cim_unit, adc, dac, integrator,
# sample, shift_add), drivers, and storage (buffers, glb, main_memory) are NOT
# interconnect -- distance must NOT scale their energy.
_INTERCONNECT_HINTS = ("router", "link", "noc", "network")


def _is_comm_component(name: str, info: dict) -> bool:
    """True only for actual interconnect: the inter-level spatial networks
    (`inter_*_spatial`) or explicit interconnect components (router/link/NoC).
    Must also have spatial fanout (>1) and nonzero energy for the distance SCALE to
    mean anything (zero-energy `inter_*` markers contribute 0)."""
    name_l = name.lower()
    is_interconnect = name_l.startswith("inter_") or any(
        h in name_l for h in _INTERCONNECT_HINTS
    )
    return is_interconnect and info["fanout"] > 1 and info.get("energy_J", 0) > 0


def position_aware_cost(
    levels: Dict[str, dict],
    layout: Dict[str, dict] = None,
    place_fn: Callable[[int], List[Tuple[float, float]]] = place_grid,
    default_pattern: str = "to_center",
    default_reference_hops: float = 1.0,
    *,
    placement=None,
    fabric=None,
) -> dict:
    """
    Apply the placement/distance overlay to perceived communication components.

    Cost model (per interconnect component)
    ---------------------------------------
        baseline_comm = volume * per_word_energy        # what CiMLoop reports.
                                                         # CiMLoop has NO distance
                                                         # term: it is volume x a
                                                         # FIXED per-word energy
                                                         # (one router traversal),
                                                         # i.e. position-blind.
        position_aware = baseline_comm * (hops / reference_hops) * hop_scale

    The key, EXPLICIT assumption is `reference_hops` = how many hops the baseline
    per-word energy already represents:
      * reference_hops = 1  -> interpret CiMLoop's energy as a SINGLE hop /
                               router traversal (the model literally charges one
                               traversal). Then a multi-hop mesh costs `hops` x
                               more, and good vs bad placement is good<bad above
                               baseline. Use this if the real interconnect is a
                               multi-hop NoC and the per-word energy is one hop.
      * reference_hops = R  -> interpret CiMLoop's energy as the AVERAGE of an
                               R-hop transfer (already distance-inclusive). Then
                               good placement falls BELOW baseline and bad ABOVE.
                               Use this once you know what the router energy was
                               calibrated to (ask the hardware team / inspect the
                               component model).

    This must be pinned down before the absolute multipliers are trustworthy;
    the RELATIVE good-vs-bad placement comparison is robust either way.

    Args:
        levels:   output of perceive().
        layout:   {component_name: {"pattern": str, "hop_scale": float,
                  "reference_hops": float, ...}} -- from the hardware layout spec.
        place_fn: placement prior mapping instance-count -> coordinates.
        default_pattern / default_reference_hops: used when not set per-component.

    Returns dict with rows, baseline, position_aware, ratio (see print_report).
    """
    layout = layout or {}

    # Coordinates per component. With an explicit (placement, fabric), a
    # component that a fabric link claims (link.cimloop_component) uses that
    # level's SLOT table -- per-level grid units, matching reference_hops
    # semantics ("one hop of this link"). Do NOT feed global leaf-grid
    # centroids here: their pitch is larger and would silently inflate the
    # distance term. Components no fabric link claims (e.g. phase-1 archs)
    # keep the place_fn PRIOR -- that is place_fn's remaining role.
    comp_level = {}
    if placement is not None and fabric is not None:
        placement.verify(fabric)
        comp_level = {lv.link.cimloop_component: lv.name
                      for lv in fabric.levels
                      if lv.link is not None and lv.link.cimloop_component}

    def mean_hops_for(name, fanout, hops_fn):
        """Mean hub->node distance in the level's slot units.

        For a fabric-backed component the level's SCHEME supplies it
        (`topology:` in the fabric config) -- topology supersedes the legacy
        `pattern` here, and `star` + to_center are the same quantity, so the
        default reproduces the pre-W2 value exactly. Components no fabric link
        claims (e.g. the phase-1 arch) keep the place_fn + pattern prior, which
        is the only coordinate source they have.
        """
        lvl = comp_level.get(name)
        if lvl is None:
            return hops_fn(place_fn(fanout))
        slots = placement.slots[lvl]
        if len(slots) != fanout:
            raise ValueError(
                f"{name}: stats fanout {fanout} != {lvl} slots {len(slots)} -- "
                "fabric config and run diverged")
        from scripts import interconnect as ic_mod
        return ic_mod.build(fabric, lvl, placement).mean_hops()

    rows = []
    tot_base = tot_pa = 0.0
    for name, info in levels.items():
        if not _is_comm_component(name, info):
            continue
        cfg = layout.get(name, {})
        pattern = cfg.get("pattern", default_pattern)
        hops_fn = DISTANCE_MODELS.get(pattern, hops_to_center)
        ref_hops = max(cfg.get("reference_hops", default_reference_hops), 1e-9)
        hop_scale = cfg.get("hop_scale", 1.0)

        base = info["energy_J"]          # the simulator's own position-blind energy
        hops = mean_hops_for(name, info["fanout"], hops_fn)
        pa = base * (hops / ref_hops) * hop_scale
        rows.append((name, info["fanout"], base, hops / ref_hops, pa))
        tot_base += base
        tot_pa += pa
    return {
        "rows": rows,
        "baseline": tot_base,
        "position_aware": tot_pa,
        "ratio": (tot_pa / tot_base) if tot_base > 0 else 1.0,
    }


# ---------------------------------------------------------------------------
# 5. Distance LATENCY overlay (propagation time, the analogue of the energy
#    overlay above). Energy SUMS over all flows; latency is a CRITICAL PATH:
#    within a tree level the branches are parallel -> the longest one (max hops)
#    sets the path; across levels the path is in series -> sum. The output
#    reduction mirrors the input multicast, so total = 2 * the down path.
#
#    This is the term Timeloop does NOT model: its cycles already include the
#    bandwidth/transfer time (V/B stalls), but it is position-blind, so the
#    per-hop PROPAGATION (hops x hop_latency_ns) is missing. We add only that.
# ---------------------------------------------------------------------------
def position_aware_latency(level_hops: Dict[str, float],
                           hop_latency_ns: Dict[str, float],
                           default_ns: float = 1.0) -> dict:
    """Propagation latency (ns) from per-level hop counts + per-level hop latency.

    Args:
        level_hops:     {level: max Manhattan hops} (crossbar_comm.level_max_hops).
        hop_latency_ns: {level: ns per hop} (mlx_system.HOP_LATENCY_NS).
        default_ns:     fallback hop latency for an unlisted level.

    Returns {down_ns, up_ns, total_ns, per_level_ns}. total_ns is what you add
    (serially) to an op's compute latency.
    """
    per_level = {lv: h * hop_latency_ns.get(lv, default_ns)
                 for lv, h in level_hops.items()}
    down = sum(per_level.values())          # series along the multicast path
    return {"down_ns": down, "up_ns": down, "total_ns": 2 * down,
            "per_level_ns": per_level}


def print_report(res: dict, title: str = ""):
    """Pretty-print a position_aware_cost() result."""
    if title:
        print(f"\n===== {title} =====")
    print(f"{'component':<34}{'fanout':>8}{'baseline(J)':>14}"
          f"{'avg_hops':>10}{'pos-aware(J)':>14}")
    for name, fo, base, hops, pa in res["rows"]:
        print(f"{name:<34}{fo:>8}{base:>14.3e}{hops:>10.2f}{pa:>14.3e}")
    print(f"{'--- communication total ---':<34}{'':>8}"
          f"{res['baseline']:>14.3e}{'':>10}{res['position_aware']:>14.3e}")
    print(f"position-aware / baseline = {res['ratio']:.2f}x")


# ---------------------------------------------------------------------------
# TODOs to make this less of a first-cut approximation
# ---------------------------------------------------------------------------
# - Communication pattern: patterns are now PLUGGABLE (DISTANCE_MODELS, chosen
#   per component via LAYOUT["..."]["pattern"]). Still TODO: AUTO-DETECT the real
#   pattern (multicast/reduction/unicast) from the container's
#   spatial_must_reuse_* constraint or map+stats.xml, instead of configuring it
#   by hand. Confirm the actual on-chip topology with the hardware team.
# - Placement: add locality-aware priors and (later) an outer search/agent that
#   optimizes placement using this cost as the objective.
# - Latency: also overlay a hop-latency term (hop_latency_ns in LAYOUT), not just
#   energy.
# - Layout source: read hop_scale / topology from the architecture spec itself
#   (declarative hardware layout) rather than a separate dict.
