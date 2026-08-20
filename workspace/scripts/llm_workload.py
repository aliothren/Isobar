"""
LLM (GPT-style) workload generator + attention write-cost overlay.

Adds the two things the static gpt2_medium workload cannot express:

  (1) SEQUENCE-LENGTH SCALING -- generate each op's einsum shape as a function of
      sequence length S and phase (prefill / decode). Attention compute then
      scales ~S^2 (QK^T, AV) while projections/FFN scale ~S, so attention stops
      being artificially tiny at the short fixed sequence the static workload used.

  (2) ATTENTION WRITE-COST overlay -- QK^T / AV are activation x activation, so one
      operand (K or V) must be PROGRAMMED into the ReRAM crossbars every inference,
      NOT amortized like a weight. We charge  write_cells * E_WRITE_PER_CELL_J.
      (Combined plan: this overlay gives controllable per-phase write cost; its
      magnitude E_WRITE_PER_CELL_J should be calibrated against a non-weight-
      stationary CiMLoop run -- see the verification.)

INTEGRATION: every generated op is a normal MLX die-hierarchy run, so it returns an
`output_dir` + placement_aware `analysis`. Therefore
    crossbar_stats.report(out_dir)        # per-crossbar stats + structure
    crossbar_comm.summarize_and_plot(out_dir)   # per-pair flows + heatmap
    placement_aware (already inside the analysis)
all work on a generated op UNCHANGED; the write cost is an extra energy term.

Usage:
    from scripts import llm_workload as lw
    cfg = lw.GptConfig()
    res = lw.run_block(cfg, S=512, phase="prefill")
    lw.report_block(res)
"""
import os
from dataclasses import dataclass
from scripts import mlx_system as mlx
from scripts import placement_aware as pa
from scripts import crossbar_comm as cc
from scripts import value_stats as vs
from scripts import crossbar_value as cvmod

# Where the data-value-dependent histograms come from. Tie this to the MODEL
# being simulated -- NOT hardcoded downstream -- so simulating another model just
# means pointing at its workload. Static (projection/FFN) and dynamic (attention)
# ops draw from matching layer types so their value distributions differ.
DEFAULT_HIST_SOURCE = "gpt2_medium"
_HIST_TYPES = {"static": ("Conv1D", "Linear"), "dynamic": ("GPT2Attention",)}

# Rough ReRAM SET (program) energy per cell for the wan device
# (~ V^2/R_on * t_set = 1.75^2 / 25e4 * 8520e-9 ~= 1e-10 J/cell).
# CALIBRATE against the cell model / a fetch_all run before trusting absolutes.
E_WRITE_PER_CELL_J = 1.0e-10

# ReRAM SET pulse width (ns) -- the per-row programming latency. The wan device
# SET pulse is ~8520 ns (vs ~2 ns read), so writing a dynamic operand into the
# array is the attention LATENCY bottleneck. PLACEHOLDER -- calibrate.
T_SET_NS = 8520.0
CIM_ROWS = 256   # crossbar rows -> rows beyond this tile onto parallel crossbars


def write_latency_s(op: "Op", phase: str = "prefill", t_set_ns: float = T_SET_NS):
    """ReRAM programming latency for a DYNAMIC op (0 for static/weight ops).

    SET is row-serial: cells on ONE wordline program together (per-column bitline
    voltages set each cell's target conductance), but distinct wordlines must be
    pulsed in turn. So the serial pulse count is the number of DISTINCT ROWS the
    write touches (`op.write_rows`), NOT the cell count. Rows beyond CIM_ROWS tile
    onto PARALLEL crossbars, so the count caps at CIM_ROWS.

    `phase` is already baked into op.write_rows/op.write_cells by block_ops() and
    is accepted only for call-site compatibility.

    Returns seconds (a SERIAL phase, added before the op's compute latency).
    """
    if op.kind != "dynamic":
        return 0.0
    n_pulses = min(op.write_rows, CIM_ROWS)
    return n_pulses * t_set_ns * 1e-9


@dataclass
class GptConfig:
    d_model: int = 1024
    n_heads: int = 16
    d_ff: int = 4096
    n_layers: int = 24
    name: str = "gpt2-medium"


@dataclass
class Op:
    name: str
    kind: str            # 'static' (weight-stationary) | 'dynamic' (attention)
    P: int
    C: int
    M: int
    N: int = 1
    write_cells: int = 0  # dynamic operand cells programmed into ReRAM / inference
    write_rows: int = 0   # DISTINCT wordlines those cells span -> serial SET pulses


