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


# ---------------------------------------------------------------------------
# O24: the non-matmul operators. They cannot run on the crossbars (no weight
# to multiply by); on every CIM design in the literature they run in a
# digital vector unit on the same die, next to the buffer: read the
# activations from the glb, compute, write back. Their cost is closed-form:
#   energy  = glb passes x elements x glb pJ/word  +  arithmetic x digital pJ
#   latency = arithmetic ops / (lanes x clock)          (serial with the matmuls)
# The digital unit is a platform input (fabric.digital, DR-8); glb pJ/word is
# the CiMLoop-calibrated access energy of the same die.
GLB_PJ_PER_WORD_REF = 15.47      # ffn1 prefill fixture: 892 uJ / 57.67 M scalar accesses
ATTENTION_ELEMENTWISE = ("softmax",)      # leaves the chip with attention (scenario B)


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
        # GELU on the FFN hidden activations: read + write; tanh approximation
        # ~ 1 LUT + 3 mul + 2 add
        ElementwiseOp("gelu", Pq * ff, 2, adds=2, muls=3, luts=1, after="ffn1"),
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
# O9: attention offloaded to an ABSTRACT external unit (fabric.attention_unit).
# The unit sits off the die at the package attach point (the die-level
# scheme's hub) with its own K/V memory. Per layer, three streams cross the
# die<->unit link: Q out, the new tokens' K and V out (appended to the unit's
# memory), the attention output back. The unit computes QK^T, softmax and AV
# for all stored tokens. No internal structure: rate, average cost, K/V
# memory rate/energy, link -- the DR-9 interface.
def offload_streams(cfg: GptConfig, S: int, phase: str = "prefill"):
    """Per-layer word counts of the three die<->unit streams (8-bit words)."""
    Pq = S if phase == "prefill" else 1
    return {"q_out": Pq * cfg.d_model,            # Q of this step's rows
            "kv_out": 2 * Pq * cfg.d_model,       # K and V of this step's rows
            "attn_back": Pq * cfg.d_model}        # attention output rows


def attention_unit_cost(cfg: GptConfig, S: int, phase: str, unit,
                        context: int = None, cycle_seconds: float = None,
                        hops: float = None):
    """Per-layer cost of the offloaded attention on the external unit.

    Serial inside the unit (stated): K/V append write, K/V read of all
    `context` stored tokens, QK^T + softmax + AV arithmetic at the unit's MAC
    rate (softmax's element operations counted as MAC-equivalents), plus a
    fixed per-call overhead. Link: Q + K/V share the die->unit direction, the
    attention output uses the unit->die direction; each timed at the link
    bandwidth. `hops` (die->attach point) prices the link energy at
    hops x pj per word (these words are NOT in the CiMLoop account, so no
    flat charge exists to replace -- the full path is billed). Die-side
    quantities carry the die placement: every script passes
    `unit_link_hops()` (the mean over the attention dies under the seating);
    `hops=None` falls back to the interface's reference hop count.
    `cycle_seconds=None` = the fabric's device cycle (O17a)."""
    if cycle_seconds is None:
        from scripts import fabric as fabric_mod
        cycle_seconds = fabric_mod.default().device.cycle_seconds
    Pq = S if phase == "prefill" else 1
    ctx = S if context is None else context
    st = offload_streams(cfg, S, phase)
    d, H = cfg.d_model, cfg.n_heads
    macs = 2 * Pq * ctx * d                      # QK^T and AV over all stored tokens
    softmax_ops = H * Pq * ctx * 4               # 2 adds + 1 mul + 1 lookup per score
    ops = macs + softmax_ops
    compute_s = ops / unit.mac_per_second + unit.call_overhead_s
    compute_J = ops * unit.pj_per_mac * 1e-12
    kv_write_words = st["kv_out"]
    kv_read_words = 2 * ctx * d                  # all stored K and V, once per layer
    kv_s = (kv_write_words + kv_read_words) / unit.kv_words_per_second
    kv_J = (kv_write_words * unit.kv_pj_per_word_write
            + kv_read_words * unit.kv_pj_per_word_read) * 1e-12
    bw = unit.link_bandwidth_words_per_cycle
    link_out_s = (st["q_out"] + st["kv_out"]) / bw * cycle_seconds
    link_back_s = st["attn_back"] / bw * cycle_seconds
    h = unit.link_reference_hops if hops is None else hops
    link_J = (st["q_out"] + st["kv_out"] + st["attn_back"]) * h * unit.link_pj_per_word * 1e-12
    return {"macs": macs, "softmax_ops": softmax_ops,
            "compute_s": compute_s, "compute_J": compute_J,
            "kv_write_words": kv_write_words, "kv_read_words": kv_read_words,
            "kv_s": kv_s, "kv_J": kv_J,
            "link_out_s": link_out_s, "link_back_s": link_back_s, "link_J": link_J,
            "link_hops": h,
            "unit_s": compute_s + kv_s,                       # time inside the unit
            "chain_s": link_out_s + compute_s + kv_s + link_back_s,   # one layer, serial
            "energy_J": compute_J + kv_J + link_J,
            "streams": st}


