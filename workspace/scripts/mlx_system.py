"""
The CIM die in CiMLoop and the runner of one layer on it.

The modelled die (MLX300-class): 256 x 256 RRAM crossbars with 4-bit cells
(the CiMLoop macro wan_nature_2022, NeuRRAM class), 8 crossbars per core,
4 cores per macro, 8 macros per die with a global buffer and an on-die
router. The geometry comes from the fabric config (models/fabric/*.yaml,
scripts/fabric.py); this module holds the CiMLoop level configuration and
mapper hints, the per-hop layout of the calibrated on-die link, and one call
that runs a layer and returns its baseline and position-aware cost.

Two CiMLoop configurations:
    MLX_DIE_CONFIG   the explicit package -> die -> macro -> core -> crossbar
                     hierarchy (3_chip/mlx_die, 2_tile/mlx_core,
                     4_system/ws_chip2chip_link), weights resident;
                     used for every account
    MLX_CONFIG       the same macro under the generic CiMLoop tile / chip
                     levels (input_output_bufs, large_router_glb,
                     fetch_weights_lpddr4)
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
# The macro under the generic CiMLoop tile / chip levels (see module docstring)
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
# The explicit hierarchy: package -> die -> macro -> core -> crossbar.
#   macro = wan_nature_2022 (256x256 4-bit ReRAM crossbar)
#   tile  = 2_tile/mlx_core.yaml   (core: I/O buffers + 8 crossbars)
#   chip  = 3_chip/mlx_die.yaml    (die: 8 MB glb + 8 macros + router + 4 cores)
#   system= 4_system/ws_chip2chip_link.yaml  (PACKAGE: N dies + die<->die link)
#
# WEIGHTS ARE RESIDENT (ReRAM is non-volatile / weight-stationary): they are
# PROGRAMMED ONCE into the crossbars and stay -- inference does NOT re-stream
# weights from DRAM. So the top level is ws_chip2chip_link (no weight DRAM; only
# activations flow die-to-die), NOT fetch_weights_lpddr4 (which streams weights
# every inference -- correct for a volatile SRAM CiM, not for ReRAM). The only
# per-inference writes are attention
# K/V (see llm_workload write cost) -- exactly what a resident design implies.
# ---------------------------------------------------------------------------
# Physical structure comes from the fabric config (models/fabric/*.yaml) --
# the single source of truth; crossbar_stats.hierarchy() verifies
# every run's stats against the same config.
from scripts import fabric as _fabric
FABRIC = _fabric.default()
N_MACROS_PER_DIE = FABRIC.level("macro").per_parent
N_CORES_PER_MACRO = FABRIC.level("core").per_parent
CROSSBARS_PER_CORE = FABRIC.level("crossbar").per_parent
# count_below spans the whole package; a multi-die fabric must not inflate
# the PER-DIE constants (the die capacity guard reads them).
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

# The weight-STREAMING top level, for comparison only: not for ReRAM inference
# cost (it re-fetches the weights from DRAM every inference).
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
    # Storage (hub) bandwidth from the fabric config, pushed into Timeloop so
    # its NATIVE throttling stalls the cycle count. UNIT WARNING:
    # Timeloop consumes this in its own COUNTER units at the glb -- input
    # fills x7 bit slices, output fills/updates x8 bit groups (the write
    # port binds; ffn1 charges 37,224,448 units against ~8.9M value words)
    # -- NOT the value words the fabric declares. This push is kept for
    # validation runs only; no shipped config declares a hub bandwidth. Network
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
# Topology + these values are PLUGGABLE -- swap per level to explore settings.
# Per-tree-level PROPAGATION latency (ns per Manhattan hop), keyed to match
# crossbar_comm.level_max_hops / placement_aware.position_aware_latency.
# Example values (fabric config): replace with the target chip's interconnect.
# Costlier the higher up the tree (die NoC > intra-macro > intra-core);
# monotonicity is enforced by fabric.validate(). The on-die per-hop latencies
# are the fabric links BELOW the die level; the die's own link is D2D.
HOP_LATENCY_NS = {
    lv.link.name: lv.link.ns_per_hop
    for lv in FABRIC.levels[FABRIC.levels.index(FABRIC.level("die")) + 1:]
    if lv.link is not None
}

# One entry per fabric link that is priced by a calibrated CiMLoop component
# (the die NoC's `router`); reference_hops comes from the config.
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
    # replace the rounded summary-table energy (pJ/compute x computes, finite
    # print precision, +0.05-0.5%) with the exact sum of the per-component
    # 'Energy (total)' lines; the rounded value stays on `energy_summary_J`.
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
