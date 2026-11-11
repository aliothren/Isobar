"""
Transformer workloads on the CIM die: operator shapes, CiMLoop runs of one
operator, and the closed-form terms around them.

  * GptConfig / block_ops: the operators of one transformer block (QKV, QK^T,
    softmax, AV, output projection, FFN) as einsum shapes for a sequence
    length S and phase (prefill: S query rows; decode: one row against the
    cache); element-wise operators (norms, activation, residual adds) via
    block_elementwise_ops / elementwise_cost on the digital vector unit.
  * block_chain / boundary_flows / block_die_flows: a block spread over dies
    as a chain of die-sets, and the die-to-die flows of its hand-offs
    (column-split consumers receive the whole input; row-split producers
    send partial sums at partial-sum width).
  * run_op: one operator through CiMLoop on the die hierarchy (mlx_system),
    with the over-capacity policy (reject / temporal rewrite / spatial
    multi-die), co-residency array shares, the attention write cost
    (activation x activation operands are programmed into the arrays every
    inference), the propagation latency and the on-die serialization.
  * lm_head_op / embedding_cost: the model-end operators.
"""
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
_HIST_TYPES = {"static": ("Conv1D", "Linear"),
               "dynamic": ("GPT2Attention", "OPTAttention")}

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
    vocab: int = 50257          # embedding / LM head (GPT-2 BPE)
    # Fields of the real models (every default reproduces the GPT-2 /
    # 2.7B-class block above):
    head_dim: int = None        # None -> d_model // n_heads (Gemma: 256 with d_model 3072, 16 heads)
    n_kv_heads: int = None      # None -> n_heads (grouped K/V: fewer resident K/V arrays)
    ffn_gated: bool = False     # GeGLU / SwiGLU: two up-projections (gate, up) of width d_ff each, gated product into ffn2
    activation: str = "gelu"    # "gelu" | "relu" (OPT) | "geglu" / "swiglu" (set with ffn_gated)

    @property
    def dh(self) -> int:
        return self.head_dim if self.head_dim else self.d_model // self.n_heads

    @property
    def kv_heads(self) -> int:
        return self.n_kv_heads if self.n_kv_heads else self.n_heads

    @property
    def attn_width(self) -> int:
        """n_heads x head_dim: the Q width and the out_proj input width (= d_model unless head_dim is set)."""
        return self.n_heads * self.dh

    def extra_fields(self) -> dict:
        """The non-default real-model fields, for account records."""
        return {k: getattr(self, k) for k in ("head_dim", "n_kv_heads", "ffn_gated", "activation")
                if getattr(self, k) not in (None, False, "gelu")}


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
    out_M: int = None     # output width that leaves the die-set (None -> M); gated FFN: the gate x up product is formed on the die, so d_ff of the 2 d_ff columns leave
    resident_N: int = None  # resident copies of the C x M operand (None -> N); grouped K/V: n_kv_heads arrays serve n_heads of compute


def block_ops(cfg: GptConfig, S: int, phase: str = "prefill"):
    """The ops in ONE transformer block at sequence length S.

    prefill : process all S query rows at once (P = S).
    decode  : process 1 new query row, attending over the S-long KV cache (P = 1).
    """
    dh = cfg.dh
    Pq = S if phase == "prefill" else 1   # query rows this step
    Klen = S                              # keys/values ATTENDED over (compute shape)
    Hq, Hkv, Wq = cfg.n_heads, cfg.kv_heads, cfg.attn_width
    M_qkv = (Hq + 2 * Hkv) * dh           # Q (Hq dh) + K and V (Hkv dh each); = 3 d_model for the plain block
    M_ffn1 = 2 * cfg.d_ff if cfg.ffn_gated else cfg.d_ff   # gate and up projections side by side (columns interleaved gate_j, up_j so that each die holds matching pairs)
    # Rows/cols NEWLY PROGRAMMED this step. ReRAM K/V arrays are resident and
    # APPEND-ONLY: prefill programs all S tokens; decode appends just the new
    # token. (Rewriting the whole cache per step would both contradict weight
    # residency and exceed ReRAM endurance within seconds of generation.)
    Kwrite = S if phase == "prefill" else 1
    return [
        Op("qkv_proj", "static",  P=Pq, C=cfg.d_model, M=M_qkv),
        # K^T is mapped dh(rows) x Klen(cols): a new token is a new COLUMN, so its
        # dh cells land on dh DISTINCT wordlines -> dh serial SET pulses.
        Op("qk^t",     "dynamic", P=Pq, C=dh,   M=Klen, N=Hq, resident_N=Hkv,
           write_cells=dh * Kwrite * Hkv, write_rows=dh),
        # V is mapped Klen(rows) x dh(cols): a new token is a new ROW, so its dh
        # cells share ONE wordline -> 1 serial SET pulse.
        Op("av",       "dynamic", P=Pq, C=Klen, M=dh,   N=Hq, resident_N=Hkv,
           write_cells=Kwrite * dh * Hkv, write_rows=Kwrite),
        Op("out_proj", "static",  P=Pq, C=Wq, M=cfg.d_model),
        Op("ffn1",     "static",  P=Pq, C=cfg.d_model, M=M_ffn1, out_M=cfg.d_ff),
        Op("ffn2",     "static",  P=Pq, C=cfg.d_ff,    M=cfg.d_model),
    ]


