"""Group 20 -- the non-matmul operators on the digital unit (O24).

Closed-form terms, so what can go wrong is bookkeeping: element counts vs
the block's shapes, which operators leave with the attention, the single
source of the half-layer stages, and the direction of the change (adding
the terms never lowers an absolute, never raises a contention multiplier).
"""
from _util import approx

from scripts import fabric
from scripts import llm_workload as lw

CFG = lw.GptConfig()
FAB = fabric.default()


def test_element_counts_follow_the_shapes():
    """softmax = H x S x S (prefill) / H x S (decode); GELU = S x d_ff;
    LayerNorm and residual = 2 x S x d_model."""
    for phase, Pq in (("prefill", 512), ("decode", 1)):
        e = {o.name: o.elements for o in lw.block_elementwise_ops(CFG, 512, phase)}
        assert e["softmax"] == CFG.n_heads * Pq * 512
        assert e["gelu"] == Pq * CFG.d_ff
        assert e["layernorm"] == 2 * Pq * CFG.d_model
        assert e["residual"] == 2 * Pq * CFG.d_model


def test_cost_scales_with_the_digital_unit():
    """latency = arithmetic / (lanes x clock): doubling the lanes halves it;
    energy = glb passes x glb pJ/word + arithmetic x per-op pJ, and the glb
    part dominates at the calibrated 15.47 pJ/word."""
    import dataclasses
    d1 = FAB.digital
    d2 = dataclasses.replace(d1, lanes=2 * d1.lanes)
    for eo in lw.block_elementwise_ops(CFG, 512, "prefill"):
        c1, c2 = lw.elementwise_cost(eo, d1), lw.elementwise_cost(eo, d2)
        approx(c1["latency_s"], 2 * c2["latency_s"], 1e-12)
        assert c1["energy_J"] == c2["energy_J"]
        assert c1["glb_J"] > c1["arith_J"]
        approx(c1["glb_J"], eo.glb_passes * eo.elements * lw.GLB_PJ_PER_WORD_REF * 1e-12, 1e-12)


def test_softmax_leaves_with_attention_the_rest_stays():
    assert not lw.stays_on_chip_under_offload("softmax")
    assert not lw.stays_on_chip_under_offload("qk^t")
    assert not lw.stays_on_chip_under_offload("av")
    for name in ("gelu", "layernorm", "residual", "qkv_proj", "out_proj", "ffn1", "ffn2"):
        assert lw.stays_on_chip_under_offload(name), name


def test_half_layer_stages_single_source():
    """Without elementwise records the shared helper reproduces the pinned
    v2/v3 stages (23.49312 / 10.38336 ms); with them, both halves grow and
    the attention half grows more (it carries the softmax)."""
    from _util import golden
    per = golden("stack_per_op_v3.json")["phases"]["prefill"]["per_op"]["star (private links)"]
    a, b = lw.half_layer_stages(per)
    approx(a, 0.02349312, 1e-12)
    approx(b, 0.01038336, 1e-12)
    elw = [{"name": eo.name, "compute_s": lw.elementwise_cost(eo, FAB.digital)["latency_s"],
            "write_s": 0.0} for eo in lw.block_elementwise_ops(CFG, 512, "prefill")]
    a2, b2 = lw.half_layer_stages(per + elw)
    assert a2 > a and b2 > b
    assert (a2 - a) > (b2 - b)


def test_shipped_generic_unit_magnitudes():
    """The generic configuration (64 lanes @ 1 GHz, Horowitz energies):
    one prefill block's non-matmul operators cost ~0.37 mJ x 10^-3 ... i.e.
    371.6 uJ and 0.557 ms -- +3% energy and +1% latency on the 355M stack.
    Pinned so a silent default change shows."""
    tot_e = sum(lw.elementwise_cost(eo, FAB.digital)["energy_J"]
                for eo in lw.block_elementwise_ops(CFG, 512, "prefill"))
    tot_l = sum(lw.elementwise_cost(eo, FAB.digital)["latency_s"]
                for eo in lw.block_elementwise_ops(CFG, 512, "prefill"))
    approx(tot_e, 371.6e-6, 2e-3)
    approx(tot_l, 0.557e-3, 2e-3)
    assert FAB.digital.lanes == 64 and FAB.digital.clock_hz == 1.0e9


