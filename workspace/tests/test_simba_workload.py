"""Group 32 -- Simba reproduction workload: conv volumes and closed-form
traffic structure (C42, worklist step 1, day 3).

Pins the touched-extent volume semantics (the anti-im2col rule), the
ResNet-50 target-layer shapes, and the closed-form TrafficStructure on
hand-computable splits. The day-4 gate (group 33) locks the full pilot
end to end; this group is the shape/volume layer it builds on.
"""
from _util import approx

from scripts.simba_workload import (RESNET50, RES4A_BRANCH1_MACS, ConvOp,
                                    compute_seconds, conv_structure,
                                    simba_fabric)


# ------------------------------------------------------------- shape pins
def test_target_layer_shapes():
    r4 = RESNET50["res4a_branch1"]            # 1x1 s2 projection, 28x28 -> 14x14
    assert r4.macs == 102_760_448 == RES4A_BRANCH1_MACS
    assert r4.input_words == 14 * 14 * 512 == 100_352
    assert r4.output_words == 14 * 14 * 1024 == 200_704
    r2 = RESNET50["res2[a-c]_branch2b"]       # 3x3 s1 pad1 at 56x56
    r5 = RESNET50["res5[a-c]_branch2b"]       # 3x3 s1 pad1 at 7x7
    assert r2.macs == r5.macs == 115_605_504  # same MACs, opposite reuse ends
    assert r2.input_words == 56 * 56 * 64     # touched == the real feature map
    assert r5.input_words == 7 * 7 * 512
    r3 = RESNET50["res3a_branch1"]
    assert r3.macs == 28 * 28 * 256 * 512


def test_one_by_one_layers_have_no_im2col_gap():
    """R=S=1: touched and im2col volumes coincide exactly -- the trap only
    exists for 3x3 layers, where im2col would overcount ~9x."""
    for op in RESNET50.values():
        if op.R == 1 and op.S == 1:
            assert op.input_words == op.im2col_input_words(), op.name
    r2 = RESNET50["res2[a-c]_branch2b"]
    assert r2.im2col_input_words() == 9 * 56 * 56 * 64
    assert r2.im2col_input_words() / r2.input_words == 9.0


def test_touched_extent_convention():
    """The three regimes of the touched formula on synthetic ops."""
    # stride < R: contiguous span with halo (3x3 s1, no pad)
    assert ConvOp("t", K=1, C=1, R=3, S=3, P=4, Q=4).input_words == 6 * 6
    # stride > R: disjoint strips (1x1 s2)
    assert ConvOp("t", K=1, C=1, R=1, S=1, P=4, Q=4, stride=2).input_words == 4 * 4
    # pad removes phantom rows (3x3 s1 pad1 = the real map)
    assert ConvOp("t", K=1, C=1, R=3, S=3, P=4, Q=4, pad=1).input_words == 4 * 4
    # stride>1 with pad>0 is off-by-one against the real map (C42 review):
    # it must refuse, same discipline as the halo deferral
    try:
        ConvOp("t", K=1, C=1, R=3, S=3, P=14, Q=14, stride=2, pad=1).input_words
    except NotImplementedError:
        pass
    else:
        raise AssertionError("stride>1 + pad>0 did not refuse")


# ------------------------------------------------- closed-form structure
def test_die_level_kc_split_hand_example():
    """res4a_branch1 over 4 chiplets as K:2 x C:2 -- every number by hand.
    Per die: IA = 14*14*(512/2) = 50,176 (K drops out: multicast); OA =
    14*14*(1024/2) = 100,352 partial sums (C split -> reduction)."""
    op = RESNET50["res4a_branch1"]
    ts = conv_structure(op, die_split={"K": 2, "C": 2})
    assert ts.n_active == 4
    ev = ts.edge_volumes()["die"]
    assert ev["in"] == 50_176 and ev["out"] == 100_352
    # reduction hyperedges: C varies fastest (last listed), so instances
    # {0,1} share M=0 and {2,3} share M=1 -- two merges of two
    assert ts.reduction_hyperedges("die") == [[0, 1], [2, 3]]
    assert ts.hyperedge_shape("die") == (2, 2)
    # reassembly: distinct input slices cover the operand exactly once
    assert ts.in_leaf * 2 == op.input_words           # C-split distinct
    assert ts.out_leaf * 4 == 2 * op.output_words     # 2 psums per output


def test_two_level_split_composes():
    """Die K:2xC:2 with PE K:4xC:4 (Simba's own on-chip convention,
    JSSC §III-B): the die edge must still carry the die's tile."""
    op = RESNET50["res4a_branch1"]
    ts = conv_structure(op, die_split={"K": 2, "C": 2},
                        pe_split={"K": 4, "C": 4})
    assert ts.n_active == 4 * 16
    assert ts.in_leaf == 14 * 14 * (512 // 8)         # per-PE tile
    ev = ts.edge_volumes()
    assert ev["die"]["in"] == ts.in_leaf * 4 == 50_176    # x C-distinct below
    assert ev["macro"]["in"] == ts.in_leaf
    # full reassembly across both levels (C-splits multiply, K drops out)
    assert ts.in_leaf * 2 * 4 == op.input_words


def test_p_split_exact_only_without_halo():
    op1 = RESNET50["res4a_branch1"]                   # R=1: P-split exact
    ts = conv_structure(op1, die_split={"K": 2, "P": 2})
    assert ts.in_leaf == 7 * 14 * 512
    assert ts.in_leaf * 2 == op1.input_words          # P-distinct, K drops
    op3 = RESNET50["res2[a-c]_branch2b"]              # R=3: halo -> deferred
    try:
        conv_structure(op3, die_split={"P": 2})
    except NotImplementedError:
        pass
    else:
        raise AssertionError("halo-carrying P-split did not defer")


def test_split_guards():
    op = RESNET50["res4a_branch1"]
    for bad in ({"K": 3}, {"C": 100_000}, {"Z": 2}):
        try:
            conv_structure(op, die_split=bad)
        except (ValueError, KeyError):
            pass
        else:
            raise AssertionError(f"{bad} accepted")
    try:
        conv_structure(op, die_split={"K": 64})       # > 36 dies
    except ValueError:
        pass
    else:
        raise AssertionError("over-capacity split accepted")


# ------------------------------------------------------------ compute time
def test_compute_seconds_closed_form():
    """res4a_branch1: 102,760,448 MACs / 1,024 per chiplet-cycle =
    100,352 cycles on one chiplet -- 14% BELOW JSSC Fig 18's measured
    114,688 compute cycles (ratio 8/7), the declared optimistic direction
    (utilization 1.0 vs their measured 63-87%); recorded, not patched."""
    op = RESNET50["res4a_branch1"]
    fab = simba_fabric()
    one = compute_seconds(op, 1, fabric=fab)
    approx(one / fab.device.cycle_seconds, 100_352.0, 1e-12)
    approx(compute_seconds(op, 4, fabric=fab) / fab.device.cycle_seconds,
           25_088.0, 1e-12)
    approx(compute_seconds(op, 32, fabric=fab) / fab.device.cycle_seconds,
           3_136.0, 1e-12)
    approx(one, 100_352 / 1.03e9, 1e-9)               # 97.4 us at 1.03 GHz