# ---------------------------------------------------------------------------
# The non-matmul operators. They cannot run on the crossbars (no weight
# to multiply by); on every CIM design in the literature they run in a
# digital vector unit on the same die, next to the buffer: read the
# activations from the glb, compute, write back. Their cost is closed-form:
#   energy  = glb passes x elements x glb pJ/word  +  arithmetic x digital pJ
#   latency = arithmetic ops / (lanes x clock)          (serial with the matmuls)
# The digital unit is a platform input (fabric.digital); glb pJ/word is
# the CiMLoop-calibrated access energy of the same die.
GLB_PJ_PER_WORD_REF = 15.47      # CiMLoop ffn1 prefill run: 892 uJ / 57.67 M scalar accesses
ATTENTION_ELEMENTWISE = ("softmax",)      # moves to the digital unit with attention when attention is offloaded


@dataclass
class ElementwiseOp:
    name: str
    elements: int            # per layer (or per model for the model-end ops)
    glb_passes: int          # glb accesses per element (reads + writes)
    adds: float              # arithmetic per element, at the intermediate width
    muls: float
    luts: float
    after: str               # the matmul whose output it consumes (ledger adjacency)
    kind: str = "elementwise"

    @property
    def arith_ops(self) -> float:
        return self.elements * (self.adds + self.muls + self.luts)


def block_elementwise_ops(cfg: GptConfig, S: int, phase: str = "prefill"):
    """The non-matmul operators of ONE transformer block at sequence length S
    (prefill: S query rows; decode: 1 row attending over S keys)."""
    Pq = S if phase == "prefill" else 1
    d, ff, H = cfg.d_model, cfg.d_ff, cfg.n_heads
    return [
        # softmax over each head's Pq x S score matrix: max pass, exp+sum pass,
        # normalise pass -> 3 glb passes; per element 1 LUT (exp), 2 adds, 1 mul
        ElementwiseOp("softmax", H * Pq * S, 3, adds=2, muls=1, luts=1, after="qk^t"),
        # the FFN activation on the hidden activations (read + write): GELU
        # tanh approximation ~ 1 LUT + 3 mul + 2 add; ReLU (OPT) a compare;
        # GeGLU (Gemma) reads gate and up, GELU on the gate, one product, writes
        {"gelu": ElementwiseOp("gelu", Pq * ff, 2, adds=2, muls=3, luts=1, after="ffn1"),
         "relu": ElementwiseOp("relu", Pq * ff, 2, adds=1, muls=0, luts=0, after="ffn1"),
         "geglu": ElementwiseOp("geglu", Pq * ff, 3, adds=2, muls=4, luts=1, after="ffn1"),
         "swiglu": ElementwiseOp("swiglu", Pq * ff, 3, adds=0, muls=2, luts=1, after="ffn1")}[cfg.activation],   # silu(gate) x up: one sigmoid lookup, two multiplies per element (Qwen2.5)
        # two LayerNorms per block (pre-attention, pre-FFN): mean pass, variance
        # pass, normalise pass; per element ~ 3 adds, 2 muls, and an rsqrt LUT
        # amortised over the row
        ElementwiseOp("layernorm", 2 * Pq * d, 3, adds=3, muls=2, luts=1.0 / d, after="qkv_proj"),
        # two residual adds: read both operands, write the sum -> 3 passes, 1 add
        ElementwiseOp("residual", 2 * Pq * d, 3, adds=1, muls=0, luts=0, after="out_proj"),
    ]


