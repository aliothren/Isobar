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
from scripts import anchors as an
CYC = an.CYCLE_S
WC_PER_GBPS = an.WC_PER_GBPS                   # = 1448.57 words/cycle per GB/s
ANCH = {"simba": an.by_key("simba_ondie").gbps, "esp": an.by_key("esp").gbps,
        "floonoc": an.by_key("floonoc").gbps}     # GB/s, the registry (scripts/anchors.py)
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


# -------------------------------------------------- C25: value units (v5)
FIX5 = json.load(open(os.path.join(HERE, "fixtures", "stack_per_op_v5.json")))


def stack5(phase, label, gbps, attention_on_chip, overlap="max"):
    per = FIX5["phases"][phase]["per_op"][label]
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


def test_v5_compute_and_write_unchanged():
    """The unit fix touches wires only: every compute / write / digital-unit
    row of v5 equals v4 bit for bit; every serialization moved."""
    v4 = json.load(open(os.path.join(HERE, "fixtures", "stack_per_op_v4.json")))
    moved = 0
    for phase in ("prefill", "decode"):
        for label, per in FIX5["phases"][phase]["per_op"].items():
            for a, b in zip(per, v4["phases"][phase]["per_op"][label]):
                assert a["name"] == b["name"]
                assert a["compute_s"] == b["compute_s"] and a["write_s"] == b["write_s"]
                moved += a["serial_s"] != b["serial_s"]
        assert FIX5["phases"][phase]["stall_free_s"] == v4["phases"][phase]["stall_free_s"]
    assert moved == 60                      # 6 matmuls x 5 schemes x 2 phases


def test_v5_anchored_readout():
    """The published (post-C25) anchored table: with the wires carrying
    values instead of Timeloop's bit-slice / bit / access counters (14x
    inputs, 48x outputs), the busiest wire hides behind compute at every
    anchor and scheme (perfect-overlap end 1.00x, both conditions); the
    zero-overlap end at the Simba anchor reads star 1.01x, centred grid
    1.04x, corner grid 1.07x, tree 1.05x, bus 1.15x (prefill) and the bus
    1.17x in offloaded decode; at ESP the bus's zero-overlap end is 1.04x,
    at FlooNoC 1.02x."""
    for phase, on_chip in (("prefill", True), ("decode", False)):
        for label in FIX5["phases"][phase]["per_op"]:
            for g in ANCH.values():
                approx(stack5(phase, label, g, on_chip), 1.00, 1e-3)
    Z = lambda label, g, ph="prefill", oc=True: stack5(ph, label, g, oc, "sum")
    approx(Z("star (private links)", ANCH["simba"]), 1.01, 1e-2)
    approx(Z("mesh, glb centre", ANCH["simba"]), 1.04, 1e-2)
    approx(Z("mesh, glb corner", ANCH["simba"]), 1.07, 1e-2)
    approx(Z("h-tree (k=4)", ANCH["simba"]), 1.05, 1e-2)
    approx(Z("bus (shared medium)", ANCH["simba"]), 1.15, 1e-2)
    approx(Z("bus (shared medium)", ANCH["simba"], "decode", False), 1.17, 1e-2)
    approx(Z("bus (shared medium)", ANCH["esp"]), 1.04, 1e-2)
    approx(Z("bus (shared medium)", ANCH["floonoc"]), 1.02, 1e-2)