def offload_flows(cfg: GptConfig, S: int, phase: str, attention_dies):
    """The die<->unit streams as node-to-node flows for link_occupancy: from
    each attention die to the package attach point (HUB) and back. Activation
    width, one direction each; they share the die links with the layer
    hand-offs."""
    from scripts import interconnect as ic
    st = offload_streams(cfg, S, phase)
    flows = []
    for d in attention_dies:
        flows.append({"level": "die<->die", "level_name": "die", "nodes": (d, ic.HUB),
                      "src": f"die{d}", "dst": "attention_unit",
                      "volume": float(st["q_out"] + st["kv_out"]), "distance": 0.0})
        flows.append({"level": "die<->die", "level_name": "die", "nodes": (ic.HUB, d),
                      "src": "attention_unit", "dst": f"die{d}",
                      "volume": float(st["attn_back"]), "distance": 0.0})
    return flows


def unit_link_hops(fabric=None, assignment="snake", n_layers: int = None):
    """Mean hop count from the attention dies to the package attach point
    (HUB) under the die placement -- the count that prices the offload
    streams' link energy (O9). Die-side quantities carry the die placement by
    default: `fabric` None, or a fabric with fewer dies than the seating
    needs (the single-die file), means the canonical 48-die package
    (analyze_d2d.MULTI); the die scheme is the routed
    grid with the hub at the centre and the seating `assignment` is one of
    analyze_d2d.assignments' labels or an explicit unit->slot list. The unit's
    own internals stay average costs (rate, pJ per MAC, K/V memory)."""
    from scripts import fabric as fabric_mod, placement as pm, interconnect as ic
    from scripts.analyze_d2d import assignments, with_link, MULTI
    L = GptConfig().n_layers if n_layers is None else n_layers
    fab = fabric
    if (fab is None or not any(l.name == "die" for l in fab.levels)
            or fab.count_below("die") < 2 * L):        # fewer dies than the seating: canonical package
        fab = fabric_mod.from_yaml(MULTI)
    fm = with_link(fab, "mesh", {"routing": "xy", "hub": "center"}, 256.0)
    pl = pm.sequential_fill(fm)
    m = ic.build(fm, "die", pl)
    asg = dict(assignments(fm))[assignment] if isinstance(assignment, str) else assignment
    adies = attention_dies_of_chain(L, asg)
    return sum(m.hops(ic.HUB, d) for d in adies) / len(adies)


# ---------------------------------------------------------------------------
# O13: a spanning model's block as a CHAIN of die-sets. Every operator's input
# arrives from the dies that own the previous operator's output (producer ->
# consumer over the die grid), not from the package attach point; what crosses
# a die-to-die wire is the tensor ONCE (the consumer's glb holds it; the
# re-reads Timeloop counts at the row drivers are on-die traffic) -- the same
# convention as the layer hand-offs (die_to_die_activation). Under an
# output-column split every consumer die needs the whole input, i.e. every
# owner's piece; under an input-row split the owners hold partial sums of the
# whole output and every consumer receives all of them at partial-sum width
# (the reduction happens at the consumer). qk^t, softmax and av share one
# die (the attention die); offloaded, that die is the external unit at the
# attach point. Elementwise operators and the residual stream are not routed
# (O24: they move through the glb only). The last die-set feeds the next
# layer's first (a loop -- the joint seating of many layers is O16).

