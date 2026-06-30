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

# Rough ReRAM SET (program) energy per cell for the wan device
# (~ V^2/R_on * t_set = 1.75^2 / 25e4 * 8520e-9 ~= 1e-10 J/cell).
# CALIBRATE against the cell model / a fetch_all run before trusting absolutes.
E_WRITE_PER_CELL_J = 1.0e-10


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


def block_ops(cfg: GptConfig, S: int, phase: str = "prefill"):
    """The ops in ONE transformer block at sequence length S.

    prefill : process all S query rows at once (P = S).
    decode  : process 1 new query row, attending over the S-long KV cache (P = 1).
    """
    dh = cfg.d_model // cfg.n_heads
    Pq = S if phase == "prefill" else 1   # query rows this step
    Klen = S                              # keys/values attended
    return [
        Op("qkv_proj", "static",  P=Pq, C=cfg.d_model, M=3 * cfg.d_model),
        Op("qk^t",     "dynamic", P=Pq, C=dh,   M=Klen, N=cfg.n_heads,
           write_cells=dh * Klen * cfg.n_heads),                 # K programmed in
        Op("av",       "dynamic", P=Pq, C=Klen, M=dh,   N=cfg.n_heads,
           write_cells=Klen * dh * cfg.n_heads),                 # V programmed in
        Op("out_proj", "static",  P=Pq, C=cfg.d_model, M=cfg.d_model),
        Op("ffn1",     "static",  P=Pq, C=cfg.d_model, M=cfg.d_ff),
        Op("ffn2",     "static",  P=Pq, C=cfg.d_ff,    M=cfg.d_model),
    ]


_BASE_LAYER = None
def _base_layer():
    """Any matmul layer file; its shape is overridden per op, histograms reused."""
    global _BASE_LAYER
    if _BASE_LAYER is None:
        _BASE_LAYER = mlx.list_layers("resnet18")[0]
    return _BASE_LAYER


def run_op(op: Op, place_fn=pa.place_grid, e_write=E_WRITE_PER_CELL_J):
    """Run one op on the MLX die hierarchy with its shape, attach the write cost.
    Returns a dict whose `output_dir` feeds crossbar_stats / crossbar_comm."""
    def callfunc(spec):
        mlx.mlx_die_callfunc(spec)                  # hierarchy meshX
        inst = spec.problem.instance
        inst["P"], inst["C"], inst["M"], inst["N"] = op.P, op.C, op.M, op.N
        inst["Q"] = inst["R"] = inst["S"] = 1       # matmul (no conv window)
    r = mlx.run_mlx_layer(_base_layer(), config=mlx.MLX_DIE_CONFIG,
                          callfunc=callfunc, place_fn=place_fn)
    write_J = op.write_cells * e_write if op.kind == "dynamic" else 0.0
    return {
        "op": op,
        "result": r["result"],
        "output_dir": r["result"].output_dir,       # -> crossbar_stats/comm
        "analysis": r["analysis"],                    # placement_aware overlay
        "compute_J": r["result"].energy,
        "comm_J": r["analysis"]["position_aware"],
        "write_J": write_J,
        "total_J": r["result"].energy + write_J,
    }


def run_block(cfg: GptConfig, S: int, phase: str = "prefill", place_fn=pa.place_grid,
              e_write=E_WRITE_PER_CELL_J, verbose=True):
    """Run one transformer block; returns the list of per-op result dicts."""
    out = []
    for op in block_ops(cfg, S, phase):
        if verbose:
            print(f"  {op.name:<9} ({op.kind:<7}) P={op.P} C={op.C} M={op.M} "
                  f"N={op.N}", flush=True)
        out.append(run_op(op, place_fn=place_fn, e_write=e_write))
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
    print(f"  attention share of block energy : {100*dyn/tot:.1f}%"
          f"   (of which write = {100*dyn_write/max(dyn,1e-30):.0f}% of attention)")
    return {"static": stat, "dynamic": dyn, "dyn_compute": dyn_compute,
            "dyn_write": dyn_write, "total": tot}
