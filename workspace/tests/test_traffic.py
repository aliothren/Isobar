"""Group 11 -- TrafficExtraction (workstream B): real structure vs the uniform
placeholder, pinned by hand-derived numbers on the FROZEN ffn1 mapping.

The frozen mapping's spatial factors are known (macro C=4,P=2; core M=4;
crossbar M=8), so every expected volume below is computed by hand from the
tensor algebra, not by running the code under test:

    in_leaf  = row_drivers / 256 = 234,881,024 / 256 =   917,504
    out_leaf = adc         / 256 = 402,653,184 / 256 = 1,572,864
    input edges  (down): all three levels carry the UNIQUE slice 917,504
                         (everything below the die split is M = multicast)
    output edges (up):   1,572,864 / x8 / x32 (distinct below, merge at glb)
"""
from _util import fixture

from scripts import fabric, traffic

IN_LEAF = 917_504
OUT_LEAF = 1_572_864


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


def test_leaf_volumes():
    ts = _ts()
    assert ts.n_active == 256
    assert ts.in_leaf == IN_LEAF
    assert ts.out_leaf == OUT_LEAF


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


def test_leaf_conservation_ties_to_stats():
    ts = _ts()
    assert ts.in_leaf * ts.n_active == 234_881_024   # row_drivers total
    assert ts.out_leaf * ts.n_active == 402_653_184  # adc total


def test_leaf_shares_split_multicast():
    """one leaf's attributable share of a shared upper edge = edge / leaves
    served; outputs are unshared so they attribute in full."""
    sh = _ts().leaf_shares()
    assert sh["crossbar"] == IN_LEAF + OUT_LEAF
    assert sh["core"] == (IN_LEAF + OUT_LEAF * 8) / 8
    assert sh["macro"] == (IN_LEAF + OUT_LEAF * 32) / 32


def test_divisibility_guard_raises_on_mismatch():
    good_map = open(fixture("ffn1_prefill_map.txt")).read()
    stats = open(fixture("ffn1_prefill_stats.txt")).read()
    tampered = stats.replace("234881024", "234881025", 1)
    try:
        traffic.extract(fabric=fabric.default(), mapping_text=good_map,
                        stats_text=tampered)
    except ValueError:
        return
    raise AssertionError("indivisible counter accepted silently")
