"""Group 16 -- over-capacity policy (FIXLIST O10).

The silent path is closed: an op whose weights exceed one die must go through
an explicit policy. Closed-form here; the mapper-level behaviour of the two
mechanisms is exercised by the probes in analyze docs / the slow tier.
"""
from _util import approx

from scripts import llm_workload as lw

CFG = lw.GptConfig()
DIE = lw.DIE_WEIGHT_CELLS                       # 16,777,216 cells


def test_capacity_closed_forms():
    """A weight occupies TWO cells (W4A8 differential encoding, the Y=2
    column split in every mapping) -- one die holds 8.39M weights, not
    16.78M. GPT-2 medium: every op fits one die (ffn1 = exactly half), but
    one LAYER = 2 dies of cells. A 1.3B-class ffn (d=2048, ff=8192) needs 2
    dies per op; its layer needs 6."""
    for op in lw.block_ops(CFG, S=512, phase="prefill"):
        assert lw.dies_for_op(op) == 1, op.name
    ffn1 = [o for o in lw.block_ops(CFG, S=512, phase="prefill")
            if o.name == "ffn1"][0]
    assert lw.op_weight_cells(ffn1) == DIE // 2               # exactly half
    layer_gpt2 = (1024 * 3 * 1024 + 1024 * 1024
                  + 2 * 1024 * 4096) * lw.CELLS_PER_WEIGHT
    assert -(-layer_gpt2 // DIE) == 2                         # not 1!
    assert lw.dies_for_op(lw.Op("ffn1_1p3B", "static", P=1, C=2048, M=8192)) == 2
    layer_1p3b = (2048 * 3 * 2048 + 2048 * 2048
                  + 2 * 2048 * 8192) * lw.CELLS_PER_WEIGHT
    assert -(-layer_1p3b // DIE) == 6


def test_reject_is_the_default_tripwire():
    big = lw.Op("probe", "static", P=64, C=2048, M=16384)   # 4.0 dies
    assert lw.dies_for_op(big) == 4
    try:
        lw.run_op(big)                                       # default policy
        raise AssertionError("over-capacity op must not run silently")
    except ValueError as e:
        assert "O10" in str(e) and "4 dies" in str(e)


def test_rewrite_cost_closed_form():
    """temporal_rewrite bills with the K/V write primitives: every cell once
    per pass; rows serial at T_SET, columns and crossbars parallel."""
    big = lw.Op("probe", "static", P=64, C=2048, M=16384)
    r = lw.static_rewrite_cost(big)
    assert r["cells"] == 2048 * 16384 * lw.CELLS_PER_WEIGHT   # 67.1 M
    assert r["rows_serial"] == -(-r["cells"] // (256 * 256))  # 1024
    approx(r["energy_J"], r["cells"] * lw.E_WRITE_PER_CELL_J, 1e-12)
    approx(r["latency_s"], 1024 * lw.T_SET_NS * 1e-9, 1e-12)  # 8.72 ms


def test_rewrite_rejects_dynamic_ops():
    big_kv = lw.Op("kv", "dynamic", P=1, C=4096, M=4096, N=2)
    assert lw.dies_for_op(big_kv) == 4
    try:
        lw.run_op(big_kv, overcapacity="temporal_rewrite")
        raise AssertionError("dynamic over-capacity must not take the "
                             "static rewrite path")
    except NotImplementedError:
        pass


def test_spatial_requires_a_big_enough_fabric():
    """On the shipped single-die fabric the spatial policy must refuse with a
    pointer to the multi-die config, BEFORE any mapper time is spent."""
    from scripts import mlx_system as mlx
    if mlx.FABRIC.level("die").per_parent > 1:
        return                                    # running under multidie env
    big = lw.Op("probe", "static", P=64, C=2048, M=16384)
    try:
        lw.run_op(big, overcapacity="spatial_multi_die")
        raise AssertionError("must refuse on a 1-die fabric")
    except ValueError as e:
        assert "multidie" in str(e)


def test_unknown_policy_rejected():
    big = lw.Op("probe", "static", P=64, C=2048, M=16384)
    try:
        lw.run_op(big, overcapacity="stream")
        raise AssertionError("unknown policy must raise")
    except ValueError as e:
        assert "unknown overcapacity" in str(e)


# ----------------------------------------------------------- O21 (C38)
def test_attention_die_context_ceiling_closed_form():
    """The two-dies-per-layer seating's K/V ceiling: (DIE_WEIGHT_CELLS -
    8 d^2 resident cells) / (4 d cells per token) = 2,048 tokens at
    d = 1024 -- the exact number behind the '~2.5k' estimate, now computed
    and stated as the cell-capacity upper bound (array packing can only
    round it down)."""
    from scripts import llm_workload as lw
    cfg = lw.GptConfig()
    cap = lw.attention_die_context_ceiling(cfg)
    assert cap == 2048
    d = cfg.d_model
    assert cap == (lw.DIE_WEIGHT_CELLS - 8 * d * d) // (4 * d)
    # the ceiling falls with width: a 2.7B-class attention die is over
    # capacity before any K/V at all (its halves span dies instead)
    big = lw.GptConfig(d_model=2560, n_heads=32, d_ff=10240, n_layers=32, name="t")
    assert lw.attention_die_context_ceiling(big) < 0


def test_context_ceiling_guard_raises_past_2048():
    from scripts import llm_workload as lw
    cfg = lw.GptConfig()
    lw.check_context_ceiling(cfg, 512)
    lw.check_context_ceiling(cfg, 2048)
    try:
        lw.check_context_ceiling(cfg, 2049)
    except ValueError as e:
        assert "O21" in str(e) and "O14" in str(e) and "2048" in str(e)
    else:
        raise AssertionError("a context past the ceiling was accepted")


def test_die_to_die_activation_guards_the_48_die_seating():
    """The guard fires on the two-dies-per-layer path (die slots >= 2 x
    layers) and only there: S = 512 passes as ever; S = 2500 raises."""
    import os
    from scripts import fabric as fabric_mod, llm_workload as lw
    ws = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fab = fabric_mod.from_yaml(os.path.join(ws, "models", "fabric", "mlx300_multidie48.yaml"))
    cfg = lw.GptConfig()
    lw.die_to_die_activation(cfg, 512, "prefill", fabric=fab)      # fine
    try:
        lw.die_to_die_activation(cfg, 2500, "prefill", fabric=fab)
    except ValueError as e:
        assert "O21" in str(e)
    else:
        raise AssertionError("the 48-die path accepted a 2500-token context")
