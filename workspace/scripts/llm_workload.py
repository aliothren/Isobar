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


def run_op(op: Op, place_fn=pa.place_grid, e_write=E_WRITE_PER_CELL_J,
           phase: str = "prefill", t_set_ns=T_SET_NS, hop_latency_ns=None,
           placement=None,
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
    def callfunc(spec):
        mlx.mlx_die_callfunc(spec)                  # hierarchy meshX
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

    # ---- latency (critical path) ----
    compute_lat = res.cycles * res.cycle_seconds                 # Timeloop native
    level_hops = cc.level_max_hops(mlx.FABRIC, pl)   # placement-aware geometry
    dist = pa.position_aware_latency(level_hops,
                                     hop_latency_ns or mlx.HOP_LATENCY_NS)
    dist_lat = dist["total_ns"] * 1e-9
    wr_lat = write_latency_s(op, phase, t_set_ns)
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
# Die-to-die activation (model-level, the package hierarchy).
#
# Weights are RESIDENT (ReRAM): one transformer layer per die, programmed once.
# What crosses dies each inference is the HIDDEN STATE between consecutive layers
# (weights never move). This is a cross-op / model-level cost that per-op Timeloop
# cannot see, so we overlay it -- the analogue of the on-die distance overlay, one
# level up (die<->die via the chip2chip_link).
#   prefill: S * d_model words per layer boundary ; decode: d_model words.
# ---------------------------------------------------------------------------
DIE_HOP_LATENCY_NS = mlx.FABRIC.level("die").link.ns_per_hop   # D2D hop (DR-3)
CHIP2CHIP_PJ_FALLBACK = 5.0   # per-word die-to-die energy if not extractable (pJ)


def die_to_die_activation(cfg: GptConfig, S: int, phase: str, chip2chip_pJ,
                          n_dies=None, hop_latency_ns=DIE_HOP_LATENCY_NS,
                          place_fn=pa.place_grid):
    """Hidden-state transfer between consecutive layers on different dies.

    n_dies defaults to n_layers (1 layer / die). Dies are placed on a grid and
    layer L sits on die L, so consecutive layers L->L+1 cost their Manhattan die
    distance. Returns energy (J) + latency (s) for one whole forward pass.
    """
    if chip2chip_pJ is None:
        chip2chip_pJ = CHIP2CHIP_PJ_FALLBACK
    n_dies = n_dies or cfg.n_layers
    n_boundaries = cfg.n_layers - 1
    words_per_boundary = (S if phase == "prefill" else 1) * cfg.d_model
    coords = place_fn(n_dies)
    hops = [pa._manhattan(coords[i], coords[i + 1]) for i in range(n_boundaries)]
    avg_hop = sum(hops) / max(len(hops), 1)
    total_words = words_per_boundary * n_boundaries
    return {
        "words": total_words,
        "energy_J": total_words * (chip2chip_pJ * 1e-12) * avg_hop,
        "latency_s": sum(h * hop_latency_ns for h in hops) * 1e-9,
        "n_boundaries": n_boundaries, "avg_die_hops": avg_hop, "n_dies": n_dies,
    }


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
