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


def test_anchored_stack_cells():
    d = _load()
    want = {"prefill": [1.6093, 1.0, 1.0, 1.0],
            "decode": [1.0843, 1.0, 1.0, 1.0]}
    share0 = {"prefill": 0.762, "decode": 0.967}
    for phase, vals in want.items():
        cells = d["phases"][phase]["cells"]
        assert [c["g_gbps"] for c in cells] == [0.4, 2.0, 8.0, 8.75]
        for c, w in zip(cells, vals):
            approx(c["a2_stack_ratio"], w, 1e-3)
            assert c["a1_stack_ratio"] == 1.0          # exhaustive by symmetry
        approx(cells[0]["fixed_share_best"], share0[phase], 2e-3)
        for c in cells[1:]:
            approx(c["fixed_share_best"], 1.0, 1e-9)   # above the knee
        # pre-registered directions: monotone in g; decode < prefill at 0.4
        rs = [c["a2_stack_ratio"] for c in cells]
        assert all(a >= b - 1e-12 for a, b in zip(rs, rs[1:]))
    approx(d["phases"]["decode"]["cells"][0]["a2_stack_ratio"] /
           d["phases"]["prefill"]["cells"][0]["a2_stack_ratio"], 0.674, 5e-3)


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
        approx(cells[0]["a3_stack_ratio"], stack0, 1e-3)
        for c in cells:
            approx(c["a3_mech_ratio_attn"], 3.00, 1e-2)
            approx(c["a3_mech_ratio_ffn"], 2.6667, 1e-2)
            assert c["a3_mech_ratio_attn"] > c["a3_mech_ratio_ffn"]  # free slots
        rs = [c["a3_stack_ratio"] for c in cells]
        assert all(a >= b - 1e-12 for a, b in zip(rs, rs[1:]))       # monotone
        for c in cells[1:]:
            approx(c["a3_stack_ratio"], 1.0, 1e-9)                   # above knee
    p0 = d["phases"]["prefill"]["a3_cells"][0]["a3_stack_ratio"]
    a2 = d["phases"]["prefill"]["cells"][0]["a2_stack_ratio"]
    assert 1.05 < p0 < a2                       # pre-registered stack window


def test_a3_connector_in_the_table():
    t = open(os.path.join(WS, "analysis", "soft_lever_table.md")).read()
    for want in ("A3 natural co-residency, stack (REALIZABLE)",
                 "A3 is that reopening, measured on a REALIZABLE",
                 "The evaluator needed no",
                 "new code."):
        assert want in t, want