def elementwise_cost(op: ElementwiseOp, digital, glb_pj_per_word: float = GLB_PJ_PER_WORD_REF):
    """Energy and latency of one elementwise operator on the digital unit."""
    n = op.elements
    glb_J = op.glb_passes * n * glb_pj_per_word * 1e-12
    arith_J = n * (op.adds * digital.pj_add + op.muls * digital.pj_mul
                   + op.luts * digital.pj_lut) * 1e-12
    latency_s = op.arith_ops / digital.ops_per_second()
    return {"name": op.name, "kind": "elementwise", "elements": n,
            "glb_J": glb_J, "arith_J": arith_J, "energy_J": glb_J + arith_J,
            "latency_s": latency_s, "glb_accesses": op.glb_passes * n,
            "arith_ops": op.arith_ops}


# ---------------------------------------------------------------------------
# A spanning model's block as a CHAIN of die-sets. Every operator's input
# arrives from the dies that own the previous operator's output (producer ->
# consumer over the die grid), not from the package attach point; what crosses
# a die-to-die wire is the tensor ONCE (the consumer's glb holds it; the
# re-reads Timeloop counts at the row drivers are on-die traffic) -- the same
# convention as the layer hand-offs. Under an
# output-column split every consumer die needs the whole input, i.e. every
# owner's piece; under an input-row split the owners hold partial sums of the
# whole output and every consumer receives all of them at partial-sum width
# (the reduction happens at the consumer). qk^t, softmax and av share one
# die (the attention die); offloaded, that die is the external unit at the
# attach point. Elementwise operators and the residual stream are not routed
# (they move through the glb only). The last die-set feeds the next
# layer's first.

ATTENTION_DIE = "attention"


def dims_for(dims, op_name):
    """The tiler's split preference for one operator: `dims` is a tuple for
    every operator, or a dict {op_name: tuple} with "*" as the default
    (per-operator mixed tilings)."""
    if isinstance(dims, dict):
        return tuple(dims.get(op_name, dims.get("*", ("M", "C"))))
    return tuple(dims)


def block_chain(cfg: GptConfig, S: int, phase: str = "prefill", on_chip: bool = True,
                max_dies: int = 24, dims=("M", "C")):
    """Data-flow order of one block's die-sets: [{name, kind, n_dies, split,
    in_words, out_words, ops}]. Static ops take their die count and split
    dim from plan_spatial; the attention die is one die consuming the whole
    Q/K/V projection output; with on_chip=False it is the external unit
    (n_dies 0 -> routed to/from the attach point)."""
    Pq = S if phase == "prefill" else 1
    ops = {o.name: o for o in block_ops(cfg, S, phase)}
    chain = []
    for name in ("qkv_proj", ATTENTION_DIE, "out_proj", "ffn1", "ffn2"):
        if name == ATTENTION_DIE:
            chain.append({"name": name, "kind": "attention" if on_chip else "unit",
                          "n_dies": 1 if on_chip else 0, "split": None,
                          "in_words": Pq * ops["qkv_proj"].M,
                          "out_words": Pq * cfg.attn_width,
                          "ops": ["qk^t", "softmax", "av"]})
            continue
        op = ops[name]
        n, dim, _ = plan_spatial(op, max_dies=max_dies, dims=dims_for(dims, name))
        if op.out_M is not None and op.out_M != op.M and dim == "C":
            raise ValueError(f"{name}: the gated product must be formed before the hand-off, which a row (C) split "
                             f"cannot do (partial sums of gate and up would have to be reduced at the consumer first)")
        chain.append({"name": name, "kind": "static", "n_dies": n, "split": dim,
                      "in_words": op.P * op.C, "out_words": op.P * (op.out_M if op.out_M is not None else op.M),
                      "ops": [name]})
    return chain


