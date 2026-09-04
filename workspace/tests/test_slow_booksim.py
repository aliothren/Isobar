"""Slow group 38 -- the BookSim bridge's day-1 identity gates (C51).

Runs the vendored cycle-accurate reference (seconds per invocation);
skipped cleanly when the binary is absent (build per
tools/booksim2/BUILD_NOTES.md). The fast-suite conversion pins live in
the module's constants and are asserted here too (cheap).
"""
from _util import SkipTest, approx

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from scripts import booksim_bridge as bb

T1_BAR1_FLOWS = [(0, 1, 392), (0, 6, 392), (0, 7, 392)]


def _need_binary():
    if not bb.available():
        raise SkipTest("booksim binary missing -- tools/booksim2/BUILD_NOTES.md")


def test_conversion_table_pins():
    approx(bb.CHANNEL_CYCLE_S, 8.0 / 5.5e9, 1e-12)     # 1.4545 ns
    assert bb.PACKET_FLITS == 17 and bb.PACKET_PAYLOAD_B == 128.0
    assert bb.HOP_CHANNEL_CYCLES + bb.HOP_ROUTER_CYCLES == 14   # 20.36 ns
    assert bb.packets_for(100_352) == 784
    b = bb.flit_bounds(T1_BAR1_FLOWS)
    assert b == {"channel_bound_cycles": 13_328,
                 "injection_bound_cycles": 19_992}


def test_gate_a_optimistic_identity():
    """Batch completion lands on the declared reference -- max(mesh
    channel bound, injection bound) -- within 5%; measured 1.0018."""
    _need_binary()
    r = bb.run_batch(T1_BAR1_FLOWS)
    ref = max(bb.flit_bounds(T1_BAR1_FLOWS).values())
    ratio = r["cycles"] / ref
    assert 1.0 <= ratio <= 1.05, ratio
    approx(ratio, 1.0018, 2e-3)


def test_gate_b_per_packet_identity():
    """The per-packet serial sum closes EXACTLY against 17 + 14h + base
    (base = 7, the source/sink interface constant of the BDP-aligned
    config; the day-1 log's 37 was measured before vc_buf_size=34 --
    the default 8-flit buffer credit-stalled even a lone packet)."""
    _need_binary()
    base = bb.run_batch([(0, 1, 1)])["cycles"] - 17 - 14
    assert base == 7
    tot = pred = 0
    for (s, d, n), h in zip(T1_BAR1_FLOWS, (1, 1, 2)):
        tot += n * bb.run_batch([(s, d, 1)])["cycles"]
        pred += n * (17 + 14 * h + base)
    assert tot == pred


def test_patch_acceptance_single_source():
    """The vendored file-traffic patch: one source, hand-counted -- N
    packets serialize on its injection channel: completion ~= N x 17 +
    latency terms."""
    _need_binary()
    r = bb.run_batch([(0, 2, 20)])
    assert 20 * 17 <= r["cycles"] <= 20 * 17 + 100, r["cycles"]


def test_day2_two_component_decomposition():
    """C52: the reviewer-signed frame, measured. Network-internal share
    (bound -> BookSim): bar1 +0.18%, bar5 +0.74% -- bar5 > bar1 (the
    distance-linearity signature INSIDE the network layer), single-digit
    percent as pre-written; both brackets are WIDE so the guard reports
    lambda (~0.001, the optimistic end) -- the corrected expectation.
    Protocol share (BookSim -> silicon): 2.530 / 1.0056 = 2.516x -- the
    bulk, with a measured anchor."""
    _need_binary()
    import json, os
    from scripts.analyze_booksim_slack import POINTS, rails
    res = {}
    for name, p in POINTS.items():
        t_opt, t_pess, _ = rails(p["flows"], p["hops"])
        r = bb.run_batch(p["flows"])
        res[name] = (t_opt, t_pess, r["cycles"])
    o1, p1, b1 = res["bar1_adjacent"]
    o5, p5, b5 = res["bar5_corners"]
    assert (o1, p1) == (19_992, 50_176)
    assert (o5, p5) == (19_992, 137_984)
    assert b1 == 20_027 and b5 == 20_139          # deterministic seeds
    assert (b5 - o5) > (b1 - o1)                   # net-internal distance signature
    approx((b1 - o1) / o1, 0.00175, 2e-1)
    approx((b5 - o5) / o5, 0.00735, 1e-1)
    ratio = b5 / b1
    approx(ratio, 1.0056, 1e-3)
    approx(2.530 / ratio, 2.516, 1e-3)             # the protocol share: the bulk
    # guard verdict: both brackets wide -> lambda reported, near zero
    for (o, p, b) in res.values():
        g = bb.lam(b * bb.CHANNEL_CYCLE_S, o * bb.CHANNEL_CYCLE_S,
                   p * bb.CHANNEL_CYCLE_S)
        assert g["reported"] == "lambda" and g["lambda"] < 0.01
