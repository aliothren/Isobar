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