def boundary_pieces(p, e, n_prod, n_cons, psum):
    """Volume (words) and width of the flow producer i -> consumer j for one
    hand-off, by the two splits. Producer column split or one die: disjoint
    pieces of the output; producer row split: partial sums of the whole
    output at the partial-sum width, reduced at the consumer. A consumer
    that is itself row-split (its input rows sharded over its dies) needs
    only the slice of the input it owns: the overlap of producer i's column
    block with consumer j's row block (column-split producer), or 1/n_cons
    of every producer's partial sums (row-split producer). A consumer that is
    not row-split receives the whole tensor (the frozen convention)."""
    out = float(p["out_words"])
    if e.get("split") == "H":          # the offloaded attention over K units: unit j needs its head groups' Q, K and V columns of the QKV output
        if p["split"] == "C":          # partial sums of the whole output: unit j needs its columns from every producer
            return (out / n_cons, psum), None
        M = e["in_cols"]; Pq = out / M
        ranges = e["unit_cols"]        # per unit: [(start, end), ...] column ranges in words per row

        def vol_h(i, j):
            lo_i, hi_i = i * M / n_prod, (i + 1) * M / n_prod
            return Pq * sum(max(0.0, min(hi_i, b) - max(lo_i, a)) for a, b in ranges[j])
        return (None, 1.0), vol_h
    if e.get("split") != "C":
        return ((out, psum) if p["split"] == "C" else (out / n_prod, 1.0)), None
    if p["split"] == "C":
        return (out / n_cons, psum), None
    def overlap(i, j):
        lo, hi = max(i / n_prod, j / n_cons), min((i + 1) / n_prod, (j + 1) / n_cons)
        return max(0.0, hi - lo)
    return (None, 1.0), lambda i, j: out * overlap(i, j)


def boundary_flows(p, e, prod, cons, fabric):
    """Node-to-node flows of ONE hand-off p -> e (producer dies prod, consumer
    dies cons), the single convention behind block_die_flows (full path) and
    the incremental evaluator."""
    lv = fabric.level("die")
    psum = getattr(fabric, "psum_word_bytes", 2.0)
    if p["out_words"] != e["in_words"]:
        raise ValueError(f"{p['name']} -> {e['name']}: {p['out_words']} words produced, {e['in_words']} consumed")
    (piece, width), fn = boundary_pieces(p, e, len(prod), len(cons), psum)
    flows = []
    for i, a in enumerate(prod):
        for j, b in enumerate(cons):
            if a == b:
                continue
            vol = fn(i, j) if fn else piece
            if vol <= 0:
                continue
            flows.append({"level": lv.link.name, "level_name": "die",
                          "nodes": (a, b), "src": f"{p['name']}@{a}",
                          "dst": f"{e['name']}@{b}", "volume": float(vol),
                          "width": width, "distance": 0.0})
    return flows


def block_die_flows(chain, seating, fabric, psum_bytes=None):
    """Node-to-node die flows of every die-set's INPUT, from the previous
    die-set's owners (the first die-set's input comes from the last: the next
    layer's copy). {name: [flows]} for link_occupancy; each flow carries
    `width` (1.0 for activations; the fabric's partial-sum width when the
    producer split its input rows). See boundary_pieces for the convention."""
    from scripts import interconnect as ic_mod
    out, n = {}, len(chain)
    fab = fabric
    if psum_bytes is not None and float(psum_bytes) != getattr(fabric, "psum_word_bytes", 2.0):
        import copy
        fab = copy.copy(fabric); fab.psum_word_bytes = float(psum_bytes)
    for i, e in enumerate(chain):
        p = chain[(i - 1) % n]
        prod = seating.get(p["name"]) or [ic_mod.HUB]      # the unit sits at the attach point
        cons = seating.get(e["name"]) or [ic_mod.HUB]
        out[e["name"]] = boundary_flows(p, e, prod, cons, fab)
    return out


