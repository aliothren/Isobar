"""Group 46 -- A2 (C61): the row split measured; O15 resolved.

Pins the whole arc: the day-0 identity rerun (18/18 EXACT), the day-1
hand gate (13/13), the P1 per-level verdicts with the exact ffn2 tie,
the P2 S weld, the P3 refutation (the voluntary underfull row split is
2x WORSE for M-heavy ops, better only for ffn2), the relief finding
(row split thins the on-die trunk up to 4x, the bill moving to the
psum-dominated die edge -- the load-relocation valve, ALWAYS stated at
both levels), and the ffn1 identity SENTINEL: two independent code
paths (column-split probes, row-split scan) must forever emit the same
number at every width -- if either side breaks, this pin goes red
first."""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
A = os.path.join(WS, "analysis")


def _rows():
    d = json.load(open(os.path.join(A, "a2_row_split.json")))
    return {(r["d"], r["S"], r["op"]): r for r in d["rows"]}


def _col():
    d = json.load(open(os.path.join(A, "scaling_probes.json")))
    return {(p["d"], p["S"]): {o["name"]: o for o in p["ops"]}
            for p in d["points"]}


def test_day0_identity_rerun_was_exact():
    d = json.load(open(os.path.join(A, "a2_identity_rerun.json")))
    assert d["verdict"] == "PASS"
    assert d["counts"] == {"EXACT": 18, "NOISE": 0, "DRIFT": 0}


def test_day1_hand_gate_passed():
    d = json.load(open(os.path.join(A, "a2_hand_gate.json")))
    assert d["verdict"] == "PASS"
    assert len(d["checks"]) == 13 and all(c["ok"] for c in d["checks"])
    assert "Simba" in d["psum_width_note"]     # the caliber split stays named


def test_p1_die_line_and_the_exact_tie():
    """Closed form 2Mn > C: every natural-span die edge psum-dominated;
    ffn2 at its minimal split is the pre-registered EXACT tie."""
    rows = _rows()
    for (d, S, op), r in rows.items():
        if not r.get("feasible") or r.get("voluntary_min_dies"):
            continue
        dl = r["lines"]["die_line"]
        cf = dl["closed_form_2Mn_vs_C"]
        assert (cf["2Mn"] > cf["C"]) == dl["psum_dominated"]
        assert dl["psum_dominated"]            # holds on every natural row
    tie = rows[(1024, 512, "ffn2")]["lines"]["die_line"]
    assert tie["tie"] and tie["closed_form_2Mn_vs_C"] == {"2Mn": 4096,
                                                          "C": 4096}
    approx(2 * tie["up_words"], tie["down_words"], 1e-12)


def test_p1_per_level_split_is_real():
    """Amendment 1's payoff: die swaps while macro does not, in exactly
    the small-n rows -- each level squared by its own account."""
    rows = _rows()
    split_rows = [(2560, 512, "out_proj"), (2560, 512, "ffn2"),
                  (4096, 512, "out_proj"), (4096, 512, "ffn2"),
                  (2560, 128, "ffn2")]
    for key in split_rows:
        ln = rows[key]["lines"]
        assert ln["die_line"]["psum_dominated"]
        assert not ln["macro_line"]["psum_dominated"]
    ln = rows[(8192, 512, "ffn2")]["lines"]    # large n: macro swaps too
    assert ln["macro_line"]["psum_dominated"]


def test_p2_s_weld_holds():
    rows = _rows()
    approx(rows[(2560, 128, "ffn2")]["serial_over_compute"],
           rows[(2560, 512, "ffn2")]["serial_over_compute"], 1e-9)
    approx(rows[(2560, 512, "ffn2")]["serial_over_compute"], 0.0179, 3e-3)


def test_p3_refuted_in_the_main():
    """The voluntary underfull row split (d=1024, C:2): exactly 2x WORSE
    on-die for the M-heavy ops (per-die compute halves, the full-M psum
    up stays), better ONLY for the C-heavy ffn2 -- the company sentence
    flips to 'replication stays the better underfull exit except for
    C-heavy shapes'."""
    rows, col = _rows(), _col()[(1024, 512)]
    for op in ("qkv_proj", "out_proj", "ffn1"):
        r = rows[(1024, 512, op)]
        assert r["voluntary_min_dies"] == 2 and r["dies"] == 2
        approx(r["serial_over_compute"],
               2.0 * col[op]["serial_over_compute"], 1e-6)
    approx(rows[(1024, 512, "ffn2")]["serial_over_compute"],
           0.5 * col["ffn2"]["serial_over_compute"], 1e-6)


def test_relief_finding_two_level_valve():
    """Row split thins the per-die trunk: ffn2's on-die ratio drops 4x at
    d = 4096 / 8192 -- while the DIE edge is psum-dominated (the bill
    relocated, not erased). The valve is always stated at both levels."""
    rows, col = _rows(), _col()
    for d in (4096, 8192):
        r = rows[(d, 512, "ffn2")]
        approx(r["serial_over_compute"], 0.0179, 3e-3)
        approx(col[(d, 512)]["ffn2"]["serial_over_compute"], 0.0714, 3e-3)
        assert r["lines"]["die_line"]["psum_dominated"]


def test_ffn1_identity_sentinel():
    """THE FREE REGRESSION SENTINEL: ffn1's row-split ratio equals its
    column-split ratio at EVERY width (the C=d, M=4d arithmetic), read
    from the two independent files -- not from stored copies of one
    another. Either code path breaking turns this red first. The
    direction flips dn -> up alongside."""
    rows, col = _rows(), _col()
    for d in (2560, 4096, 5120, 6144, 8192):
        r, c = rows[(d, 512, "ffn1")], col[(d, 512)]["ffn1"]
        approx(r["serial_over_compute"], c["serial_over_compute"], 1e-9)
        assert r["bottleneck"]["direction"] == "up"
        assert c["bottleneck"]["direction"] == "dn"


def test_regime_fence():
    """New rows only: the scan file declares the row-split regime; the
    frozen probe file still declares column-split-only. R10's note now
    names the other regime as MEASURED."""
    scan = json.load(open(os.path.join(A, "a2_row_split.json")))
    frozen = json.load(open(os.path.join(A, "scaling_probes.json")))
    assert "ROW SPLIT" in scan["regime"] and "untouched" in scan["regime"]
    assert "column split only" in frozen["regime"]
    rob = json.load(open(os.path.join(A, "robustness.json")))
    r10 = {r["id"]: r for r in rob["rows"]}["R10"]
    assert "MEASURED (A2/C61)" in r10["note"]