def test_v5_direction_and_thresholds():
    """Direction, pinned: value units never raise a multiplier relative to
    the v3 counter units (the inflation was 14x/48x, one-sided). The
    reference-input thresholds: no scheme doubles the stack at any
    bandwidth of the scripts' sweep (2^9..2^23 w/c) except the bus (512 w/c); the 1%
    thresholds sit at 512 (centred grid) .. 2,048 w/c (bus), and private
    links never reach 1%."""
    for phase, on_chip in (("prefill", True), ("decode", False)):
        for label in FIX5["phases"][phase]["per_op"]:
            for g in ANCH.values():
                for ov in ("max", "sum"):
                    assert stack5(phase, label, g, on_chip, ov) <= \
                        stack3(phase, label, g, on_chip, ov) + 1e-9, (phase, label, g, ov)

    def at_wc(label, wc, ov="max"):
        return stack5("prefill", label, wc / WC_PER_GBPS, True, ov)
    def knee(label, level):
        hit = [wc for wc in (2 ** k for k in range(9, 24)) if at_wc(label, wc) >= level]   # the scripts' sweep 2^9..2^23
        return max(hit) if hit else None
    assert knee("star (private links)", 1.01) is None
    assert knee("mesh, glb centre", 1.01) == 512
    assert knee("mesh, glb corner", 1.01) == 1024
    assert knee("h-tree (k=4)", 1.01) == 1024
    assert knee("bus (shared medium)", 1.01) == 2048
    assert knee("bus (shared medium)", 2.0) == 512
    assert all(knee(l, 2.0) is None for l in FIX5["phases"]["prefill"]["per_op"] if "bus" not in l)


def test_v5_scheme_ordering_unchanged():
    """The zero-overlap end still ranks the schemes as before at every anchor
    (the perfect-overlap end is a tie at 1.00x and carries no order)."""
    order = ["star (private links)", "mesh, glb centre", "h-tree (k=4)",
             "mesh, glb corner", "bus (shared medium)"]
    for g in ANCH.values():
        vals = [stack5("prefill", l, g, True, "sum") for l in order]
        assert vals == sorted(vals), g


# -------------------------------------------------- C27: the fill-exact 2x4 default (v6)
FIX6 = json.load(open(os.path.join(HERE, "fixtures", "stack_per_op_v6.json")))
MESHES = ["mesh, glb centre", "mesh, glb corner", "h-tree (k=4)"]


def stack6(phase, label, gbps, attention_on_chip, overlap="max"):
    per = FIX6["phases"][phase]["per_op"][label]
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


def test_v6_is_a_geometry_change_only():
    """C27 switched the default die from the 3x3-with-a-hole grids to the
    fill-exact 2x4 macro / 4x2 crossbar grids. Compute, write and the
    star / bus serializations are bit-identical to v5 (no geometry in them);
    only the two routed-grid rows moved (2 schemes x 6 matmuls x 2 phases);
    the tree carried 4 macros' traffic on its busiest wire on both grids, so
    its rows did not move either."""
    assert FIX6["fabric"]["macro_mesh"] == [2, 4] and FIX6["fabric"]["crossbar_mesh"] == [4, 2]
    moved = 0
    for phase in ("prefill", "decode"):
        for label, per in FIX6["phases"][phase]["per_op"].items():
            for a, b in zip(per, FIX5["phases"][phase]["per_op"][label]):
                assert a["name"] == b["name"]
                approx(a["compute_s"], b["compute_s"], 1e-12) if b["compute_s"] else None
                assert a["write_s"] == b["write_s"]
                if label in ("mesh, glb centre", "mesh, glb corner"):
                    moved += a["serial_s"] != b["serial_s"]
                elif b["serial_s"]:
                    approx(a["serial_s"], b["serial_s"], 1e-9), (phase, label, a["name"])
        # the stall-free stack carries the per-op PROPAGATION term, which reads
        # the grids' worst-case paths (macro 2x4, crossbar 4x2): +6 us per pass
        # (0.0008% of the 826 ms prefill stack, 0.04% of the 14.8 ms decode stack)
        # -- the only non-wire number that moved
        approx(FIX6["phases"][phase]["stall_free_s"], FIX5["phases"][phase]["stall_free_s"], 5e-4)
        assert abs(FIX6["phases"][phase]["stall_free_s"] - FIX5["phases"][phase]["stall_free_s"]) < 1e-5
        assert FIX6["phases"][phase]["stall_free_s"] != FIX5["phases"][phase]["stall_free_s"]
    assert moved == 24