def die_flow_surplus_energy(flows, fabric, placement=None, pj_per_word=None,
                            reference_hops=None):
    """Energy of node-to-node die flows beyond the flat charge: volume x
    width x max(hops - reference, 0) x pJ per word -- the rule of
    die_to_die_activation."""
    from scripts import interconnect as ic_mod, placement as placement_mod
    lv = fabric.level("die")
    pl = placement or placement_mod.sequential_fill(fabric)
    m = ic_mod.build(fabric, "die", pl)
    pj = lv.link.pj_per_word if pj_per_word is None else pj_per_word
    ref = ((lv.link.reference_hops if lv.link.reference_hops is not None else 1.0)
           if reference_hops is None else reference_hops)
    tot = 0.0
    for f in flows:
        a, b = f["nodes"]
        tot += (f["volume"] * float(f.get("width", 1.0))
                * max(m.energy_hops(a, b) - ref, 0.0) * (pj or 0.0) * 1e-12)
    return tot


def lm_head_op(cfg: GptConfig, S: int = 512, phase: str = "prefill") -> Op:
    """The LM head IS a matmul (d_model x vocab, ~51.5 M weights -> spans dies
    under spatial_multi_die); inference evaluates it for the LAST token only
    (P = 1) in both phases. vocab is padded to the next power of two
    (50,257 -> 65,536): the residency tiler places whole dies on a
    power-of-two fanout grid, so the padding is the same utilisation loss
    the planner charges every spanning operator (stated; 77% of the
    columns carry real vocabulary)."""
    M = 1 << (cfg.vocab - 1).bit_length()
    return Op("lm_head", "static", P=1, C=cfg.d_model, M=M)


