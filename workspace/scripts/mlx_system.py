"""
MLX-style CIM system model + position-aware runner.

This file pins down the hardware we are currently simulating and wires it to the
placement-aware overlay (placement_aware.py). It is the single place that:
  (1) documents how the company chip maps onto CiMLoop's hierarchy,
  (2) holds the (verified) CiMLoop level configuration + mapper hints,
  (3) holds the assumed physical LAYOUT (topology + per-hop cost), and
  (4) provides one call to run a layer and get baseline + position-aware cost.

=============================================================================
Company chip (preliminary draft specs -- some numbers UNCONFIRMED)
=============================================================================
    crossbar : 256 x 256, 4-bit weight (ReRAM)        -> CiMLoop macro = wan_nature_2022
    core     : ~2M, several crossbars + local buffers  -> CiMLoop tile  = input_output_bufs
    macro    : 4 cores                                 -\
    die/chip : 8 macros + 8M on-chip SRAM              -/-> CiMLoop chip = large_router_glb
    package  : 256 dies                                -> NOT modeled yet (top level ignored)

Notes / open questions (confirm with company):
  - "2M / 8M": bit or byte? (changes crossbars-per-core and total capacity)
  - die-to-die stacking / topology: unknown -> top package level skipped for now.
  - macro/core interconnect topology: assumed 2D mesh.

PHASE 1 (this file): reuse the *verified* CiMLoop levels
    macro = wan_nature_2022 (the 256x256 4-bit ReRAM crossbar)
    tile  = input_output_bufs (local input/output buffers + crossbars) ~= "core"
    chip  = large_router_glb  (8M-ish glb + router + tiles)            ~= "die"
    system= fetch_weights_lpddr4 (off-chip DRAM, weight-stationary -- natural for ReRAM)
  The on-die interconnect that distance acts on is the `router` component.

PHASE 2 (later): build exact die -> macro -> core -> crossbar arch.yaml levels,
  each carrying its own LAYOUT block (declarative physical layout in the spec).
=============================================================================
"""

import os
import sys

# Make `from scripts import ...` work regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

from scripts import utils as utl
from scripts import placement_aware as pa


# ---------------------------------------------------------------------------
# Phase-1 hardware configuration (verified to run; see module docstring)
# ---------------------------------------------------------------------------
MLX_CONFIG = dict(
    macro="wan_nature_2022",        # 256x256 4-bit ReRAM crossbar
    tile="input_output_bufs",       # ~ "core": local I/O buffers + crossbars
    chip="large_router_glb",        # ~ "die": glb + router (on-die NoC) + tiles
    system="fetch_weights_lpddr4",  # off-chip DRAM, weight-stationary
)

# Number of spatial instances at each grouping level (mapper sees these as
# available parallelism; it uses as many as a layer needs).
N_ROUTER_GROUPS = 64   # shared_router_group.meshX
N_TILES_IN_CHIP = 16   # tile_in_chip.meshX


def mlx_callfunc(spec):
    """Size the on-die interconnect/tiles and relax a couple of default
    constraints (mirrors the verified wang full-system setup)."""
    srg = spec.architecture.find("shared_router_group")
    srg.spatial.meshX = N_ROUTER_GROUPS
    srg.attributes.has_power_gating = True
    srg.constraints.spatial.no_reuse = []

    tic = spec.architecture.find("tile_in_chip")
    tic.spatial.meshX = N_TILES_IN_CHIP
    tic.attributes.has_power_gating = True
    tic.constraints.spatial.no_reuse = []

    spec.architecture.find("output_buffer").constraints.temporal.iter_only = []


# ---------------------------------------------------------------------------
# Assumed physical LAYOUT (Phase 1: only the `router` interconnect has fanout +
# energy, so distance acts there). hop_scale = relative physical cost per hop.
# Fill per-level values once the exact die->macro->core hierarchy exists.
# ---------------------------------------------------------------------------
LAYOUT = {
    "router": {"topology": "mesh_2d", "hop_scale": 1.0, "hop_latency_ns": 1.0},
    # Phase 2 examples (cheaper inside, costlier across):
    # "inter_core_in_macro":  {"topology": "mesh_2d", "hop_scale": 0.3},
    # "inter_macro_in_die":   {"topology": "mesh_2d", "hop_scale": 1.0},
    # "inter_die_in_package": {"topology": "mesh_2d", "hop_scale": 8.0},
}


# ---------------------------------------------------------------------------
# Run one layer + perceive + position-aware overlay
# ---------------------------------------------------------------------------
def run_mlx_layer(layer_path, place_fn=pa.place_grid, layout=None):
    """Run a single workload layer on the MLX-style system and return both the
    raw CiMLoop result and the position-aware communication analysis.

    The stats file is parsed IMMEDIATELY (the run dir is wiped on the next
    run_mapper call in the same thread), so this is loop-safe.
    """
    result = utl.run_layer(layer=layer_path, callfunc=mlx_callfunc, **MLX_CONFIG)
    levels = pa.perceive_result(result)                 # capture before next run
    analysis = pa.position_aware_cost(levels, layout or LAYOUT, place_fn)
    return {
        "result": result,
        "levels": levels,
        "analysis": analysis,
        "baseline_total_energy_J": result.energy,
        "position_aware_extra_J": analysis["position_aware"] - analysis["baseline"],
    }


def list_layers(dnn_name="resnet18"):
    """Sorted, einsum-only layer paths for a workload in models/workloads/."""
    d = utl.path_from_model_dir(f"workloads/{dnn_name}")
    paths = sorted(
        os.path.join(d, f) for f in os.listdir(d)
        if f.endswith(".yaml") and f != "index.yaml"
    )
    return [p for p in paths if "From einsum" not in open(p).read()]


def run_mlx_dnn(dnn_name="resnet18", place_fn=pa.place_grid, layout=None, limit=None):
    """Run all (or `limit`) layers of a DNN SEQUENTIALLY (1 core -- safe to run
    alongside other workloads; do NOT switch to joblib n_jobs=None here)."""
    layers = list_layers(dnn_name)
    if limit:
        layers = layers[:limit]
    out = []
    for i, lp in enumerate(layers):
        print(f"[{i+1}/{len(layers)}] {os.path.basename(lp)}", flush=True)
        out.append(run_mlx_layer(lp, place_fn=place_fn, layout=layout))
    return out


if __name__ == "__main__":
    # Quick smoke test: one ResNet18 layer, grid vs linear placement.
    layer = list_layers("resnet18")[0]
    for name, fn in [("grid", pa.place_grid), ("linear", pa.place_linear)]:
        r = run_mlx_layer(layer, place_fn=fn)
        pa.print_report(r["analysis"], title=f"{os.path.basename(layer)}  placement={name}")
