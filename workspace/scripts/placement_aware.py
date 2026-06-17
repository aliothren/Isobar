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
    """Parse a Timeloop stats.txt into {component_name: {fanout, unit_pJ, volume}}."""
    with open(stats_path, "r") as f:
        text = f.read()

    levels: Dict[str, dict] = {}
    # SPECS block: instance count + per-access energy
    for m in re.finditer(
        r"=== (\w+) ===\n.*?Instances\s*:\s*(\d+)"
        r".*?Vector access energy\s*:\s*([\d.eE+-]+)\s*pJ",
        text,
        re.DOTALL,
    ):
        name, inst, ue = m.group(1), int(m.group(2)), float(m.group(3))
        levels[name] = {"fanout": inst, "unit_pJ": ue, "volume": 0}
    # STATS block: total scalar accesses (data-movement volume)
    for m in re.finditer(
        r"=== (\w+) ===\s*\n\s*Total scalar accesses\s*:\s*(\d+)", text
    ):
        if m.group(1) in levels:
            levels[m.group(1)]["volume"] = int(m.group(2))
    return levels


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
def avg_hops(coords: List[Tuple[float, float]]) -> float:
    """Average Manhattan distance from the centroid -- a representative hop count
    for a reduction-to-center / multicast-from-center communication pattern."""
    if len(coords) <= 1:
        return 1.0
    cx = sum(x for x, _ in coords) / len(coords)
    cy = sum(y for _, y in coords) / len(coords)
    return max(1.0, sum(abs(x - cx) + abs(y - cy) for x, y in coords) / len(coords))


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
    Must also have spatial fanout (>1) and nonzero per-access energy for the
    distance SCALE to mean anything (zero-energy `inter_*` markers contribute 0)."""
    name_l = name.lower()
    is_interconnect = name_l.startswith("inter_") or any(
        h in name_l for h in _INTERCONNECT_HINTS
    )
    return is_interconnect and info["fanout"] > 1 and info["unit_pJ"] > 0


def position_aware_cost(
    levels: Dict[str, dict],
    layout: Dict[str, dict] = None,
    place_fn: Callable[[int], List[Tuple[float, float]]] = place_grid,
) -> dict:
    """
    Apply the placement/distance overlay to perceived components.

    Args:
        levels:   output of perceive().
        layout:   {component_name: {"hop_scale": float, ...}} -- per-level
                  physical cost from the hardware layout spec. Default scale 1.0.
        place_fn: placement prior mapping instance-count -> coordinates.

    Returns dict with:
        rows:           list of (name, fanout, baseline_J, avg_hops, position_aware_J)
        baseline:       sum of baseline communication energy (position-blind)
        position_aware: sum of position-aware communication energy
        ratio:          position_aware / baseline
    """
    layout = layout or {}
    rows = []
    tot_base = tot_pa = 0.0
    for name, info in levels.items():
        if not _is_comm_component(name, info):
            continue
        base = info["volume"] * info["unit_pJ"] * 1e-12  # Joules, position-blind
        hops = avg_hops(place_fn(info["fanout"]))
        hop_scale = layout.get(name, {}).get("hop_scale", 1.0)
        pa = base * hops * hop_scale
        rows.append((name, info["fanout"], base, hops, pa))
        tot_base += base
        tot_pa += pa
    return {
        "rows": rows,
        "baseline": tot_base,
        "position_aware": tot_pa,
        "ratio": (tot_pa / tot_base) if tot_base > 0 else 1.0,
    }


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
# - Communication pattern: distinguish multicast / reduction / unicast from the
#   container's spatial_must_reuse_* constraint (or parse map+stats.xml), instead
#   of assuming reduction-to-center for everything.
# - Placement: add locality-aware priors and (later) an outer search/agent that
#   optimizes placement using this cost as the objective.
# - Latency: also overlay a hop-latency term (hop_latency_ns in LAYOUT), not just
#   energy.
# - Layout source: read hop_scale / topology from the architecture spec itself
#   (declarative hardware layout) rather than a separate dict.