def embedding_cost(cfg: GptConfig, S: int, phase: str, fabric=None,
                   e_dram=None, cycle_seconds: float = None):
    """Embedding lookup: S x d_model words read from off-chip (decode: 1 x
    d_model), priced at the DRAM per-word energy; TIMED only if the fabric
    sets an off-chip port bandwidth (otherwise reported as not timed)."""
    from scripts import fabric as fabric_mod
    fab = fabric or fabric_mod.default()
    e = E_DRAM_PER_WORD_J if e_dram is None else e_dram
    words = (S if phase == "prefill" else 1) * cfg.d_model
    bw = fab.offchip_bandwidth_words_per_cycle
    cyc = fab.device.cycle_seconds if cycle_seconds is None else cycle_seconds
    return {"name": "embedding", "kind": "offchip_read", "words": words,
            "energy_J": words * e,
            "latency_s": (words / bw * cyc) if bw else None,
            "timed": bool(bw)}


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
# Over-capacity policy.
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
    """Physical cells the op's resident operand occupies (grouped K/V: the
    resident copies, not the compute copies)."""
    return op.C * op.M * (op.resident_N if op.resident_N is not None else op.N) * CELLS_PER_WEIGHT


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
    weights of M per array. The fanout menu is the fabric's die, macro x core x
    crossbar (8 x 4 x 8 = 256 array tiles on the base die, all powers of two;
    a capacity variant changes the macro count) -- so a non-power-of-two slice
    (e.g. d=2560 shapes) must OVER-allocate: the per-level spatial factors
    must divide the slice dims, cover them within array capacity, and fit the
    fanouts jointly. Returns [(C_f, M_f) per level] minimising wasted tiles,
    or None if no allocation exists (then the op needs more dies than raw
    capacity says -- utilisation loss from the power-of-two grid, a real
    effect the capacity ceiling alone hides). Exists because the arch's
    greedy M-first maximize_dims can starve C and silently fall back to
    temporal weight tiling (= phantom reload) even for shapes that fit."""
    fan = [mlx.N_MACROS_PER_DIE, mlx.N_CORES_PER_MACRO, mlx.CROSSBARS_PER_CORE]   # macro, core, crossbar: the fabric's die (8 x 4 x 8 on the base die; a capacity variant changes the macro count)

    def _divs(n):
        return [d for d in range(1, n + 1) if n % d == 0]

    best = None
    for c0 in _divs(fan[0]):
        for c1 in _divs(fan[1]):
            for c2 in _divs(fan[2]):
                pc = c0 * c1 * c2
                if c_res % pc or c_res // pc > 256:
                    continue
                for m0 in _divs(fan[0] // c0):
                    for m1 in _divs(fan[1] // c1):
                        for m2 in _divs(fan[2] // c2):
                            pm = m0 * m1 * m2
                            if m_res % pm:
                                continue
                            if m_res // pm > 256 // CELLS_PER_WEIGHT:
                                continue
                            waste = pc * pm           # tiles used; fewer = better
                            cand = (waste, [(c0, m0), (c1, m1), (c2, m2)])
                            if best is None or cand[0] < best[0]:
                                best = cand
    return best[1] if best else None


def plan_spatial(op: Op, max_dies: int = 24, dims=("M", "C"), min_dies=None):
    """How many dies the op ACTUALLY needs under the residency constraint,
    with the split dim and per-die tiling. May exceed dies_for_op (the raw
    capacity ceiling): the power-of-two fanout grid cannot always realise a
    non-power-of-two slice even when the cells would fit. Returns
    (n_dies, split_dim_or_None, tiles) or raises if nothing up to `max_dies`
    works. `dims=("M",)` restricts the die split to the column split (input
    multicast)."""
    lo = dies_for_op(op)
    if min_dies is not None:
        # a VOLUNTARY span (e.g. forcing 2 half-full dies); never set by
        # any default path; capacity still rules the floor.
        lo = max(lo, int(min_dies))
    for n in range(lo, max_dies + 1):
        for dim in dims if n > 1 else (None,):
            if dim is not None and getattr(op, dim) % n:
                continue
            c = op.C // n if dim == "C" else op.C
            m = op.M // n if dim == "M" else op.M
            t = _die_tiling(c, m)
            if t is not None:
                return n, dim, t
    raise ValueError(f"{op.name}: no residency tiling up to {max_dies} dies "
                     f"(C={op.C}, M={op.M}, dims={dims})")


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


# ---------------------------------------------------------------------------
# Co-residency array shares (the 48-die seating of the GPT-2-medium-class block).
#
# Two ops sharing a die each own a PARTITION of its 256 arrays; simulating
# each with the full die would be optimistic. The share plans
# below pin each op's per-level spatial factors so the mapper works inside
# the op's own arrays. Derived from the seating geometry (power-of-two
# allocation; per-array limits: 256 rows of C, 128 weights of M):
#
#   FFN die (exact fill): ffn1 128 arrays | ffn2 128 arrays
#   attention die (exact fill): qkv 128 | out_proj 32 | qk^t 64 | av 32
#
# Format: {level: (C_f, M_f, N_f)} for macro/core/crossbar. Static ops also
# get the glb temporal ban on C/M (residency); dynamic ops additionally on
# N -- a temporal head loop would re-tile the resident K/V arrays.
SHARE_355M_48DIE = {
    "qkv_proj": {"macro": (1, 8, 1), "core": (1, 4, 1), "crossbar": (4, 1, 1)},
    "out_proj": {"macro": (2, 4, 1), "core": (2, 2, 1), "crossbar": (1, 1, 1)},
    "ffn1":     {"macro": (1, 8, 1), "core": (1, 4, 1), "crossbar": (4, 1, 1)},
    "ffn2":     {"macro": (8, 1, 1), "core": (2, 2, 1), "crossbar": (1, 4, 1)},
    "qk^t":     {"macro": (1, 1, 8), "core": (1, 2, 2), "crossbar": (1, 2, 1)},
    "av":       {"macro": (1, 1, 8), "core": (2, 1, 2), "crossbar": (1, 1, 1)},
}


def run_op(op: Op, place_fn=pa.place_grid, e_write=E_WRITE_PER_CELL_J,
           phase: str = "prefill", t_set_ns=T_SET_NS, hop_latency_ns=None,
           placement=None, overcapacity: str = "reject",
           share_plan=None,
           spatial_dims=("M", "C"), spatial_max_dies=24, spatial_min_dies=None,
           save_comm=True, comm_dir=cc.DEFAULT_COMM_DIR,
           hist_source=DEFAULT_HIST_SOURCE,
           value_mode="uniform", value_source="synthetic",
           value_spread=cvmod.DEFAULT_SPREAD, strict_traffic=True):
    """Run one op on the MLX die hierarchy with its shape, attach write cost +
    latency. Returns a dict whose `output_dir` feeds crossbar_stats / crossbar_comm.

    Latency (critical path, seconds):
        total = write (serial, dynamic only)   -- ReRAM SET phase, before compute
              + compute (Timeloop cycles x cycle_time, incl. bandwidth stalls)
              + distance propagation (hops x hop_latency, the position-aware term)
    """
    n_dies_op = dies_for_op(op)
    spatial_plan = None
    if overcapacity == "spatial_multi_die" and op.kind == "static":
        # The gate must use the TILING planner, not the raw capacity ceiling:
        # a fitting-but-untilable shape (e.g. C=2560 on the power-of-two
        # fanout grid) would otherwise fall through to the greedy default and
        # reload silently.
        spatial_plan = plan_spatial(op, max_dies=spatial_max_dies, dims=spatial_dims,
                                    min_dies=spatial_min_dies)
        if spatial_plan[0] != n_dies_op:
            print(f"    [spatial: capacity says {n_dies_op} die(s) but "
                  f"the power-of-two fanout grid needs {spatial_plan[0]} -- "
                  "utilisation loss, charged honestly]", flush=True)
        n_dies_op = spatial_plan[0]
    rewrite = None
    if n_dies_op > 1:
        if overcapacity == "reject":
            raise ValueError(
                f"{op.name}: weights need {op_weight_cells(op):,} cells = "
                f"{n_dies_op} dies (one die holds {DIE_WEIGHT_CELLS:,}). "
                "Timeloop would silently time-multiplex the arrays with the "
                "reprogramming billed at zero. Choose "
                "overcapacity='temporal_rewrite' (charge the rewrite) or "
                "'spatial_multi_die' (span dies, weights resident).")
        if overcapacity == "temporal_rewrite":
            if op.kind != "static":
                raise NotImplementedError(
                    "temporal_rewrite covers static ops; over-capacity "
                    "K/V arrays need their own policy")
            rewrite = static_rewrite_cost(op, e_write, t_set_ns)
            print(f"    [temporal_rewrite: {rewrite['cells']:,} cells "
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
        if share_plan is not None:
            # confine the op to its co-residency array share by pinning
            # the per-level spatial factors; ban the glb temporal sinks for
            # every resident dim (C/M always; N too -- a temporal head loop
            # re-tiles resident K/V arrays).
            for _cname, _lv in (("macro_in_die", "macro"),
                                ("core_in_macro", "core"),
                                ("crossbar_in_core", "crossbar")):
                _cf, _mf, _nf = share_plan[_lv]
                _cn = spec.architecture.find(_cname).constraints.spatial
                _cn.pop("maximize_dims", None)
                _cn.factors.append(f'"C={_cf}"')
                _cn.factors.append(f'"M={_mf}"')
                _cn.factors.append(f'"N={_nf}"')
                # P/Q spatial would REPLICATE weights into arrays the
                # co-resident neighbour owns -- pin them off, so the product
                # of pinned factors IS the op's array share.
                _cn.factors.append('"P=1"')
                _cn.factors.append('"Q=1"')
            for _name in ("glb", "chip2chip_link"):
                _fac = spec.architecture.find(_name).constraints.temporal.factors
                for _i in range(len(_fac) - 1, -1, -1):
                    if str(_fac[_i]).startswith(("C=", "M=", "N=")):
                        del _fac[_i]
                _fac.append('"C=1"')
                _fac.append('"M=1"')
                _fac.append('"N=1"')
        if spatial_plan is not None:
            # Pin the whole per-die C/M tiling closed-form (chosen by the
            # planner above -- M-split preferred: input multicast across dies
            # beats a cross-die partial-sum reduction). We must not leave
            # this to the arch's greedy M-first maximize_dims: it can starve
            # C and dump the remainder into glb's temporal sink -- the
            # phantom reload this policy exists to eliminate.
            _n, _dim, _tiles = spatial_plan
            _chip = spec.architecture.find("chip_in_system")
            if _n > 1:
                _chip.spatial.meshX = _n
            if _dim is not None:
                _chip.constraints.spatial.factors.append(f'"{_dim}={_n}"')
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
    if share_plan is not None:
        import os as _os
        _mp = _os.path.join(res.output_dir, "timeloop-mapper.map.txt")
        _txt = open(_mp).read() if _os.path.exists(_mp) else ""
        if _temporal_weight_loads(_txt) != 1:
            raise ValueError(
                f"{op.name}: share-constrained mapping temporally re-tiles "
                "resident arrays -- share plan and mapper disagree")
    if spatial_plan is not None:
        import os as _os
        _mp = _os.path.join(res.output_dir, "timeloop-mapper.map.txt")
        _txt = open(_mp).read() if _os.path.exists(_mp) else ""
        if _temporal_weight_loads(_txt) != 1:
            raise ValueError(
                f"{op.name}: spatial_multi_die mapping still temporally "
                "re-tiles the weights -- residency constraint did not hold")
        if n_dies_op > 1 and "inter_chip_in_system_spatial" not in _txt:
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
    mlx.FABRIC.verify_cycle(res.cycle_seconds)   # the run's CiMLoop cycle must be the fabric's device cycle
    compute_lat = res.cycles * res.cycle_seconds                 # Timeloop native
    level_hops = cc.level_max_hops(mlx.FABRIC, pl)   # placement-aware geometry
    dist = pa.position_aware_latency(level_hops,
                                     hop_latency_ns or mlx.HOP_LATENCY_NS)
    dist_lat = dist["total_ns"] * 1e-9
    wr_lat = write_latency_s(op, phase, t_set_ns)
    if rewrite is not None:
        wr_lat += rewrite["latency_s"]              # serial, before compute
    # Static contention: the worst network link's serialization time.
    # Between the two tiers the composition is MAX, never sum -- Timeloop's
    # own throttling (storage hubs) and the per-link tier both lower-bound
    # the same serialization. Between compute and network the truth lies in
    # [max, sum]: max = perfect overlap (double-buffered), sum = zero overlap.
    # Both ends are returned; the max end is the reported one.
    # All-zero unless a fabric link carries a bandwidth (default: none do).
    traffic_guard_error = None
    try:
        flows_q, _, _, _ = cc.build_flows(res.output_dir, verbose=False,
                                          fabric=mlx.FABRIC, placement=pl)
        occ = cc.link_occupancy(flows_q, mlx.FABRIC, res.cycle_seconds)
    except ValueError as e:
        # The traffic extraction's conservation guard refused this mapping.
        # By default that is an error (the guard is the platform's counting
        # discipline); an account-measurement caller may pass
        # strict_traffic=False to keep the compute, write and energy readings
        # (all computed above, independent of the flow decomposition) and
        # record the refusal instead.
        if strict_traffic:
            raise
        traffic_guard_error = f"{type(e).__name__}: {e}"
        occ = {"serialization_s": 0.0, "bottleneck": None}
    contention_lat = occ["serialization_s"]
    total_lat = wr_lat + max(compute_lat, contention_lat) + dist_lat
    total_lat_sum = wr_lat + compute_lat + contention_lat + dist_lat

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
        "total_latency_sum_s": total_lat_sum,
        "comm_files": comm_files,                     # (csv, json) of per-pair flows
        "traffic_guard_error": traffic_guard_error,   # None unless strict_traffic=False caught a refusal
        "levels": r["levels"],                        # perceived components (unit_pJ ...)
        "value_mode": value_mode,
        "crossbar_value": crossbar_value,             # per-crossbar energy spread or None
        "overcapacity": overcapacity if n_dies_op > 1 else None,
        "dies_for_op": n_dies_op,
        "rewrite": rewrite,                           # temporal_rewrite account or None
    }


# ---------------------------------------------------------------------------
# KV-cache model (the decode-phase memory bottleneck).
#
# During decode, each step appends the new token's K,V to a cache and the
# attention reads the WHOLE cache. The cache is large (2 * S * d_model * n_layers
# * precision -> ~100s of MB for long S), so it lives off-chip; reads dominate.
#   per step at context length t (one layer): read 2*t*d, write 2*d words.
#   generating G tokens total:  read ~ G^2 * d  (QUADRATIC), write ~ G * d.
# ---------------------------------------------------------------------------
# Off-chip (DRAM) access energy per 8-bit word, LPDDR class (~6 pJ/bit);
# used for the embedding read.
E_DRAM_PER_WORD_J = 5.0e-11
