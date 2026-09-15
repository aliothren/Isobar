"""Group 37 -- the soft-placement lever at the anchors (C49, step 2).

Pins the anchored table AND its pre-registered expectation checks
(FIXLIST step 2): the uniformity fit is exact, so A1 (real, joint seat
permutations) is 1.000 by symmetry -- exhaustively; the C28 synthetic
ceiling folds through the stored whole-stack ledger per anchor. The
inherited 1.31x-at-0.4 number is SUPERSEDED by the v6 ledger's 1.609x
(recorded as a finding per the pre-registration); the inherited
1.5-1.7x band-low-end claim is confirmed.
"""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)


def _load():
    return json.load(open(os.path.join(WS, "analysis", "soft_lever.json")))


def test_self_checks_are_exact():
    """The two pre-registered gates: the uniform (D,U) model reproduces
    all five schemes' stored serializations, and the refolded shipped
    stack reproduces the stored whole-stack row -- both to 1e-9."""
    d = _load()
    for phase in ("prefill", "decode"):
        ph = d["phases"][phase]
        assert ph["stack_check_rel_err"] < 1e-9
        assert len(ph["levers"]) == 6                  # the block's matmuls
        for lv in ph["levers"].values():
            assert lv["fit_rel_err"] < 1e-9


def test_mechanism_ratio_is_pure_geometry():
    """A2 mechanism = 1.750 for every op, both phases (the C28 pin,
    op- and condition-independent as pre-registered)."""
    d = _load()
    for phase in ("prefill", "decode"):
        for lv in d["phases"][phase]["levers"].values():
            approx(lv["a2_mech_ratio"], 1.75, 1e-9)


def _by_g(cells):
    """Anchors are addressed BY VALUE, not by position: the anchor set is
    extensible (0.1 / 0.2 added for the lever's saturation plateau) and
    the standing pins must survive the extension."""
    return {c["g_gbps"]: c for c in cells}


def test_anchored_stack_cells():
    d = _load()
    want = {"prefill": {0.4: 1.6093, 2.0: 1.0, 8.0: 1.0, 8.75: 1.0},
            "decode": {0.4: 1.0843, 2.0: 1.0, 8.0: 1.0, 8.75: 1.0}}
    share0 = {"prefill": 0.762, "decode": 0.967}
    for phase, vals in want.items():
        cells = d["phases"][phase]["cells"]
        by = _by_g(cells)
        assert {0.1, 0.2, 0.4, 2.0, 8.0, 8.75} <= set(by)
        for g, w in vals.items():
            approx(by[g]["a2_stack_ratio"], w, 1e-3)
        for c in cells:
            assert c["a1_stack_ratio"] == 1.0          # exhaustive by symmetry
        approx(by[0.4]["fixed_share_best"], share0[phase], 2e-3)
        for g in (2.0, 8.0, 8.75):
            approx(by[g]["fixed_share_best"], 1.0, 1e-9)   # above the knee
        # pre-registered directions: monotone in g
        rs = [c["a2_stack_ratio"] for c in sorted(cells,
                                                  key=lambda c: c["g_gbps"])]
        assert all(a >= b - 1e-12 for a, b in zip(rs, rs[1:]))
    approx(_by_g(d["phases"]["decode"]["cells"])[0.4]["a2_stack_ratio"] /
           _by_g(d["phases"]["prefill"]["cells"])[0.4]["a2_stack_ratio"],
           0.674, 5e-3)


def test_low_anchor_staircase_and_plateau():
    """A3 (the 0.1 / 0.2 extension): the lever's three-stage staircase --
    flat above the knee, opening through 0.4, saturating below. The A2
    (uniform-mapping) lever approaches its own mechanism ratio 1.750
    (1.7347 at 0.1, within 1%); the REALIZABLE A3 lever does NOT
    approach its 3.00 / 2.67 (1.6979 at 0.1) -- finding F-A3: the
    mechanism ratio is a CEILING, approached only in proportion to the
    share of the stack the lever commands (the A3 lever leaves
    attention, the elementwise terms and the other dies fixed)."""
    d = _load()
    a2 = _by_g(d["phases"]["prefill"]["cells"])
    a3 = _by_g(d["phases"]["prefill"]["a3_cells"])
    approx(a2[0.2]["a2_stack_ratio"], 1.7199, 1e-3)
    approx(a2[0.1]["a2_stack_ratio"], 1.7347, 1e-3)
    mech_a2 = a2[0.1]["a2_mech_ratio"]
    approx(mech_a2, 1.750, 1e-3)
    assert a2[0.1]["a2_stack_ratio"] / mech_a2 > 0.99      # plateau reached
    approx(a3[0.2]["a3_stack_ratio"], 1.6220, 1e-3)
    approx(a3[0.1]["a3_stack_ratio"], 1.6979, 1e-3)
    # F-A3: still far below its own mechanism ratio at the deepest anchor
    assert a3[0.1]["a3_stack_ratio"] / a3[0.1]["a3_mech_ratio_ffn"] < 0.7
    dec = _by_g(d["phases"]["decode"]["a3_cells"])
    approx(dec[0.1]["a3_stack_ratio"], 1.2294, 1e-3)
    assert dec[0.1]["a3_stack_ratio"] < a3[0.1]["a3_stack_ratio"]