ATTENTION_DIE = "attention"


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
                          "in_words": Pq * 3 * cfg.d_model,
                          "out_words": Pq * cfg.d_model,
                          "ops": ["qk^t", "softmax", "av"]})
            continue
        op = ops[name]
        n, dim, _ = plan_spatial(op, max_dies=max_dies, dims=dims)
        chain.append({"name": name, "kind": "static", "n_dies": n, "split": dim,
                      "in_words": op.P * op.C, "out_words": op.P * op.M,
                      "ops": [name]})
    return chain


def seat_block(fabric, chain, style: str = "clustered", placement=None):
    """DISJOINT die slots for every die-set of the chain, seated in data-flow
    order. clustered: the nearest free slots to the attach point; row-fill:
    the placement's slot order; spread: farthest-point sampling (every new
    die as far as possible from every seated die). Returns {name: [die node
    indices]} (indices into placement.slots['die'])."""
    from scripts import interconnect as ic_mod, placement as placement_mod
    pl = placement or placement_mod.sequential_fill(fabric)
    slots = pl.slots["die"]
    hub = ic_mod.build(fabric, "die", pl).hub_coord()
    need = sum(e["n_dies"] for e in chain)
    if need > len(slots):
        raise ValueError(f"the block needs {need} dies, the package has {len(slots)}")
    if style not in ("clustered", "row-fill", "spread"):
        raise ValueError(f"unknown seating style '{style}'")

    def manh(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])
    free = list(range(len(slots)))
    if style == "clustered":
        free.sort(key=lambda i: (manh(slots[i], hub), i))
    seating, taken = {}, []
    for e in chain:
        mine = []
        for _ in range(e["n_dies"]):
            if style == "spread" and taken:
                pick = max(free, key=lambda i: (min(manh(slots[i], slots[t]) for t in taken), -i))
            else:
                pick = free[0]
            free.remove(pick)
            taken.append(pick)
            mine.append(pick)
        seating[e["name"]] = mine
    return seating


def block_die_flows(chain, seating, fabric, psum_bytes=None):
    """Node-to-node die flows of every die-set's INPUT, from the previous
    die-set's owners (the first die-set's input comes from the last: the next
    layer's copy). {name: [flows]} for link_occupancy; each flow carries
    `width` (1.0 for activations; the fabric's partial-sum width when the
    producer split its input rows)."""
    from scripts import interconnect as ic_mod
    lv = fabric.level("die")
    psum = (getattr(fabric, "psum_word_bytes", 2.0) if psum_bytes is None
            else float(psum_bytes))
    out, n = {}, len(chain)
    for i, e in enumerate(chain):
        p = chain[(i - 1) % n]
        prod = seating.get(p["name"]) or [ic_mod.HUB]      # the unit sits at the attach point
        cons = seating.get(e["name"]) or [ic_mod.HUB]
        if p["out_words"] != e["in_words"]:
            raise ValueError(f"{p['name']} -> {e['name']}: {p['out_words']} words "
                             f"produced, {e['in_words']} consumed")
        if p["split"] == "C":          # partial sums of the whole output, reduced at the consumer
            piece, width = float(p["out_words"]), psum
        else:                          # column split / one die / the unit: disjoint pieces of the tensor
            piece, width = p["out_words"] / len(prod), 1.0
        flows = []
        for a in prod:
            for b in cons:
                if a == b:
                    continue
                flows.append({"level": lv.link.name, "level_name": "die",
                              "nodes": (a, b), "src": f"{p['name']}@{a}",
                              "dst": f"{e['name']}@{b}", "volume": float(piece),
                              "width": width, "distance": 0.0})
        out[e["name"]] = flows
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
                * max(m.hops(a, b) - ref, 0.0) * (pj or 0.0) * 1e-12)
    return tot


def attention_dies_of_chain(n_layers: int, assignment=None):
    """In the two-dies-per-layer seating, unit 2L is layer L's attention die;
    `assignment` maps unit index -> die slot."""
    units = [2 * L for L in range(n_layers)]
    return units if assignment is None else [assignment[u] for u in units]


