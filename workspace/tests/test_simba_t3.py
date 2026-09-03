"""Group 36 -- T3, the Fig 7 scaling-shape experiment (C47, step 1,
day 7), governed by SIMBA_PREREG amendment A4. The pins freeze the
outcome INCLUDING the falsified pre-registration choice: A4-3 graded the
pessimistic rail, which matches only 1 of 3 measured classes; the class
bracket [optimistic rail, pessimistic rail] contains the measured class
3 of 3 (a post-hoc reading, labeled as such in prereg §11, NOT a
criterion swap -- the rail-choice reopen is C47's formal record)."""
from _util import approx

from scripts.simba_targets import (T3_COUNTS, T3_MEASURED, t3_classify,
                                   t3_run)

CLASS_ORDER = {"SCALE": 0, "PLATEAU": 1, "DEGRADE": 2, "NONE": 3}


def test_t3_curve_and_split_pins():
    res = t3_run()
    L = res["layers"]
    want = {
        "res2[a-c]_branch2b": {
            "pess": [1.0, 1.1760, 1.1225, 1.2960],
            "opt": [1.0, 0.3541, 0.3543, 0.4434],
            "splits": [{}, {"K": 4}, {"K": 4, "C": 2}, {"K": 8, "C": 4}]},
        "res3a_branch1": {
            "pess": [1.0, 0.2500, 0.1250, 0.2266],
            "opt": [1.0, 0.2500, 0.1250, 0.0758],
            "splits": [{}, {"P": 2, "Q": 2}, {"P": 2, "Q": 4},
                       {"K": 2, "P": 4, "Q": 4}]},
        "res5[a-c]_branch2b": {
            "pess": [1.0, 0.3657, 0.2497, 0.1896],
            "opt": [1.0, 0.2504, 0.1255, 0.0565],
            "splits": [{}, {"K": 4}, {"K": 4, "C": 2}, {"K": 8, "C": 4}]},
    }
    for name, w in want.items():
        d = L[name]
        for got, exp in zip(d["curve_pess"], w["pess"]):
            approx(got, exp, 2e-3)
        for got, exp in zip(d["curve_opt"], w["opt"]):
            approx(got, exp, 2e-3)
        assert [p["split"] for p in d["points"]] == w["splits"]


def test_t3_classes_graded_and_bracketed():
    """The graded (pessimistic) rail: 1/3 -- pinned as the honest
    outcome; the class bracket contains the measured class 3/3 under
    the monotone order SCALE < PLATEAU < DEGRADE < NONE."""
    res = t3_run()
    L = res["layers"]
    assert L["res2[a-c]_branch2b"]["class_pess"] == "NONE"
    assert L["res2[a-c]_branch2b"]["class_opt"] == "DEGRADE"     # = measured
    assert L["res3a_branch1"]["class_pess"] == "DEGRADE"
    assert L["res3a_branch1"]["class_opt"] == "SCALE"            # PLATEAU between
    assert L["res5[a-c]_branch2b"]["class_pess"] == "SCALE"      # = measured
    assert L["res5[a-c]_branch2b"]["class_opt"] == "SCALE"
    assert res["all_classes_match"] is False                     # graded rail 1/3
    for d in L.values():
        lo, hi = sorted((CLASS_ORDER[d["class_opt"]],
                         CLASS_ORDER[d["class_pess"]]))
        assert lo <= CLASS_ORDER[d["measured_class"]] <= hi


def test_t3_bound_rail_never_overestimates():
    """Direction discipline: the optimistic rail sits at or below the
    measured curve at every point of every layer. (The reverse does NOT
    hold numerically for res3a at n=4/8: both rails beat silicon there
    because the enumeration finds zero-communication P/Q tilings the
    real compiler did not use -- the same tiling-freedom divergence as
    T2's res2c, recorded in prereg §11, not patched.)"""
    res = t3_run()
    for name, d in res["layers"].items():
        for o, ms in zip(d["curve_opt"], d["measured"]):
            assert o <= ms + 1e-9, (name, o, ms)
    r3 = res["layers"]["res3a_branch1"]
    assert r3["curve_pess"][1] < r3["measured"][1]               # 0.250 < 0.419


def test_t3_classifier_definitions():
    """A4-4 thresholds on synthetic curves."""
    assert t3_classify([1.0, 0.5, 0.4, 0.39]) == "SCALE"
    assert t3_classify([1.0, 0.5, 0.4, 0.43]) == "PLATEAU"       # within 10%
    assert t3_classify([1.0, 0.5, 0.4, 0.45]) == "DEGRADE"       # beyond 10%
    assert t3_classify([1.0, 1.2, 1.3, 1.4]) == "NONE"