def block_ops(cfg: GptConfig, S: int, phase: str = "prefill"):
    """The ops in ONE transformer block at sequence length S.

    prefill : process all S query rows at once (P = S).
    decode  : process 1 new query row, attending over the S-long KV cache (P = 1).
    """
    dh = cfg.d_model // cfg.n_heads
    Pq = S if phase == "prefill" else 1   # query rows this step
    Klen = S                              # keys/values ATTENDED over (compute shape)
    # Rows/cols NEWLY PROGRAMMED this step. ReRAM K/V arrays are resident and
    # APPEND-ONLY: prefill programs all S tokens; decode appends just the new
    # token. (Rewriting the whole cache per step would both contradict weight
    # residency and exceed ReRAM endurance within seconds of generation.)
    Kwrite = S if phase == "prefill" else 1
    return [
        Op("qkv_proj", "static",  P=Pq, C=cfg.d_model, M=3 * cfg.d_model),
        # K^T is mapped dh(rows) x Klen(cols): a new token is a new COLUMN, so its
        # dh cells land on dh DISTINCT wordlines -> dh serial SET pulses.
        Op("qk^t",     "dynamic", P=Pq, C=dh,   M=Klen, N=cfg.n_heads,
           write_cells=dh * Kwrite * cfg.n_heads, write_rows=dh),
        # V is mapped Klen(rows) x dh(cols): a new token is a new ROW, so its dh
        # cells share ONE wordline -> 1 serial SET pulse.
        Op("av",       "dynamic", P=Pq, C=Klen, M=dh,   N=cfg.n_heads,
           write_cells=Kwrite * dh * cfg.n_heads, write_rows=Kwrite),
        Op("out_proj", "static",  P=Pq, C=cfg.d_model, M=cfg.d_model),
        Op("ffn1",     "static",  P=Pq, C=cfg.d_model, M=cfg.d_ff),
        Op("ffn2",     "static",  P=Pq, C=cfg.d_ff,    M=cfg.d_model),
    ]


_BASE_LAYER = None
def _base_layer():
    """Any matmul layer file; used only as a shape scaffold -- both the shape
    (P/C/M/N) AND the value histograms are overridden per op in run_op, so the
    scaffold layer's own data distribution never leaks into the result."""
    global _BASE_LAYER
    if _BASE_LAYER is None:
        _BASE_LAYER = mlx.list_layers("resnet18")[0]
    return _BASE_LAYER


# ---------------------------------------------------------------------------
# Over-capacity policy (FIXLIST O10).
#
# An op whose weights exceed one die's cells has NO silent path any more:
#   reject           (default) refuse to run -- the tripwire.
#   temporal_rewrite  run on one die; Timeloop time-multiplexes the arrays,
#                     which physically means reprogramming them EVERY pass.
#                     We charge that with the same primitives as the K/V write
#                     (E_WRITE_PER_CELL_J per cell; row-serial SET pulses,
#                     columns and crossbars parallel) and surface the
#                     endurance consequence. Static ops only.
#   spatial_multi_die the op spans ceil(cells/die) dies (chip_in_system.meshX);
#                     weights stay resident. Requires a fabric whose die level
#                     has enough instances (CIMSIM_FABRIC=...multidie).
# ---------------------------------------------------------------------------
DIE_WEIGHT_CELLS = mlx.CROSSBARS_PER_DIE * 256 * 256   # 4-bit cells
# The wan W4A8 device ENCODES a 4-bit weight into 8 bits across two 4-bit
# cells (N_WEIGHT_SLICES=2 -- the `Y in [0:2)` column split in every mapping),
# so a weight occupies TWO cells and an array holds 256 rows x 128 weights.
# Getting this wrong by 2x is exactly how "one layer per die" over-promised.
CELLS_PER_WEIGHT = 2
# ReRAM write endurance, cycles per cell. EXAMPLE DEFAULT (platform input):
# public figures span 1e6..1e12 depending on device class.
ENDURANCE_CYCLES = 1.0e8


def op_weight_cells(op: Op) -> int:
    """Physical cells the op's resident operand occupies."""
    return op.C * op.M * op.N * CELLS_PER_WEIGHT