def half_layer_stages(per_op):
    """Per-die pipeline stages of the feasible 48-die configuration (two dies
    per layer) from a per-op record list ({name, compute_s, write_s}).
    Scenario A: the attention die carries qkv / qk^t / av / out_proj, the K/V
    write, the softmax, and half of the block's LayerNorm + residual work;
    the FFN die carries ffn1 / ffn2, the GELU, and the other half. Scenario
    B: qk^t / av / softmax and the write leave with the attention. The
    stage is the slower half. The single source for every script (O18/O24)."""
    t = {o["name"]: o["compute_s"] + o.get("write_s", 0.0) for o in per_op}
    g = lambda k: t.get(k, 0.0)
    half = 0.5 * (g("layernorm") + g("residual"))
    attn_A = g("qkv_proj") + g("qk^t") + g("av") + g("out_proj") + g("softmax") + half
    attn_B = g("qkv_proj") + g("out_proj") + half
    ffn = g("ffn1") + g("ffn2") + g("gelu") + half
    return max(attn_A, ffn), max(attn_B, ffn)


def stays_on_chip_under_offload(name: str) -> bool:
    """Scenario B (attention offloaded): the attention matmuls (qk^t, av) and
    the softmax between them leave the chip; everything else stays."""
    return name not in ("qk^t", "av") + ATTENTION_ELEMENTWISE


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