def test_band_thresholds():
    """C-part: where the (synthetic-ceiling) band is visible: >1% below
    ~1.37 / ~1.08 GB/s, >10% below ~1.06 / ~0.33 (prefill / decode)."""
    d = _load()
    approx(d["phases"]["prefill"]["g_threshold_1pct"], 1.368, 2e-3)
    approx(d["phases"]["prefill"]["g_threshold_10pct"], 1.062, 2e-3)
    approx(d["phases"]["decode"]["g_threshold_1pct"], 1.084, 2e-3)
    approx(d["phases"]["decode"]["g_threshold_10pct"], 0.333, 2e-3)


def test_a1_is_structural_degeneracy_not_a_null_search():
    """C49-a adjudication: any two seatings carry IDENTICAL per-wire
    loads for every lever op (zero freedom, not differences canceling at
    the max); the second evidence layer is the extraction's certified
    even division. The claim is therefore CONDITIONED, never global."""
    d = _load()
    for phase in ("prefill", "decode"):
        dg = d["phases"][phase]["degeneracy"]
        assert len(dg) == 6
        for name, e in dg.items():
            assert e["wirewise_identical"] is True, (phase, name)
            assert e["n_wires"] >= 10


def test_table_exists_with_the_conditioned_reading():
    t = open(os.path.join(WS, "analysis", "soft_lever_table.md")).read()
    for want in ("A1 real, exhaustive (stack) | 1.000 | 1.000 | 1.000 | 1.000",
                 "STRUCTURAL DEGENERACY",
                 "FROZEN TO ZERO BY",
                 "NOT a realizable seating",
                 "each",
                 "of which reopens the space when it breaks",
                 "must NOT be read as 'on-die placement never",
                 "the MAPPING decides whether",
                 "searchable freedom concentrates at the die level"):
        assert want in t, want
    # the banned unconditioned phrasing stays out
    assert "placement leverage lives at the DIE level" not in t


def test_a3_natural_coresidency_reopens_the_space():
    """C49-b: the REALIZABLE on-die lever. Joint seatings exhaustive
    (attn die 280, ffn die 70); every pre-registered direction held; the
    magnitude pre-estimate (mech 1.1-1.8) was UNDERSHOT by the data --
    mech 3.00/2.67 exceeds even A2's synthetic 1.75, recorded as a
    finding (A2's 'ceiling' is scoped to the uniform-mapping world)."""
    d = _load()
    for phase, stack0 in (("prefill", 1.4341), ("decode", 1.0570)):
        ph = d["phases"][phase]
        assert ph["a3"]["attn"]["n_seatings"] == 280
        assert ph["a3"]["ffn"]["n_seatings"] == 70
        cells = ph["a3_cells"]
        by = _by_g(cells)
        approx(by[0.4]["a3_stack_ratio"], stack0, 1e-3)
        for c in cells:
            approx(c["a3_mech_ratio_attn"], 3.00, 1e-2)
            approx(c["a3_mech_ratio_ffn"], 2.6667, 1e-2)
            assert c["a3_mech_ratio_attn"] > c["a3_mech_ratio_ffn"]  # free slots
        rs = [c["a3_stack_ratio"] for c in sorted(cells,
                                                  key=lambda c: c["g_gbps"])]
        assert all(a >= b - 1e-12 for a, b in zip(rs, rs[1:]))       # monotone
        for g in (2.0, 8.0, 8.75):
            approx(by[g]["a3_stack_ratio"], 1.0, 1e-9)               # above knee
    p0 = _by_g(d["phases"]["prefill"]["a3_cells"])[0.4]["a3_stack_ratio"]
    a2 = _by_g(d["phases"]["prefill"]["cells"])[0.4]["a2_stack_ratio"]
    assert 1.05 < p0 < a2                       # pre-registered stack window


def test_a3_connector_in_the_table():
    t = open(os.path.join(WS, "analysis", "soft_lever_table.md")).read()
    for want in ("A3 natural co-residency, stack (REALIZABLE)",
                 "A3 is that reopening, measured on a REALIZABLE",
                 "The evaluator needed no",
                 "new code."):
        assert want in t, want