def dies_for_op(op: Op) -> int:
    return -(-op_weight_cells(op) // DIE_WEIGHT_CELLS)


def static_rewrite_cost(op: Op, e_write=E_WRITE_PER_CELL_J,
                        t_set_ns=T_SET_NS):
    """Per-inference cost of temporal weight reuse: EVERY cell is rewritten
    once per pass (the arrays end each pass holding the last tile, so even
    the first tile must be re-programmed next time). Rows are written
    serially at T_SET each; the columns of a row and all crossbars program in
    parallel -- the same conventions as the K/V write model."""
    cells = op_weight_cells(op)
    columns = mlx.CROSSBARS_PER_DIE * 256
    rows = -(-cells // columns)
    return {"cells": cells, "rows_serial": rows,
            "energy_J": cells * e_write,
            "latency_s": rows * t_set_ns * 1e-9,
            "lifetime_inferences": ENDURANCE_CYCLES}   # 1 write/cell/pass


def _die_tiling(c_res: int, m_res: int):
    """Closed-form spatial tiling of one die for a C_res x M_res weight slice.

    Rows are C-only (256/array); columns hold 256//CELLS_PER_WEIGHT = 128
    weights of M per array (the other half is the weight-slice dim Y). The
    fanout menu is macro 8 x core 4 x crossbar 8 = 256 array tiles. Returns
    per-level (C, M) spatial factors covering ceil(C/256) x ceil(M/128) tiles
    exactly, or None if the slice does not fit. Exists because the arch's
    greedy M-first maximize_dims can starve C and silently fall back to
    temporal weight tiling (= phantom reload) even for shapes that fit."""
    cT = -(-c_res // 256)
    mT = -(-m_res // (256 // CELLS_PER_WEIGHT))
    if cT * mT > 256:
        return None
    fan = [8, 4, 8]                                  # macro, core, crossbar
    def _divs(n):
        return [d for d in range(1, n + 1) if n % d == 0]
    for c0 in _divs(fan[0]):
        for c1 in _divs(fan[1]):
            for c2 in _divs(fan[2]):
                if c0 * c1 * c2 != cT:
                    continue
                m_room = [fan[0] // c0, fan[1] // c1, fan[2] // c2]
                for m0 in _divs(m_room[0]):
                    for m1 in _divs(m_room[1]):
                        for m2 in _divs(m_room[2]):
                            if m0 * m1 * m2 == mT:
                                return [(c0, m0), (c1, m1), (c2, m2)]
    return None


def _temporal_weight_loads(mapping_text: str) -> int:
    """Product of TEMPORAL factors over the weight dims (C/M/N) anywhere in
    the mapping = how many distinct weight tiles visit the arrays over time.
    Cross-check for the rewrite account: must be >= dies_for_op."""
    import re
    prod = 1
    for line in mapping_text.splitlines():
        ls = line.strip().lstrip("|").strip()
        m = re.match(r"for ([CMN]) in \[0:(\d+)\)\s*$", ls)
        if m:
            prod *= int(m.group(2))
    return prod


def run_op(op: Op, place_fn=pa.place_grid, e_write=E_WRITE_PER_CELL_J,
           phase: str = "prefill", t_set_ns=T_SET_NS, hop_latency_ns=None,
           placement=None, overcapacity: str = "reject",
           save_comm=True, comm_dir=cc.DEFAULT_COMM_DIR,
           hist_source=DEFAULT_HIST_SOURCE,
           value_mode="uniform", value_source="synthetic",
           value_spread=cvmod.DEFAULT_SPREAD):
    """Run one op on the MLX die hierarchy with its shape, attach write cost +
    latency. Returns a dict whose `output_dir` feeds crossbar_stats / crossbar_comm.

    Latency (critical path, seconds):
        total = write (serial, dynamic only)   -- ReRAM SET phase, before compute
              + compute (Timeloop cycles x cycle_time, incl. bandwidth stalls)
              + distance propagation (hops x hop_latency, the position-aware term)
    """
    n_dies_op = dies_for_op(op)
    rewrite = None
    if n_dies_op > 1:
        if overcapacity == "reject":
            raise ValueError(
                f"{op.name}: weights need {op_weight_cells(op):,} cells = "
                f"{n_dies_op} dies (one die holds {DIE_WEIGHT_CELLS:,}). "
                "Timeloop would silently time-multiplex the arrays with the "
                "reprogramming billed at zero (FIXLIST O10). Choose "
                "overcapacity='temporal_rewrite' (charge the rewrite) or "
                "'spatial_multi_die' (span dies, weights resident).")
        if overcapacity == "temporal_rewrite":
            if op.kind != "static":
                raise NotImplementedError(
                    "temporal_rewrite covers static ops; over-capacity "
                    "K/V arrays need their own policy")
            rewrite = static_rewrite_cost(op, e_write, t_set_ns)
            print(f"    [O10 temporal_rewrite: {rewrite['cells']:,} cells "
                  f"reprogrammed EVERY pass -> +{rewrite['energy_J']*1e3:.2f} mJ, "
                  f"+{rewrite['latency_s']*1e3:.2f} ms; endurance bounds the "
                  f"array at ~{rewrite['lifetime_inferences']:.0e} inferences]",
                  flush=True)
        elif overcapacity == "spatial_multi_die":
            if mlx.FABRIC.level("die").per_parent < n_dies_op:
                raise ValueError(
                    f"{op.name} spans {n_dies_op} dies but the fabric "
                    f"'{mlx.FABRIC.name}' has "
                    f"{mlx.FABRIC.level('die').per_parent}; select a multi-die "
                    "fabric (CIMSIM_FABRIC=models/fabric/mlx300_multidie.yaml)")
        else:
            raise ValueError(f"unknown overcapacity policy '{overcapacity}'")

    def callfunc(spec):
        mlx.mlx_die_callfunc(spec)                  # hierarchy meshX
        if n_dies_op > 1 and overcapacity == "spatial_multi_die":
            _chip = spec.architecture.find("chip_in_system")
            _chip.spatial.meshX = n_dies_op
            # Choose the die-split dim by TILING FEASIBILITY (prefer M: input
            # multicast across dies beats cross-die partial-sum reduction),
            # then pin the whole per-die C/M tiling closed-form. We must not
            # leave this to the arch's greedy M-first maximize_dims: it can
            # starve C and dump the remainder into glb's temporal sink --
            # the phantom reload this policy exists to eliminate.
            _plan = None
            for _dim in ("M", "C"):
                _sz = getattr(op, _dim)
                if _sz % n_dies_op:
                    continue
                _c = op.C // n_dies_op if _dim == "C" else op.C
                _m = op.M // n_dies_op if _dim == "M" else op.M
                _t = _die_tiling(_c, _m)
                if _t is not None:
                    _plan = (_dim, _t)
                    break
            if _plan is None:
                raise ValueError(
                    f"{op.name}: no exact spatial tiling across "
                    f"{n_dies_op} dies (C={op.C}, M={op.M})")
            _dim, _tiles = _plan
            _chip.constraints.spatial.factors.append(
                f'"{_dim}={n_dies_op}"')
            for _cname, (_cf, _mf) in zip(
                    ("macro_in_die", "core_in_macro", "crossbar_in_core"),
                    _tiles):
                _cn = spec.architecture.find(_cname).constraints.spatial
                _cn.pop("maximize_dims", None)       # explicit pins take over
                _cn.factors.append(f'"C={_cf}"')
                _cn.factors.append(f'"M={_mf}"')
            # Residency made a CONSTRAINT: glb's C=-1/M=-1 are the temporal
            # REMAINDER SINKS -- exactly where the free phantom reload lives.
            for _name in ("glb", "chip2chip_link"):
                _fac = spec.architecture.find(_name).constraints.temporal.factors
                for _i in range(len(_fac) - 1, -1, -1):
                    if str(_fac[_i]).startswith(("C=", "M=")):
                        del _fac[_i]
                _fac.append('"C=1"')      # quoted: parsed as expression
                _fac.append('"M=1"')
        inst = spec.problem.instance
        inst["P"], inst["C"], inst["M"], inst["N"] = op.P, op.C, op.M, op.N
        inst["Q"] = inst["R"] = inst["S"] = 1       # matmul (no conv window)
        # value-dependent energy: use the SIMULATED model's operand distribution
        # (matched to this op's kind), not the shape-scaffold layer's histograms.
        if hist_source:
            h = vs.representative_histograms(hist_source, _HIST_TYPES.get(op.kind))
            if h:
                spec.problem["histograms"] = dict(h)
    from scripts import placement as placement_mod
    pl = placement or placement_mod.sequential_fill(mlx.FABRIC)
    r = mlx.run_mlx_layer(_base_layer(), config=mlx.MLX_DIE_CONFIG,
                          callfunc=callfunc, place_fn=place_fn, placement=pl)
    res = r["result"]
    write_J = op.write_cells * e_write if op.kind == "dynamic" else 0.0
    if n_dies_op > 1 and overcapacity == "spatial_multi_die":
        import os as _os
        _mp = _os.path.join(res.output_dir, "timeloop-mapper.map.txt")
        _txt = open(_mp).read() if _os.path.exists(_mp) else ""
        if _temporal_weight_loads(_txt) != 1:
            raise ValueError(
                f"{op.name}: spatial_multi_die mapping still temporally "
                "re-tiles the weights -- residency constraint did not hold")
        if "inter_chip_in_system_spatial" not in _txt:
            raise ValueError(
                f"{op.name}: mapper did not use the {n_dies_op}-die spatial "
                "fanout")
    if rewrite is not None:
        import os as _os
        _mp = _os.path.join(res.output_dir, "timeloop-mapper.map.txt")
        loads = _temporal_weight_loads(open(_mp).read()) if _os.path.exists(_mp) else 0
        if loads < n_dies_op:
            raise ValueError(
                f"{op.name}: mapping shows {loads} temporal weight tiles but "
                f"capacity requires >= {n_dies_op} -- rewrite account and "
                "mapping disagree")
        write_J += rewrite["energy_J"]

    # ---- latency (critical path) ----
    compute_lat = res.cycles * res.cycle_seconds                 # Timeloop native
    level_hops = cc.level_max_hops(mlx.FABRIC, pl)   # placement-aware geometry
    dist = pa.position_aware_latency(level_hops,
                                     hop_latency_ns or mlx.HOP_LATENCY_NS)
    dist_lat = dist["total_ns"] * 1e-9
    wr_lat = write_latency_s(op, phase, t_set_ns)
    if rewrite is not None:
        wr_lat += rewrite["latency_s"]              # serial, before compute
    # T2 static contention: the worst network link's serialization time.
    # Composes with compute by MAX, never sum -- Timeloop's own throttling (T1,
    # storage hubs) and our per-link tier both lower-bound the same phenomenon.
    # All-zero unless a fabric link carries a bandwidth (default: none do).
    flows_q, _, _, _ = cc.build_flows(res.output_dir, verbose=False,
                                      fabric=mlx.FABRIC, placement=pl)
    occ = cc.link_occupancy(flows_q, mlx.FABRIC, res.cycle_seconds)
    contention_lat = occ["serialization_s"]
    total_lat = wr_lat + max(compute_lat, contention_lat) + dist_lat

    # value-dependent energy MODE. "uniform" (default) = one histogram for the whole
    # op, every crossbar identical (exact, cheap). "per_crossbar" = each crossbar's
    # value-dependent energy scaled by its own distribution -> a per-crossbar spread.
    crossbar_value = None
    if value_mode == "per_crossbar":
        def floor_cf(spec):                          # zero-activity -> energy floor
            mlx.mlx_die_callfunc(spec)
            i = spec.problem.instance
            i["P"], i["C"], i["M"], i["N"] = op.P, op.C, op.M, op.N
            i["Q"] = i["R"] = i["S"] = 1
            spec.problem["histograms"] = cvmod.zero_histograms()
        floor = mlx.utl.run_layer(layer=_base_layer(), callfunc=floor_cf,
                                  **mlx.MLX_DIE_CONFIG)
        scales = cvmod.per_crossbar_activities(mlx.CROSSBARS_PER_DIE,
                                               source=value_source, spread=value_spread)
        crossbar_value = cvmod.per_crossbar_energy(res.energy, floor.energy, scales)

    # auto-save the DETAILED per-pair communication data for this run (the run
    # dir is overwritten by the next op, so snapshot now).
    comm_files = None
    if save_comm:
        try:
            comm_files = cc.save_flows(res.output_dir, tag=f"{op.name}_{phase}",
                                       dest_dir=comm_dir, fabric=mlx.FABRIC,
                                       placement=pl)
        except Exception as e:                       # non-die run / parse miss
            print(f"    [save_comm skipped for {op.name}: "
                  f"{type(e).__name__}: {e}]", flush=True)
    return {
        "op": op,
        "result": res,
        "output_dir": res.output_dir,                 # -> crossbar_stats/comm
        "analysis": r["analysis"],                    # placement_aware overlay
        "compute_J": res.energy,
        "comm_J": r["analysis"]["position_aware"],
        "write_J": write_J,
        "total_J": res.energy + write_J,
        # latency breakdown (seconds)
        "compute_latency_s": compute_lat,
        "contention_latency_s": contention_lat,
        "bottleneck_link": occ["bottleneck"],
        "dist_latency_s": dist_lat,
        "write_latency_s": wr_lat,
        "total_latency_s": total_lat,
        "comm_files": comm_files,                     # (csv, json) of per-pair flows
        "levels": r["levels"],                        # perceived components (unit_pJ ...)
        "value_mode": value_mode,
        "crossbar_value": crossbar_value,             # per-crossbar energy spread or None
        "overcapacity": overcapacity if n_dies_op > 1 else None,
        "dies_for_op": n_dies_op,
        "rewrite": rewrite,                           # temporal_rewrite account or None
    }


def run_block(cfg: GptConfig, S: int, phase: str = "prefill", place_fn=pa.place_grid,
              e_write=E_WRITE_PER_CELL_J, verbose=True):
    """Run one transformer block; returns the list of per-op result dicts."""
    out = []
    for op in block_ops(cfg, S, phase):
        if verbose:
            print(f"  {op.name:<9} ({op.kind:<7}) P={op.P} C={op.C} M={op.M} "
                  f"N={op.N}", flush=True)
        out.append(run_op(op, place_fn=place_fn, e_write=e_write, phase=phase))
    return out


# ---------------------------------------------------------------------------
# KV-cache model (the decode-phase memory bottleneck).
#
# During decode, each step appends the new token's K,V to a cache and the
# attention reads the WHOLE cache. The cache is large (2 * S * d_model * n_layers
# * precision -> ~100s of MB for long S), so it lives off-chip; reads dominate.
#   per step at context length t (one layer): read 2*t*d, write 2*d words.
#   generating G tokens total:  read ~ G^2 * d  (QUADRATIC), write ~ G * d.
# ---------------------------------------------------------------------------
# DRAM access energy per word. Placeholder -- calibrate against CiMLoop's
# main_memory access energy / the company DRAM. ~ tens of pJ/word.
E_DRAM_PER_WORD_J = 5.0e-11


# ---------------------------------------------------------------------------
# Die-to-die activation (model-level, the package hierarchy) -- W3.
#
# Weights are RESIDENT (ReRAM): one transformer layer per die, programmed once.
# What crosses dies each inference is the HIDDEN STATE between consecutive
# layers (weights never move) -- a cross-op cost per-op Timeloop cannot see.
#   prefill: S * d_model words per layer boundary ; decode: d_model words.
#
# Geometry now comes from the fabric's DIE level (grid + scheme + params), the
# same registry the on-die levels use, one level up. `assignment[L]` = which
# die slot layer L occupies (default: layer L -> slot L mod n_dies; the shipped
# single-die default puts every layer on die 0).
#
# REPLACE, NEVER ADD (the C6 acceptance): CiMLoop's flat chip2chip_link already
# charges every word once, position-blind. reference_hops (die link config)
# declares how many die-boundary traversals that flat price covers; the overlay
# bills only the SURPLUS  max(hops - reference_hops, 0)  per word. Single die
# (hops = 0) and adjacent dies (hops = 1 = reference) therefore add exactly
# zero energy -- the pre-D2D totals are preserved by construction.
# ---------------------------------------------------------------------------
DIE_HOP_LATENCY_NS = mlx.FABRIC.level("die").link.ns_per_hop   # D2D hop (DR-3)


def die_assignment(cfg: GptConfig, fabric=None):
    """Default layer -> die-slot assignment: layer L on slot L mod n_dies."""
    from scripts import fabric as fabric_mod
    fab = fabric or fabric_mod.default()
    n_dies = fab.level("die").per_parent
    return [L % n_dies for L in range(cfg.n_layers)]


def die_to_die_activation(cfg: GptConfig, S: int, phase: str, chip2chip_pJ=None,
                          fabric=None, placement=None, assignment=None,
                          hop_latency_ns=None):
    """Hidden-state transfer between consecutive layers, on the fabric's die
    grid under its configured scheme. Returns energy (J, SURPLUS beyond the
    flat charge -- see module comment) + latency (s) for one forward pass,
    plus the per-boundary flows for link_occupancy (D2D contention).
    """
    from scripts import fabric as fabric_mod
    from scripts import interconnect as ic_mod
    from scripts import placement as placement_mod
    fab = fabric or fabric_mod.default()
    lv = fab.level("die")
    pl = (placement or placement_mod.sequential_fill(fab)).verify(fab)
    asg = assignment or die_assignment(cfg, fab)
    if len(asg) != cfg.n_layers:
        raise ValueError(f"assignment covers {len(asg)} layers, "
                         f"model has {cfg.n_layers}")
    if max(asg) >= len(pl.slots["die"]):
        raise ValueError(f"assignment uses die slot {max(asg)}, fabric has "
                         f"{len(pl.slots['die'])}")
    if chip2chip_pJ is None:
        chip2chip_pJ = lv.link.pj_per_word          # example default (DR-3)
    ref = lv.link.reference_hops if lv.link.reference_hops is not None else 1.0
    ns_hop = hop_latency_ns if hop_latency_ns is not None else lv.link.ns_per_hop

    die_ic = ic_mod.build(fab, "die", pl)
    words_per_boundary = (S if phase == "prefill" else 1) * cfg.d_model
    n_boundaries = cfg.n_layers - 1
    hops, flows = [], []
    for L in range(n_boundaries):
        a, b = asg[L], asg[L + 1]
        h = die_ic.hops(a, b) if a != b else 0.0
        hops.append(h)
        if a != b:
            flows.append({"level": lv.link.name, "level_name": "die",
                          "nodes": (a, b), "src": f"die{a}", "dst": f"die{b}",
                          "volume": float(words_per_boundary), "distance": h})
    surplus = sum(max(h - ref, 0.0) for h in hops)
    pj = 0.0 if chip2chip_pJ is None else chip2chip_pJ
    total_words = words_per_boundary * n_boundaries
    return {
        "words": total_words,
        "energy_J": words_per_boundary * (pj * 1e-12) * surplus,
        "latency_s": sum(hops) * ns_hop * 1e-9,
        "flows": flows,
        "n_boundaries": n_boundaries,
        "avg_die_hops": sum(hops) / max(len(hops), 1),
        "n_dies": lv.per_parent,
    }


def die_pipeline_interval(cfg: GptConfig, S: int, phase: str, stage_s: float,
                          fabric=None, placement=None, assignment=None,
                          cycle_seconds=None):
    """Steady-state PIPELINED operation across the die grid: each die holds one
    layer, different microbatches (prefill requests / independent decode
    streams) occupy different dies simultaneously, and every layer boundary
    transfers concurrently each beat.

    This is the operating mode where D2D placement actually reaches the
    system numbers: the transfer no longer hides behind the WHOLE forward
    pass's compute (single-pass view) -- it races ONE stage's compute, and the
    busiest die wire's occupancy per beat sets the interval:

        interval = max(stage_s, busiest_wire_volume / bandwidth * cycle)
        throughput = 1 / interval

    Assumptions (stated, all optimistic): perfect microbatch pipelining, no
    bubbles, transfer/compute overlap via double buffering, weights resident.
    Returns {"interval_s", "net_s", "network_bound", "flows"}. With no die
    bandwidth set net_s is 0 and the interval is the compute stage -- the same
    off-by-default discipline as every other contention term.
    """
    from scripts import fabric as fabric_mod
    from scripts import placement as placement_mod
    import scripts.crossbar_comm as cc
    fab = fabric or fabric_mod.default()
    pl = placement or placement_mod.sequential_fill(fab)
    d = die_to_die_activation(cfg, S, phase, fabric=fab, placement=pl,
                              assignment=assignment)
    cyc = cycle_seconds if cycle_seconds is not None else 1.449e-6
    occ = cc.link_occupancy(d["flows"], fab, cyc, pl)
    net = occ["serialization_s"]
    return {"interval_s": max(stage_s, net), "net_s": net,
            "network_bound": net > stage_s, "flows": d["flows"],
            "bottleneck": occ["bottleneck"]}


def kv_cache_size_bytes(cfg: GptConfig, S: int, dtype_bytes: int = 2):
    """Total KV-cache footprint for context length S (all layers)."""
    return 2 * S * cfg.d_model * cfg.n_layers * dtype_bytes


def decode_kv_cost(cfg: GptConfig, gen_len: int, e_dram=E_DRAM_PER_WORD_J):
    """KV-cache traffic + energy to generate `gen_len` tokens (all layers).

    read ~ sum_{t=1..G} 2*t*d  ~ G^2 * d   (quadratic -> the decode bottleneck)
    write ~ sum 2*d            ~ G   * d   (linear)
    """
    d, L = cfg.d_model, cfg.n_layers
    total_read = sum(2 * t * d for t in range(1, gen_len + 1)) * L
    total_write = (2 * d) * gen_len * L
    return {
        "gen_len": gen_len,
        "read_words": total_read,
        "write_words": total_write,
        "read_energy_J": total_read * e_dram,
        "write_energy_J": total_write * e_dram,
        "kv_total_J": (total_read + total_write) * e_dram,
        "cache_bytes_final": kv_cache_size_bytes(cfg, gen_len),
    }


def report_decode_kv(cfg: GptConfig, gen_len: int, e_dram=E_DRAM_PER_WORD_J):
    kv = decode_kv_cost(cfg, gen_len, e_dram)
    print(f"\n==== decode KV-cache, generate {gen_len} tokens "
          f"({cfg.name}, {cfg.n_layers} layers) ====")
    print(f"  KV read  : {kv['read_words']:,} words  -> {kv['read_energy_J']:.3e} J")
    print(f"  KV write : {kv['write_words']:,} words  -> {kv['write_energy_J']:.3e} J")
    print(f"  KV total : {kv['kv_total_J']:.3e} J   "
          f"(final cache {kv['cache_bytes_final']/1e6:.0f} MB)")
    print(f"  read is {kv['read_words']/max(kv['write_words'],1):.0f}x the write "
          "(quadratic vs linear in context length)")
    return kv


def report_block(results, title=""):
    """Print a per-op + static/dynamic summary for one block."""
    print(f"\n==== transformer block {title} ====")
    print(f"  {'op':<10}{'kind':<9}{'compute(J)':>13}{'comm(J)':>12}"
          f"{'write(J)':>12}{'total(J)':>13}")
    for r in results:
        o = r["op"]
        print(f"  {o.name:<10}{o.kind:<9}{r['compute_J']:>13.3e}"
              f"{r['comm_J']:>12.3e}{r['write_J']:>12.3e}{r['total_J']:>13.3e}")

    def s(key, kind):
        return sum(r[key] for r in results if r["op"].kind == kind)
    stat = s("total_J", "static")
    dyn_compute = s("compute_J", "dynamic")
    dyn_write = s("write_J", "dynamic")
    dyn = dyn_compute + dyn_write
    tot = stat + dyn
    print(f"\n  static total  : {stat:.3e} J")
    print(f"  dynamic total : {dyn:.3e} J   (compute {dyn_compute:.3e} + "
          f"write {dyn_write:.3e})")
    print(f"  attention share of block ENERGY : {100*dyn/tot:.1f}%"
          f"   (of which write = {100*dyn_write/max(dyn,1e-30):.0f}% of attention)")

    # ---- latency table (critical path: write + compute + propagation) ----
    print(f"\n  {'op':<10}{'kind':<9}{'compute(s)':>13}{'dist(s)':>12}"
          f"{'write(s)':>12}{'total(s)':>13}")
    for r in results:
        o = r["op"]
        print(f"  {o.name:<10}{o.kind:<9}{r['compute_latency_s']:>13.3e}"
              f"{r['dist_latency_s']:>12.3e}{r['write_latency_s']:>12.3e}"
              f"{r['total_latency_s']:>13.3e}")
    lat_tot = sum(r["total_latency_s"] for r in results)
    lat_dyn = sum(r["total_latency_s"] for r in results if r["op"].kind == "dynamic")
    lat_write = sum(r["write_latency_s"] for r in results)
    print(f"\n  block latency : {lat_tot:.3e} s")
    print(f"  attention share of block LATENCY: {100*lat_dyn/max(lat_tot,1e-30):.1f}%"
          f"   (ReRAM write alone = {100*lat_write/max(lat_tot,1e-30):.0f}% of block)")
    return {"static": stat, "dynamic": dyn, "dyn_compute": dyn_compute,
            "dyn_write": dyn_write, "total": tot,
            "latency_total": lat_tot, "latency_dynamic": lat_dyn,
            "latency_write": lat_write}
