"""Group 17 -- the ANCHORED findings, pinned (upgrade protocol).

The anchored sweep promoted the contention numbers from placeholder
sensitivities to findings stated at published link bandwidths (ANCHORS.md).
Per our own upgrade rule that promotion is only real once the orderings are
pinned as tests against a frozen fixture -- same treatment the on-die
contention anchors got (group 14). Fixture: stack_per_op_v1.json (per-op
compute/write/serialization from the real mapper runs; serialization scales
exactly as 1/bandwidth).
"""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = json.load(open(os.path.join(HERE, "fixtures", "stack_per_op_v1.json")))
REF = FIX["ref_words_per_cycle"]
CYC = 1.4485714285714284e-06
WC_PER_GBPS = 1e9 * CYC                        # = 1448.57 words/cycle per GB/s
ANCH = {"simba": 8.75, "esp": 32.0, "floonoc": 80.6}     # GB/s, ANCHORS.md
STATIC = {"qkv_proj", "out_proj", "ffn1", "ffn2"}
N = 24


def stack(phase, label, gbps, attention_on_chip):
    per = FIX["phases"][phase]["per_op"][label]
    wc = gbps * WC_PER_GBPS
    tot = base = 0.0
    for o in per:
        if not attention_on_chip and o["name"] not in STATIC:
            continue
        wr = o["write_s"] if attention_on_chip else 0.0
        tot += wr + max(o["compute_s"], o["serial_s"] * REF / wc)
        base += wr + o["compute_s"]
    return (tot / base)


def test_low_anchor_spread_prefill():
    """At the silicon-measured Simba on-die bandwidth, prefill contention is
    first-order: 1.42x (private links) to 8.60x (shared bus)."""
    approx(stack("prefill", "star (private links)", ANCH["simba"], True),
           1.42, 5e-3)
    approx(stack("prefill", "bus (shared medium)", ANCH["simba"], True),
           8.60, 5e-3)


def test_hub_position_lever_at_low_anchor():
    """Buffer centre -> corner alone is worth 1.65x at the Simba anchor."""
    c = stack("prefill", "mesh, glb centre", ANCH["simba"], True)
    k = stack("prefill", "mesh, glb corner", ANCH["simba"], True)
    approx(c, 3.32, 5e-3)
    approx(k / c, 1.65, 1e-2)


def test_high_anchor_collapse():
    """At the FlooNoC anchor the effect nearly vanishes: every scheme <=1.32x
    and everything except the bus <=1.07x, in BOTH conditions."""
    for phase, on_chip in (("prefill", True), ("decode", False)):
        for label in FIX["phases"][phase]["per_op"]:
            m = stack(phase, label, ANCH["floonoc"], on_chip)
            assert m <= 1.325, (phase, label, m)
            if "bus" not in label:
                assert m <= 1.075, (phase, label, m)


def test_mid_anchor_condition_divergence():
    """At the ESP anchor the two conditions disagree: prefill still separates
    the hub positions (1.28 vs 1.70) while offloaded decode has collapsed to
    ~1.06 for both -- 'is the NoC fast enough' has no single-number answer."""
    pc = stack("prefill", "mesh, glb centre", ANCH["esp"], True)
    pk = stack("prefill", "mesh, glb corner", ANCH["esp"], True)
    dc = stack("decode", "mesh, glb centre", ANCH["esp"], False)
    dk = stack("decode", "mesh, glb corner", ANCH["esp"], False)
    assert pk / pc > 1.30                       # prefill still separates
    assert abs(dk - dc) / dc < 0.01             # decode has collapsed
    approx(pc, 1.28, 1e-2); approx(pk, 1.70, 1e-2)
    approx(dc, 1.06, 1e-2)


def test_anchors_land_consistently_with_published_thresholds():
    """Blind-test coherence: the previously PUBLISHED mesh-centre thresholds
    (stack doubles below 16,384 w/c; moves 1% below 65,536 w/c) must place
    the three anchors exactly where the sweep found them: Simba below the
    doubling line (>=2x), ESP between the lines (1.01..2x), FlooNoC above
    the 1% line (<1.01x)."""
    def wc(g):
        return g * WC_PER_GBPS
    assert wc(ANCH["simba"]) < 16384 < wc(ANCH["esp"]) < 65536 < wc(ANCH["floonoc"])
    m = {k: stack("prefill", "mesh, glb centre", g, True)
         for k, g in ANCH.items()}
    assert m["simba"] >= 2.0
    assert 1.01 <= m["esp"] < 2.0
    assert m["floonoc"] < 1.01


def test_htree_equals_bus_in_offloaded_decode_is_real():
    """The 3.76x tie is physics, not a transcription merge: decode's small
    static flows all cross the tree's ROOT edge, which then carries exactly
    the whole level's traffic -- the same resource the bus is. Pinned per-op:
    identical serializations for every static op."""
    ht = FIX["phases"]["decode"]["per_op"]["h-tree (k=4)"]
    bu = FIX["phases"]["decode"]["per_op"]["bus (shared medium)"]
    for a, b in zip(ht, bu):
        assert a["name"] == b["name"]
        if a["name"] in STATIC:
            approx(a["serial_s"], b["serial_s"], 1e-12)
    # and they differ in prefill, where the tree's parallel branches matter
    ht_p = FIX["phases"]["prefill"]["per_op"]["h-tree (k=4)"]
    bu_p = FIX["phases"]["prefill"]["per_op"]["bus (shared medium)"]
    assert any(abs(a["serial_s"] - b["serial_s"]) > 1e-9
               for a, b in zip(ht_p, bu_p))
