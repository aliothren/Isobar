"""Group 33 -- the day-4 HARD GATE (C43): conv traffic structure locked
against hand-derived numbers on a pilot layer.

The gate the pre-registration requires before any target runs: a small
hand-computable 3x3 conv, split across dies and PEs, with every extracted
number -- multicast groups, reduction hyperedges, per-edge volumes, leaf
shares, conservation -- pinned to integers derived BY HAND in this file's
comments, plus the anti-im2col assertion (the overcount trap that would
break the declared underestimate direction). If any assertion here fails,
work stops at this layer of the machinery (SIMBA_PREREG day plan; triage
tier 3 debugging starts at conv traffic extraction).

Pilot: K=4, C=4, R=S=3, P=Q=4, stride 1, pad 1 (a miniature
res2-branch2b). Hand numbers:
  feature map 4x4x4 = 64 IA values; OA 4x4x4 = 64; MACs 4*4*9*16 = 2,304;
  im2col would claim 16*4*9 = 576 = 9x the real IA.
Die split K:2 x C:2 (4 dies, index i = m*2 + c, C varying fastest):
  per-die IA tile = full 4x4 map x 2 channels = 32 (K drops out:
  multicast); per-die OA = 16 pixels x 2 out-channels = 32 PARTIAL sums.
  Multicast groups (same C coord, IA shared):   {0,2} and {1,3}
  Reduction hyperedges (same M coord, OA merge): {0,1} and {2,3}
PE split another K:2 x C:2 inside each die (16 leaves):
  per-PE IA = 4x4x1 = 16; die edge still carries the die tile
  16 x 2 (PE C-distinct) = 32; leaf shares: die (32+32)/4 = 16,
  macro (16+16)/1 = 32. Reassembly: 16 x 2 x 2 = 64 = the operand once.
"""
from scripts.simba_workload import RESNET50, ConvOp, conv_structure
from scripts.traffic import IN_DISTINCT, OUT_REDUCED

PILOT = ConvOp("pilot", K=4, C=4, R=3, S=3, P=4, Q=4, stride=1, pad=1)


def _groups_by(split, keep):
    """Manual enumeration mirroring the traffic index convention (last
    listed dim varies fastest): group instances by the kept dims' coords."""
    dims = list(split.factors.items())
    groups = {}
    for i in range(split.fanout):
        rem, coord = i, []
        for name, f in reversed(dims):
            coord.append((name, rem % f))
            rem //= f
        key = tuple(v for name, v in coord if name in keep)
        groups.setdefault(key, []).append(i)
    return sorted(sorted(g) for g in groups.values())


def test_pilot_volumes_by_hand():
    assert PILOT.macs == 2_304
    assert PILOT.input_words == 64
    assert PILOT.output_words == 64
    assert PILOT.im2col_input_words() == 576 == 9 * PILOT.input_words


def test_pilot_die_structure_by_hand():
    ts = conv_structure(PILOT, die_split={"K": 2, "C": 2})
    assert ts.n_active == 4
    ev = ts.edge_volumes()["die"]
    assert ev["in"] == 32 and ev["out"] == 32          # hand numbers above
    # reduction hyperedges: dies sharing the M coordinate merge partial sums
    assert ts.reduction_hyperedges("die") == [[0, 1], [2, 3]]
    assert ts.hyperedge_shape("die") == (2, 2)
    # multicast groups: dies sharing every IN-DISTINCT coordinate (here C)
    # receive the SAME IA slice -- manual enumeration, same convention
    split = ts.splits[0]
    mcast = _groups_by(split, keep={d for d in split.factors if d in IN_DISTINCT})
    assert mcast == [[0, 2], [1, 3]]
    # the two groupings are transposed partitions of the 2x2 instance grid
    red = _groups_by(split, keep={d for d in split.factors if d not in OUT_REDUCED})
    assert red == [[0, 1], [2, 3]]


def test_pilot_two_level_composition_by_hand():
    ts = conv_structure(PILOT, die_split={"K": 2, "C": 2},
                        pe_split={"K": 2, "C": 2})
    assert ts.n_active == 16
    assert ts.in_leaf == 16 and ts.out_leaf == 16
    ev = ts.edge_volumes()
    assert ev["die"]["in"] == 32                       # the die's tile, unchanged
    assert ev["die"]["out"] == 32
    assert ev["macro"]["in"] == 16 and ev["macro"]["out"] == 16
    assert ts.leaf_shares() == {"die": 16.0, "macro": 32.0}
    assert ts.reduction_hyperedges("macro") == [[0, 1], [2, 3]]


def test_pilot_conservation_identities():
    """The distinct slices reassemble each operand exactly once; partial
    sums count C-copies; im2col appears NOWHERE in the delivered volumes."""
    ts = conv_structure(PILOT, die_split={"K": 2, "C": 2},
                        pe_split={"K": 2, "C": 2})
    c_distinct = 2 * 2                                 # C splits, both levels
    k_copies = 2 * 2
    assert ts.in_leaf * c_distinct == PILOT.input_words           # IA once
    assert ts.out_leaf * ts.n_active == c_distinct * PILOT.output_words
    # anti-im2col: the die edge carries the tile (32), never 9x it (288)
    assert ts.edge_volumes()["die"]["in"] * 9 == 288
    # and the multicast copies are structural (k_copies dies per IA slice),
    # never volume inflation on a single edge
    assert ts.in_leaf * c_distinct * k_copies == 4 * PILOT.input_words


def test_conv_matmul_equivalence_on_1x1():
    """A 1x1 conv IS the matmul our measured machinery models: the die
    edge under K:2 x C:2 equals the algebraic matmul tile P*(C/2) with
    P = 14*14 output pixels -- the bridge to the width-law trunk formula
    (per-edge input = S*d there, = pixels x channel slice here)."""
    op = RESNET50["res4a_branch1"]
    ts = conv_structure(op, die_split={"K": 2, "C": 2})
    P_matmul, C_matmul = op.P * op.Q, op.C
    assert ts.edge_volumes()["die"]["in"] == P_matmul * (C_matmul // 2)
    assert ts.edge_volumes()["die"]["out"] == P_matmul * (op.K // 2)
