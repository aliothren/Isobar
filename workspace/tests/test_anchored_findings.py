"""Group 17 -- the ANCHORED findings, pinned (upgrade protocol).

Two bases coexist. The v1 fixture is the EXCLUSIVE-DIE reference (each op
mapped with the whole die; weight replication over P fills idle arrays) --
its tests are kept as the historical basis the blind-test coherence ran on.
The v2 fixture is the O12 CO-RESIDENCY basis (each op pinned to its 48-die
seating share; no replication) -- the published 355M numbers since O12.

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
FIX2 = json.load(open(os.path.join(HERE, "fixtures", "stack_per_op_v2.json")))
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


def stack2(phase, label, gbps, attention_on_chip):
    per = FIX2["phases"][phase]["per_op"][label]
    wc = gbps * WC_PER_GBPS
    tot = base = 0.0
    for o in per:
        if not attention_on_chip and o["name"] not in STATIC:
            continue
        wr = o["write_s"] if attention_on_chip else 0.0
        tot += wr + max(o["compute_s"], o["serial_s"] * REF / wc)
        base += wr + o["compute_s"]
    return tot / base


def test_share_basis_compute_is_uniform_5192us():
    """O12: without weight replication every op's compute lands at exactly
    X7 x P512 = 3584 cycles = 5.192 ms (prefill); decode is untouched
    (P=1 ops never replicated)."""
    for o in FIX2["phases"]["prefill"]["per_op"]["mesh, glb centre"]:
        approx(o["compute_s"], 5.192e-3, 2e-3)
    for o in FIX2["phases"]["decode"]["per_op"]["mesh, glb centre"]:
        approx(o["compute_s"], 10.14e-6, 2e-2)


def test_share_basis_anchored_readout():
    """The published (post-O12) anchored table: at the Simba anchor the
    spread is 1.00-3.11x with the hub lever at 1.50x; at ESP everything
    collapses to <=1.10x -- the v1 'mid-anchor condition divergence' does
    NOT survive the honest bases and is retired."""
    approx(stack2("prefill", "star (private links)", ANCH["simba"], True),
           1.00, 5e-3)
    c = stack2("prefill", "mesh, glb centre", ANCH["simba"], True)
    k = stack2("prefill", "mesh, glb corner", ANCH["simba"], True)
    approx(c, 1.31, 1e-2)
    approx(k / c, 1.50, 1e-2)
    approx(stack2("prefill", "bus (shared medium)", ANCH["simba"], True),
           3.11, 5e-3)
    for phase, on_chip in (("prefill", True), ("decode", False)):
        for label in FIX2["phases"][phase]["per_op"]:
            assert stack2(phase, label, ANCH["esp"], on_chip) <= 1.105


def test_share_vs_fulldie_direction():
    """The register's predicted direction, pinned: co-residency slows
    compute, so every contention multiplier SHRINKS relative to the
    exclusive-die basis (never grows), at every anchor."""
    for label in FIX2["phases"]["prefill"]["per_op"]:
        for g in ANCH.values():
            assert stack2("prefill", label, g, True) <= \
                stack("prefill", label, g, True) + 1e-9


# -------------------------------------------------- O7: the overlap bracket
def stack2_sum(phase, label, gbps, attention_on_chip):
    """The zero-overlap end: write + compute + serialization + prop per op.
    With stack2 (perfect overlap) it brackets the truth -- O7."""
    per = FIX2["phases"][phase]["per_op"][label]
    wc = gbps * WC_PER_GBPS
    tot = base = 0.0
    for o in per:
        if not attention_on_chip and o["name"] not in STATIC:
            continue
        wr = o["write_s"] if attention_on_chip else 0.0
        tot += wr + o["compute_s"] + o["serial_s"] * REF / wc
        base += wr + o["compute_s"]
    return tot / base


def test_bracket_identity_and_order():
    """sum >= max always, and (sum - max) == the overlapped time
    sum(min(compute, serial)) -- the bracket width IS the value of
    double buffering. Checked per scheme at every anchor."""
    for phase, on_chip in (("prefill", True), ("decode", False)):
        for label, per in FIX2["phases"][phase]["per_op"].items():
            for g in ANCH.values():
                lo = stack2(phase, label, g, on_chip)
                hi = stack2_sum(phase, label, g, on_chip)
                assert hi >= lo - 1e-12, (label, g)
                base = sum((o["write_s"] if on_chip else 0.0) + o["compute_s"]
                           for o in per
                           if on_chip or o["name"] in STATIC)
                overlap = sum(min(o["compute_s"],
                                  o["serial_s"] * REF / (g * WC_PER_GBPS))
                              for o in per
                              if on_chip or o["name"] in STATIC)
                approx(hi - lo, overlap / base, 1e-6)


def test_bracket_at_the_anchors():
    """The published bracket ends (prefill, attention on chip):
    Simba star [1.00, 1.38] / corner [1.97, 2.89] / bus [3.11, 4.02];
    ESP bus upper 1.83; FlooNoC bus upper 1.33 and star upper 1.04.
    The zero-overlap end does NOT collapse at the high anchors: 'the
    network is invisible there' requires the double-buffered overlap the
    lower end assumes -- that caveat is now part of the published claim."""
    A = lambda label, g: stack2_sum("prefill", label, g, True)
    approx(A("star (private links)", ANCH["simba"]), 1.3781, 1e-3)
    approx(A("mesh, glb corner", ANCH["simba"]), 2.8903, 1e-3)
    approx(A("bus (shared medium)", ANCH["simba"]), 4.0245, 1e-3)
    approx(A("bus (shared medium)", ANCH["esp"]), 1.8270, 1e-3)
    approx(A("bus (shared medium)", ANCH["floonoc"]), 1.3283, 1e-3)
    approx(A("star (private links)", ANCH["floonoc"]), 1.0410, 1e-3)


def test_scheme_ordering_is_bracket_invariant():
    """Both ends rank the schemes identically at every anchor (adding the
    serialization term preserves the order the max already induced) -- so
    every placement RANKING published from the lower end survives O7."""
    order = ["star (private links)", "mesh, glb centre", "h-tree (k=4)",
             "mesh, glb corner", "bus (shared medium)"]
    for g in ANCH.values():
        lows = [stack2("prefill", l, g, True) for l in order]
        highs = [stack2_sum("prefill", l, g, True) for l in order]
        assert lows == sorted(lows), g
        assert highs == sorted(highs), g


# -------------------------------------------------- O22/O23: the v3 accounting
FIX3 = json.load(open(os.path.join(HERE, "fixtures", "stack_per_op_v3.json")))


def stack3(phase, label, gbps, attention_on_chip, overlap="max"):
    per = FIX3["phases"][phase]["per_op"][label]
    wc = gbps * WC_PER_GBPS
    tot = base = 0.0
    for o in per:
        if not attention_on_chip and o["name"] not in STATIC:
            continue
        wr = o["write_s"] if attention_on_chip else 0.0
        ser = o["serial_s"] * REF / wc
        tot += wr + (max(o["compute_s"], ser) if overlap == "max"
                     else o["compute_s"] + ser)
        base += wr + o["compute_s"]
    return tot / base


def test_v3_anchored_readout():
    """The published (post-O22/O23) anchored table, prefill on chip: Simba
    spread 1.03-5.31x with the hub lever 1.56x; at ESP private links and
    the centred grid collapse (1.00) while the corner grid / tree / bus do
    not (1.16 / 1.06 / 1.60); at FlooNoC everything collapses."""
    A = lambda label, g: stack3("prefill", label, g, True)
    approx(A("star (private links)", ANCH["simba"]), 1.03, 1e-2)
    c, k = A("mesh, glb centre", ANCH["simba"]), A("mesh, glb corner", ANCH["simba"])
    approx(c, 1.85, 1e-2)
    approx(k / c, 1.56, 1e-2)
    approx(A("bus (shared medium)", ANCH["simba"]), 5.31, 5e-3)
    approx(A("star (private links)", ANCH["esp"]), 1.00, 1e-3)
    approx(A("mesh, glb centre", ANCH["esp"]), 1.00, 1e-3)
    approx(A("mesh, glb corner", ANCH["esp"]), 1.16, 1e-2)
    approx(A("bus (shared medium)", ANCH["esp"]), 1.60, 1e-2)
    for label in FIX3["phases"]["prefill"]["per_op"]:
        assert A(label, ANCH["floonoc"]) <= 1.005, label


def test_v3_direction_understated_before():
    """The register's net direction, settled: the physical wire accounting
    (separate per-direction wires AND 16-bit partial sums) never lowers a
    multiplier relative to the v2 accounting -- the width term dominates."""
    for phase, on_chip in (("prefill", True), ("decode", False)):
        for label in FIX3["phases"][phase]["per_op"]:
            for g in ANCH.values():
                assert stack3(phase, label, g, on_chip) >= \
                    stack2(phase, label, g, on_chip) - 1e-9, (phase, label, g)


def test_v3_scheme_ordering_unchanged():
    """Both bracket ends still rank the schemes identically at every anchor
    under the new accounting."""
    order = ["star (private links)", "mesh, glb centre", "h-tree (k=4)",
             "mesh, glb corner", "bus (shared medium)"]
    for g in ANCH.values():
        for ov in ("max", "sum"):
            vals = [stack3("prefill", l, g, True, ov) for l in order]
            assert vals == sorted(vals), (g, ov)