def attention_die_context_ceiling(cfg: GptConfig) -> int:
    """O21 (C38): the context ceiling of the feasible two-dies-per-layer
    seating (C13). The attention die holds qkv_proj (d x 3d) and out_proj
    (d x d) resident -- 8 d^2 cells at CELLS_PER_WEIGHT = 2 -- plus the
    K/V arrays, which grow by one K column and one V row per token
    (2 x d values = 4d cells). Ceiling = free cells / cells per token =
    (DIE_WEIGHT_CELLS - 8 d^2) / (4 d); at d = 1024 that is
    (16,777,216 - 8,388,608) / 4,096 = 2,048 tokens. This is the
    CELL-capacity ceiling: array-granularity packing can only round it
    DOWN, so it is the upper bound of the seating's validity domain
    (prompt + generated tokens). No S = 512 number is affected; the
    long-context mechanism itself is O14."""
    resident_cells = 4 * cfg.d_model * cfg.d_model * CELLS_PER_WEIGHT
    per_token_cells = 2 * cfg.d_model * CELLS_PER_WEIGHT
    return int((DIE_WEIGHT_CELLS - resident_cells) // per_token_cells)


def check_context_ceiling(cfg: GptConfig, context: int):
    """Raise when a context (prompt + generated tokens) exceeds the
    two-dies-per-layer seating's K/V ceiling (O21)."""
    cap = attention_die_context_ceiling(cfg)
    if context > cap:
        raise ValueError(
            f"context {context} tokens exceeds the attention die's K/V "
            f"ceiling of {cap} for the two-dies-per-layer seating (O21): "
            f"the 48-die configuration is INVALID past it -- the "
            f"long-context mechanism itself is O14")


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
    weights of M per array. The fanout menu is macro 8 x core 4 x crossbar 8
    = 256 array tiles, all powers of two -- so a non-power-of-two slice
    (e.g. d=2560 shapes) must OVER-allocate: the per-level spatial factors
    must divide the slice dims, cover them within array capacity, and fit the
    fanouts jointly. Returns [(C_f, M_f) per level] minimising wasted tiles,
    or None if no allocation exists (then the op needs more dies than raw
    capacity says -- utilisation loss from the power-of-two grid, a real
    effect the capacity ceiling alone hides). Exists because the arch's
    greedy M-first maximize_dims can starve C and silently fall back to
    temporal weight tiling (= phantom reload) even for shapes that fit."""
    fan = [8, 4, 8]                                  # macro, core, crossbar

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


def plan_spatial(op: Op, max_dies: int = 24, dims=("M", "C")):
    """How many dies the op ACTUALLY needs under the residency constraint,
    with the split dim and per-die tiling. May exceed dies_for_op (the raw
    capacity ceiling): the power-of-two fanout grid cannot always realise a
    non-power-of-two slice even when the cells would fit. Returns
    (n_dies, split_dim_or_None, tiles) or raises if nothing up to `max_dies`
    works. `dims=("M",)` restricts the die split to the column split (input
    multicast) -- the scaling-law probes (O17c) run in that regime only; the
    row split is the O15 branch and stays unexercised."""
    lo = dies_for_op(op)
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
# O12: co-residency array shares (the feasible 48-die seating, C13).
#
# Two ops sharing a die each own a PARTITION of its 256 arrays; simulating
# each with the full die makes every 355M base optimistic. The share plans
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


def share_arrays(plan):
    out = 1
    for lv in ("macro", "core", "crossbar"):
        c, m, n = plan[lv]
        out *= c * m * n
    return out


def run_op(op: Op, place_fn=pa.place_grid, e_write=E_WRITE_PER_CELL_J,
           phase: str = "prefill", t_set_ns=T_SET_NS, hop_latency_ns=None,
           placement=None, overcapacity: str = "reject",
           share_plan=None,
           spatial_dims=("M", "C"), spatial_max_dies=24,
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
    spatial_plan = None
    if overcapacity == "spatial_multi_die" and op.kind == "static":
        # The gate must use the TILING planner, not the raw capacity ceiling:
        # a fitting-but-untilable shape (e.g. C=2560 on the power-of-two
        # fanout grid) would otherwise fall through to the greedy default and
        # reload silently.
        spatial_plan = plan_spatial(op, max_dies=spatial_max_dies, dims=spatial_dims)
        if spatial_plan[0] != n_dies_op:
            print(f"    [O10 spatial: capacity says {n_dies_op} die(s) but "
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
        if share_plan is not None:
            # O12: confine the op to its co-residency array share by pinning
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
    mlx.FABRIC.verify_cycle(res.cycle_seconds)   # O17a: the run's CiMLoop cycle IS the fabric's device
    compute_lat = res.cycles * res.cycle_seconds                 # Timeloop native
    level_hops = cc.level_max_hops(mlx.FABRIC, pl)   # placement-aware geometry
    dist = pa.position_aware_latency(level_hops,
                                     hop_latency_ns or mlx.HOP_LATENCY_NS)
    dist_lat = dist["total_ns"] * 1e-9
    wr_lat = write_latency_s(op, phase, t_set_ns)
    if rewrite is not None:
        wr_lat += rewrite["latency_s"]              # serial, before compute
    # T2 static contention: the worst network link's serialization time.
    # Between the two TIERS the composition is MAX, never sum -- Timeloop's
    # own throttling (T1, storage hubs) and our per-link tier both lower-bound
    # the same serialization. Between compute and network the truth lies in
    # [max, sum]: max = perfect overlap (double-buffered), sum = zero overlap.
    # Both ends are returned (O7 bracket); the max end is the headline.
    # All-zero unless a fabric link carries a bandwidth (default: none do).
    flows_q, _, _, _ = cc.build_flows(res.output_dir, verbose=False,
                                      fabric=mlx.FABRIC, placement=pl)
    occ = cc.link_occupancy(flows_q, mlx.FABRIC, res.cycle_seconds)
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
    if len(pl.slots["die"]) >= 2 * cfg.n_layers:
        # the two-dies-per-layer seating (C13): its K/V ceiling applies (O21)
        check_context_ceiling(cfg, S)
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
                          cycle_seconds=None,
                          duplex=None, psum_bytes=None):
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

    Assumptions (stated): perfect microbatch pipelining, no bubbles, weights
    resident. interval_s assumes transfer/compute overlap via double
    buffering (perfect-overlap end); interval_sum_s assumes zero overlap
    (the O7 bracket's other end) -- the true beat lies between them.
    Returns {"interval_s", "interval_sum_s", "net_s", "network_bound",
    "flows"}. With no die bandwidth set net_s is 0 and both ends equal the
    compute stage -- the same off-by-default discipline as every other
    contention term.
    """
    from scripts import fabric as fabric_mod
    from scripts import placement as placement_mod
    import scripts.crossbar_comm as cc
    fab = fabric or fabric_mod.default()
    pl = placement or placement_mod.sequential_fill(fab)
    d = die_to_die_activation(cfg, S, phase, fabric=fab, placement=pl,
                              assignment=assignment)
    cyc = cycle_seconds if cycle_seconds is not None else fab.device.cycle_seconds   # O17a
    occ = cc.link_occupancy(d["flows"], fab, cyc, pl,
                            duplex=duplex, psum_bytes=psum_bytes)
    net = occ["serialization_s"]
    return {"interval_s": max(stage_s, net), "interval_sum_s": stage_s + net,
            "net_s": net,
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