def test_v6_hub_position_lever_vanishes_on_the_fill_exact_grid():
    """On the 2x4 grid the routed schemes tie: mesh centre, mesh corner and
    the tree all put 4 macros' traffic on the busiest wire (the elongated
    grid funnels a full column either way), where the 3x3 read 3 / 5 / 4.
    The buffer-position lever of v5 (corner / centre 1.67x) is a property
    of the squarer grid, not of the chip."""
    for phase in ("prefill", "decode"):
        per = FIX6["phases"][phase]["per_op"]
        star = {o["name"]: o["serial_s"] for o in per["star (private links)"]}
        for label in MESHES:
            for o in per[label]:
                if star[o["name"]] > 0:
                    approx(o["serial_s"], 4.0 * star[o["name"]], 1e-9), (phase, label, o["name"])
        bus = {o["name"]: o["serial_s"] for o in per["bus (shared medium)"]}
        assert all(bus[n] > 4.0 * star[n] for n in star if star[n] > 0)


def test_v6_anchored_readout():
    """The published anchored table on the 2x4 default: 1.00x at every
    digital anchor and scheme (perfect-overlap end, both conditions); the
    zero-overlap end at Simba reads star 1.013x, the three routed schemes
    1.052x, bus 1.148x (prefill on chip) and bus 1.167x (offloaded decode);
    at ESP the bus reads 1.040x, at FlooNoC 1.016x. At the analog-reality
    band's low end (0.4 GB/s, estimated) the routed schemes read 1.31x and
    the bus 3.33x at the perfect-overlap end; at 8 GB/s every scheme 1.00x."""
    for phase, on_chip in (("prefill", True), ("decode", False)):
        for label in FIX6["phases"][phase]["per_op"]:
            for g in ANCH.values():
                approx(stack6(phase, label, g, on_chip), 1.00, 1e-3)
            approx(stack6(phase, label, 8.0, on_chip), 1.00, 5e-3)
    Z = lambda label, g, ph="prefill", oc=True: stack6(ph, label, g, oc, "sum")
    approx(Z("star (private links)", ANCH["simba"]), 1.013, 2e-3)
    for label in MESHES:
        approx(Z(label, ANCH["simba"]), 1.052, 2e-3)
        approx(stack6("prefill", label, 0.4, True), 1.312, 5e-3)
    approx(Z("bus (shared medium)", ANCH["simba"]), 1.148, 2e-3)
    approx(Z("bus (shared medium)", ANCH["simba"], "decode", False), 1.167, 2e-3)   # matmul rows only (STATIC)
    approx(Z("bus (shared medium)", ANCH["esp"]), 1.040, 2e-3)
    approx(Z("bus (shared medium)", ANCH["floonoc"]), 1.016, 2e-3)
    approx(stack6("prefill", "bus (shared medium)", 0.4, True), 3.331, 5e-3)


def test_v6_thresholds_on_the_grid():
    """2^k-grid knees (prefill on chip, perfect-overlap end), the largest
    2^k words/cycle at which the stack is >= 1.01x / >= 2x: star 256 / 64,
    the routed schemes 1,024 / 256, the bus 2,048 / 512 -- the centred grid
    moved up from 512 (v5) and the corner grid stayed, because both now
    carry 4 macros' traffic on the busiest wire."""
    def knee(label, level):
        hit = [wc for wc in (2 ** k for k in range(3, 24))
               if stack6("prefill", label, wc / WC_PER_GBPS, True) >= level]
        return max(hit) if hit else None
    assert knee("star (private links)", 1.01) == 256 and knee("star (private links)", 2.0) == 64
    for label in MESHES:
        assert knee(label, 1.01) == 1024 and knee(label, 2.0) == 256, label
    assert knee("bus (shared medium)", 1.01) == 2048 and knee("bus (shared medium)", 2.0) == 512
    order = ["star (private links)", "mesh, glb centre", "bus (shared medium)"]
    for g in ANCH.values():
        vals = [stack6("prefill", l, g, True, "sum") for l in order]
        assert vals == sorted(vals), g
