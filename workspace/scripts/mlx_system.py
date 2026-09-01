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
# Phase-2 hardware: explicit package -> die -> macro -> core -> crossbar.
#   macro = wan_nature_2022 (256x256 4-bit ReRAM crossbar)
#   tile  = 2_tile/mlx_core.yaml   (core: I/O buffers + 8 crossbars)
#   chip  = 3_chip/mlx_die.yaml    (die: 8 MB glb + 8 macros + router + 4 cores)
#   system= 4_system/ws_chip2chip_link.yaml  (PACKAGE: N dies + die<->die link)
#
# WEIGHTS ARE RESIDENT (ReRAM is non-volatile / weight-stationary): they are
# PROGRAMMED ONCE into the crossbars and stay -- inference does NOT re-stream
# weights from DRAM. So the top level is ws_chip2chip_link (no weight DRAM; only
# activations flow die-to-die), NOT fetch_weights_lpddr4 (which streams weights
# every inference -- correct for a volatile SRAM CiM, WRONG for ReRAM, and
# inflated our earlier energy ~36%). The ONLY per-inference writes are attention
# K/V (see llm_workload write cost) -- exactly what a resident design implies.
# ---------------------------------------------------------------------------
# Physical structure comes from the fabric config (models/fabric/mlx300.yaml)
# -- the single source of truth. These module attributes keep their legacy
# names so downstream code is unchanged; crossbar_stats.hierarchy() verifies
# every run's stats against the same config.
from scripts import fabric as _fabric
FABRIC = _fabric.default()
N_MACROS_PER_DIE = FABRIC.level("macro").per_parent
N_CORES_PER_MACRO = FABRIC.level("core").per_parent
CROSSBARS_PER_CORE = FABRIC.level("crossbar").per_parent
# count_below spans the whole package; a multi-die fabric must not inflate
# the PER-DIE constants (that silently disabled the O10 capacity guard once).
CROSSBARS_PER_DIE = (FABRIC.count_below("crossbar")
                     // FABRIC.count_below("die"))                # 256
# One die weight capacity (4-bit cells): 256 crossbars x 256x256 x 4b = 8.4 MB
# = 16.8 M 4-bit weights. GPT-2 medium (302 M weights) is thus RESIDENT across
# ~18 dies (4-bit) / ~36 (8-bit); the 256-die package holds it easily. A single
# transformer layer (~12.6 M weights) fits on ONE die -> we model 1 layer / die
# and move activations die-to-die between layers.
DIE_WEIGHT_CAPACITY_4B = CROSSBARS_PER_DIE * 256 * 256 * 4 // 4   # 16.8 M weights

MLX_DIE_CONFIG = dict(
    macro="wan_nature_2022",
    tile="mlx_core",              # core: local I/O buffer + crossbars
    chip="mlx_die",               # die: 8 MB glb + 8 macros + router + 4 cores
    system="ws_chip2chip_link",   # package: dies + die<->die link, weights RESIDENT
)

# The old weight-STREAMING top level -- kept only for A/B comparison. Do NOT use
# for ReRAM inference cost (it re-fetches weights from DRAM every inference).
MLX_DIE_STREAMING_CONFIG = dict(MLX_DIE_CONFIG, system="fetch_weights_lpddr4")


def n_dies_for_weights(n_weights, weight_bits=4):
    """How many dies a model's weights need to be RESIDENT (weight-stationary)."""
    per_die = CROSSBARS_PER_DIE * 256 * 256 * 4 // weight_bits
    return -(-n_weights // per_die)   # ceil


def mlx_die_callfunc(spec):
    """Size the explicit die hierarchy (8 macros/die, 4 cores/macro, 8
    crossbars/core) and relax the same default constraints."""
    for name, mesh in [("macro_in_die", N_MACROS_PER_DIE),
                       ("core_in_macro", N_CORES_PER_MACRO),
                       ("crossbar_in_core", CROSSBARS_PER_CORE)]:
        c = spec.architecture.find(name)
        c.spatial.meshX = mesh
        c.attributes.has_power_gating = True
        c.constraints.spatial.no_reuse = []
    spec.architecture.find("output_buffer").constraints.temporal.iter_only = []
    # T1 storage bandwidth from the fabric config, pushed into Timeloop so
    # its NATIVE throttling stalls the cycle count. UNIT WARNING (O28/C34):
    # Timeloop consumes this in its own COUNTER units at the glb -- input
    # fills x7 bit slices, output fills/updates x8 bit groups (the write
    # port binds; ffn1 charges 37,224,448 units against ~8.9M value words)
    # -- NOT the value words the fabric declares. The readable T1 axis is
    # the analytic one (sweep_axes.axis_t1_hub, value units); this push is
    # kept for validation runs only (analyze_bandwidth_sweep.py), and no
    # shipped config declares a hub bandwidth (group 29 checks). Network
    # links are deliberately NOT pushed here -- they belong to the analytic
    # per-link tier (crossbar_comm.link_occupancy); the tiers compose by max.
    hub_bw = FABRIC.level("die").hub_bandwidth_words_per_cycle
    if hub_bw is not None:
        glb = spec.architecture.find("glb")
        glb.attributes.read_bandwidth = hub_bw
        glb.attributes.write_bandwidth = hub_bw


# ---------------------------------------------------------------------------
# Assumed physical LAYOUT (Phase 1: only the `router` interconnect has fanout +
# energy, so distance acts there). hop_scale = relative physical cost per hop.
# Fill per-level values once the exact die->macro->core hierarchy exists.
# ---------------------------------------------------------------------------
# Per-interconnect physical layout.
#   pattern         : communication model (placement_aware.DISTANCE_MODELS) --
#                     "to_center"/"tree" (reduction/multicast), "all_to_all",
#                     "neighbor".
#   hop_scale       : per-hop physical cost multiplier (from the layout spec).
#   reference_hops  : how many hops CiMLoop's BASELINE per-word energy already
#                     represents. CiMLoop charges a fixed per-word energy for ONE
#                     router traversal with NO distance term, so reference_hops=1
#                     treats the baseline as "one hop" (a multi-hop mesh then
#                     costs `hops` x more). If the router energy was instead
#                     calibrated to an average R-hop transfer, set reference_hops=R
#                     so good placement falls BELOW baseline and bad ABOVE.
#                     >>> UNCONFIRMED: verify what the isaac_router energy means. <<<
# Topology + these values are PLUGGABLE -- swap per level to explore settings.
# Per-tree-level PROPAGATION latency (ns per Manhattan hop), keyed to match
# crossbar_comm.level_max_hops / placement_aware.position_aware_latency.
# ALL PLACEHOLDERS -- calibrate against the company interconnect once known.
# Costlier the higher up the tree (die NoC > intra-macro > intra-core);
# monotonicity is enforced by fabric.validate(). The on-die per-hop latencies
# are the fabric links BELOW the die level; the die's own link is D2D.
HOP_LATENCY_NS = {
    lv.link.name: lv.link.ns_per_hop
    for lv in FABRIC.levels[FABRIC.levels.index(FABRIC.level("die")) + 1:]
    if lv.link is not None
}

# One entry per fabric link that is priced by a calibrated CiMLoop component
# (today: the die NoC's `router`); reference_hops comes from the config (DR-4).
LAYOUT = {
    lv.link.cimloop_component: {
        "topology": "mesh_2d", "pattern": "to_center", "hop_scale": 1.0,
        "hop_latency_ns": 1.0, "reference_hops": lv.link.reference_hops,
    }
    for lv in FABRIC.levels
    if lv.link is not None and lv.link.cimloop_component
}


# ---------------------------------------------------------------------------
# Run one layer + perceive + position-aware overlay
# ---------------------------------------------------------------------------
def run_mlx_layer(layer_path, place_fn=pa.place_grid, layout=None,
                  config=None, callfunc=None, placement=None):
    """Run a single workload layer on the MLX-style system and return both the
    raw CiMLoop result and the position-aware communication analysis.

    config/callfunc default to the Phase-1 setup (MLX_CONFIG / mlx_callfunc);
    pass MLX_DIE_CONFIG / mlx_die_callfunc for the explicit die->macro->core->
    crossbar hierarchy.

    The stats file is parsed IMMEDIATELY (the run dir is wiped on the next
    run_mapper call in the same thread), so this is loop-safe.
    """
    config = config or MLX_CONFIG
    callfunc = callfunc or mlx_callfunc
    result = utl.run_layer(layer=layer_path, callfunc=callfunc, **config)
    # hygiene 22 (C40): replace the rounded summary-table energy (pJ/compute
    # x computes, finite print precision, +0.05-0.5%) with the exact sum of
    # the per-component 'Energy (total)' lines; the rounded value stays on
    # `energy_summary_J`. Published JSON energies move by <=0.5% at the next
    # regeneration; the ledger's residual row closes then.
    try:
        from scripts import tl_output_parsing as _tlp
        with open(os.path.join(result.output_dir, "timeloop-mapper.stats.txt")) as _f:
            _exact = _tlp.exact_total_energy_J(_f.read())
        result.energy_summary_J = result.energy
        result.energy = _exact
        result.tops_per_w = result.computes / result.energy * 2 / 1e12
    except (OSError, AttributeError):
        pass
    levels = pa.perceive_result(result)                 # capture before next run
    analysis = pa.position_aware_cost(levels, layout or LAYOUT, place_fn,
                                      placement=placement,
                                      fabric=FABRIC if placement else None)
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
