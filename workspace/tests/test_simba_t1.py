"""Group 34 -- T1, the Fig 9 seating-spread experiment (C44, step 1,
day 5), governed by SIMBA_PREREG amendment A1 and graded by its criteria
table. The pins here freeze the OUTCOME as measured by our model on the
frozen fabric -- including the honest failure: T1b lands OUTSIDE its band
(tier-2 class gap, see the prereg triage record). A code change that
moves any of these numbers is a model change and must re-open the triage.
"""
from _util import approx

from scripts.simba_targets import (FIG9_MEASURED, FIG9_SEATINGS, T1_LAYER,
                                   RESNET50, t1_candidate_splits,
                                   t1_evaluate, t1_run)


def test_seatings_are_the_decoded_figure():
    assert FIG9_SEATINGS[0] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert FIG9_SEATINGS[4] == [(0, 0), (0, 5), (5, 0), (5, 5)]  # the corners
    assert FIG9_MEASURED == [1.000, 1.359, 1.739, 2.122, 2.530]


def test_enumeration_and_frozen_split():
    """A1's rule on res4a_branch1: 8 legal candidates; the four multicast-
    structured ones tie at the reference seating; deterministic tie-break
    freezes {K:2, P:2}; C-heavy splits lose (psum return at 3x width)."""
    op = RESNET50[T1_LAYER]
    cands = t1_candidate_splits(op)
    assert {frozenset(c.items()) for c in cands} == {
        frozenset({"K": 4}.items()), frozenset({"C": 4}.items()),
        frozenset({"P": 2, "Q": 2}.items()), frozenset({"K": 2, "C": 2}.items()),
        frozenset({"K": 2, "P": 2}.items()), frozenset({"K": 2, "Q": 2}.items()),
        frozenset({"C": 2, "P": 2}.items()), frozenset({"C": 2, "Q": 2}.items())}
    res = t1_run()
    assert res["frozen_split"] == {"K": 2, "P": 2}
    lat = {tuple(sorted(e["split"].items())): e["latency_max_end_s"]
           for e in res["enumeration"]}
    approx(lat[(("K", 4),)], 24.397e-6, 1e-3)
    approx(lat[(("C", 4),)], 232.67e-6, 1e-3)          # psum x3 punishes C (x17/16 since C46)
    # tie-robustness: the readout does not depend on the tie-break
    ties = [{"K": 2, "P": 2}, {"K": 2, "Q": 2}, {"K": 4}, {"P": 2, "Q": 2}]
    for seat in FIG9_SEATINGS:
        vals = [t1_evaluate(RESNET50[T1_LAYER], c, seat)["latency_max_end_s"]
                for c in ties]
        assert max(vals) - min(vals) < 1e-15


def test_t1_outcome_pins():
    """The graded outcome (re-pinned under A3 = C46): the OPTIMISTIC end
    is unchanged in shape -- serialization seating-FLAT (busiest segment
    100,352 words, now x 17/16 wire overhead), slope only from the
    one-shot propagation term -- so T1a still holds only degenerately and
    T1b's optimistic ratio still fails its band in the UNDER direction."""
    res = t1_run()
    for r, prop_ns in zip(res["rows"], (40, 80, 120, 160, 200)):
        assert r["busiest_words"] == 100_352
        approx(r["serialization_s"], 19.3860e-6, 1e-3)   # 18.2456 x 1.0625
        approx(r["compute_s"], 24.3573e-6, 1e-3)
        approx(r["prop_s"], prop_ns * 1e-9, 1e-9)
    assert res["T1a_strictly_increasing"] is True      # degenerate: see triage
    approx(res["T1b_ratio"], 1.0065581, 1e-6)
    assert res["T1b_band"] == [1.265, 5.06]
    assert res["T1b_pass"] is False                    # tier-2 class gap
    # the gap is the WHOLE measured effect: 2.53 vs our 1.0066
    approx(res["rows"][-1]["measured_norm"] / res["T1b_ratio"], 2.513, 1e-3)


def test_t1_packet_bracket_pins():
    """A3's pessimistic end, against its PRE-REGISTERED expectations:
    per-source packet term 23.52k us at bar k, pessimistic latency
    43.74 + 23.52k us, bar-5 pessimistic ratio ~2.400 -- INSIDE T1b's
    band, tracking the measured ladder from below (residual 0.7% -> 5.2%
    growing with distance = the ack/sync fingerprint, BookSim's job).
    Tilings stay frozen; the pessimistic re-score argmin is recorded as
    a sensitivity note only."""
    res = t1_run()
    for k, r in enumerate(res["rows"], 1):
        approx(r["packet_term_s"], 23.52e-6 * k, 1e-3)
        approx(r["latency_pess_s"], (43.743 + 23.52 * k) * 1e-6, 1e-3)
    for r, want in zip(res["rows"], (1.0, 1.3497, 1.6993, 2.0490, 2.3987)):
        approx(r["ratio_pess"], want, 1e-3)
    assert res["T1b_pess_in_band"] is True
    # both ends stay BELOW silicon: the conservative direction survives A3
    for r in res["rows"]:
        assert r["ratio_pess"] <= r["measured_norm"] + 1e-9
    assert res["pess_rescore_argmin"] == {"P": 2, "Q": 2}


def test_t1_pessimistic_closure_identity():
    """§10a: every bar's pessimistic value must CLOSE against its own
    decomposition -- comp + ser + (392 pkts x k + 392 pkts x 2k) x 20 ns
    -- to float precision. A composition drift (double-count, absorbed
    term, caliber mix) turns this red before it can confuse an audit."""
    import math
    res = t1_run()
    n_pkt = math.ceil(50_176 / 128)                    # 392 per slice
    assert n_pkt == 392
    for k, r in enumerate(res["rows"], 1):
        pkt = n_pkt * (k + 2 * k) * 20e-9
        approx(r["packet_term_s"], pkt, 1e-12)
        approx(r["latency_pess_s"],
               r["compute_s"] + r["serialization_s"] + pkt, 1e-12)