def test_embedding_priced_not_timed_by_default():
    emb = lw.embedding_cost(CFG, 512, "prefill", fabric=FAB)
    assert emb["words"] == 512 * CFG.d_model
    approx(emb["energy_J"], emb["words"] * lw.E_DRAM_PER_WORD_J, 1e-12)
    assert emb["latency_s"] is None and not emb["timed"]
    lm = lw.lm_head_op(CFG)
    assert lm.P == 1 and lm.M == 65536 and lm.M >= CFG.vocab


# -------------------------------------------------- v4: the published numbers
def _v4():
    from _util import golden
    return golden("stack_per_op_v4.json")


def test_v4_stack_and_stages():
    """v4 = v3 + the four elementwise rows: stall-free prefill stack 826.42 ms
    (+13.37 ms of digital time, 1.6%), decode 14.80 ms; half-layer stages
    23.80 / 10.63 ms (the FFN die now carries the GELU); dividend +124%."""
    fx = _v4()
    pre = fx["phases"]["prefill"]["per_op"]["star (private links)"]
    sf = sum(o["latency_s"] for o in pre) * 24           # star is network-free at 16,384 w/c
    approx(sf, 0.82642, 1e-4)
    approx(fx["phases"]["prefill"]["elementwise_s"], 0.01337, 2e-3)
    a, b = lw.half_layer_stages(pre)
    approx(a, 0.02380, 1e-3)
    approx(b, 0.01063, 1e-3)
    approx(a / b, 2.24, 5e-3)
    dec = fx["phases"]["decode"]["per_op"]["star (private links)"]
    approx(sum(o["latency_s"] for o in dec) * 24, 0.01480, 1e-3)


def test_v4_anchored_readout_eases_slightly():
    """With the digital terms in the denominator every multiplier eases by a
    percent or two and nothing re-ranks: Simba prefill 1.03 / 1.84 / 2.86 /
    2.33 / 5.24 (v3: 1.03 / 1.85 / 2.89 / 2.36 / 5.31), hub lever 1.55."""
    fx = _v4()
    REF = fx["ref_words_per_cycle"]; WC = 1e9 * 1.4485714285714284e-06
    def stack(label, gbps):
        per = fx["phases"]["prefill"]["per_op"][label]
        tot = base = 0.0
        for o in per:
            ser = o["serial_s"] * REF / (gbps * WC)
            tot += o["write_s"] + max(o["compute_s"], ser)
            base += o["write_s"] + o["compute_s"]
        return tot / base
    want = {"star (private links)": 1.03, "mesh, glb centre": 1.84,
            "mesh, glb corner": 2.86, "h-tree (k=4)": 2.33, "bus (shared medium)": 5.24}
    for label, v in want.items():
        approx(stack(label, 8.75), v, 5e-3)
    approx(stack("mesh, glb corner", 8.75) / stack("mesh, glb centre", 8.75), 1.55, 5e-3)
    order = ["star (private links)", "mesh, glb centre", "h-tree (k=4)",
             "mesh, glb corner", "bus (shared medium)"]
    vals = [stack(l, 8.75) for l in order]
    assert vals == sorted(vals)


def test_v4_d2d_knees_grid_reading():
    """At the v4 stage (23.80 ms) the 32 w/c point of the snake / sequential
    chains sits 0.3% UNDER the compute beat, so the power-of-two knee reads
    16 w/c (v3: 32); far pairs 64 (v3: 128); bus unchanged at 1,024. A grid
    artefact of a 1.3% longer stage, pinned so nobody mistakes it for a
    mechanism change."""
    from scripts import placement
    from scripts.analyze_d2d import assignments, with_link, UNITS, MULTI
    fab0 = fabric.from_yaml(MULTI)
    ucfg = lw.GptConfig(n_layers=UNITS, name="units48")
    stage = 0.02380
    want = {"snake": 16, "sequential rows": 16, "far pairs (adversarial)": 64}
    for lbl, asg in assignments(fab0):
        ys = {}
        for bw in (8.0, 16.0, 32.0, 64.0, 128.0, 256.0):
            f = with_link(fab0, "mesh", {"routing": "xy", "hub": "center"}, bw)
            d = lw.die_pipeline_interval(ucfg, 512, "prefill", stage, fabric=f,
                                         assignment=asg, cycle_seconds=1.449e-6)
            ys[bw] = d["interval_s"] / stage
        k1 = max(bw for bw, y in ys.items() if y >= 1.01)
        assert k1 == want[lbl], (lbl, k1, ys)
