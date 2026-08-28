"""Group 11 -- TrafficExtraction (workstream B, units fixed in C25): real
structure vs the uniform placeholder, pinned by hand-derived numbers on the
FROZEN ffn1 mapping.

The frozen mapping's spatial factors are known (macro C=4,P=2; core M=4;
crossbar M=8), so every expected volume below is computed by hand from the
tensor algebra, not by running the code under test. VALUE units (C25):

    row-driver reads   = 117,440,512 = 256 leaves x 65,536 values x 7 input bit slices
    ADC reads          = 134,217,728 = 256 leaves x 32,768 values x 8 output bits x 2 cell columns
    in_leaf  = 65,536  (256 input rows x 256 token rows per crossbar)
    out_leaf = 32,768  (128 output columns x 256 token rows per crossbar)
    input edges  (down): all three levels carry the UNIQUE slice 65,536
                         (everything below the die split is M = multicast)
    output edges (up):   32,768 / x8 / x32 (distinct below, merge at glb)
    union of the leaves: inputs 65,536 x 8 = 524,288 = P x C,
                         outputs 32,768 x 64 = 2,097,152 = P x M

The retired convention (v1-v4) took "Total scalar accesses" as 8-bit words:
917,504 = 65,536 x 7 x 2 (reads + fills) and 1,572,864 = 32,768 x 8 x 2 x 3
(reads + fills + updates) -- 14x and 48x the values.
"""
import re

from _util import fixture

from scripts import fabric, traffic

IN_LEAF = 65_536
OUT_LEAF = 32_768


def _ts():
    return traffic.extract(
        fabric=fabric.default(),
        mapping_text=open(fixture("ffn1_prefill_map.txt")).read(),
        stats_text=open(fixture("ffn1_prefill_stats.txt")).read())


def test_parsed_factors_match_known_mapping():
    ts = _ts()
    got = {s.level: dict(s.factors) for s in ts.splits}
    assert got == {"macro": {"C": 4, "P": 2}, "core": {"M": 4},
                   "crossbar": {"M": 8}}, got


def test_leaf_volumes_are_values():
    ts = _ts()
    assert ts.n_active == 256
    assert ts.in_leaf == IN_LEAF
    assert ts.out_leaf == OUT_LEAF
    assert (ts.x_slices, ts.z_bits, ts.y_columns) == (7, 8, 2)


def test_unit_decomposition_of_the_counters():
    """Where the retired 14x / 48x came from, pinned so it cannot creep back:
    reads = values x unit factors; the old totals also added fills/updates."""
    ts = _ts()
    assert ts.in_reads_total == 117_440_512 == ts.n_active * IN_LEAF * 7
    assert ts.out_reads_total == 134_217_728 == ts.n_active * OUT_LEAF * 8 * 2
    stats = open(fixture("ffn1_prefill_stats.txt")).read()
    old_in = int(re.search(r"=== row_drivers ===\s*\n\s*Total scalar accesses\s*:\s*(\d+)", stats).group(1))
    old_out = int(re.search(r"=== adc ===\s*\n\s*Total scalar accesses\s*:\s*(\d+)", stats).group(1))
    assert old_in == 234_881_024 == ts.n_active * IN_LEAF * 7 * 2
    assert old_out == 402_653_184 == ts.n_active * OUT_LEAF * 8 * 2 * 3


def test_leaves_reassemble_the_operands_once():
    ts = _ts()
    assert ts.tensor_in == 512 * 1024 and ts.tensor_out == 512 * 4096
    assert IN_LEAF * 8 == ts.tensor_in          # macro C=4,P=2 distinct
    assert OUT_LEAF * 2 * 4 * 8 == ts.tensor_out  # P=2 distinct, M=4, M=8


def test_edge_volumes_hand_derived():
    ev = _ts().edge_volumes()
    assert ev["crossbar"] == {"in": IN_LEAF, "out": OUT_LEAF}
    assert ev["core"] == {"in": IN_LEAF, "out": OUT_LEAF * 8}
    assert ev["macro"] == {"in": IN_LEAF, "out": OUT_LEAF * 32}


def test_multicast_trunk_correction_is_32x():
    """the uniform model charged the glb->macro input side subtree-sum
    (in_leaf x 32); the real slice crosses once."""
    ev = _ts().edge_volumes()
    uniform_macro_in = IN_LEAF * 32
    assert uniform_macro_in / ev["macro"]["in"] == 32


def test_output_side_equals_uniform_for_this_mapping():
    """no reduction below the die hub in this mapping -> the subtree-sum was
    accidentally right for outputs; structured must agree, not overcorrect."""
    ev = _ts().edge_volumes()
    assert ev["macro"]["out"] == OUT_LEAF * 32
    assert ev["core"]["out"] == OUT_LEAF * 8


def test_leaf_shares_split_multicast():
    """one leaf's attributable share of a shared upper edge = edge / leaves
    served; outputs are unshared so they attribute in full."""
    sh = _ts().leaf_shares()
    assert sh["crossbar"] == IN_LEAF + OUT_LEAF
    assert sh["core"] == (IN_LEAF + OUT_LEAF * 8) / 8
    assert sh["macro"] == (IN_LEAF + OUT_LEAF * 32) / 32


def test_guards_raise_on_mismatch():
    """a tampered read count (not divisible over leaves x units) and a
    count that no longer reassembles the operand both raise."""
    good_map = open(fixture("ffn1_prefill_map.txt")).read()
    stats = open(fixture("ffn1_prefill_stats.txt")).read()
    body = re.search(r"=== row_drivers ===.*?(?=\n=== )", stats, re.S).group(0)
    tampered = stats.replace(body, body.replace("Scalar reads (per-instance)              : 458752",
                                                "Scalar reads (per-instance)              : 458753", 1), 1)
    assert tampered != stats
    for bad in (tampered,
                stats.replace(body, body.replace("Scalar reads (per-instance)              : 458752",
                                                 "Scalar reads (per-instance)              : 917504", 1), 1)):
        try:
            traffic.extract(fabric=fabric.default(), mapping_text=good_map, stats_text=bad)
        except ValueError:
            continue
        raise AssertionError("bad counter accepted silently")
