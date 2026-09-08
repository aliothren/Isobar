"""Group 41 -- O27 static energy + peak concurrency (C57, post-v6).

Pins the layered caliber: the parameter-free structural results (ordering
inheritance and the crossover powers -- decode's 0.09 W A-vs-B flip is
the headline), the share-as-a-function values, the schedule-level
concurrency counts, and the verbatim boundary sentence."""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)


def _load():
    return json.load(open(os.path.join(WS, "analysis", "static_energy.json")))


def test_structural_inheritance_and_crossovers():
    d = _load()
    pre, dec = d["phases"]["prefill"], d["phases"]["decode"]
    assert pre["latency_order"] == ["B", "C", "A"]
    assert dec["latency_order"] == ["C", "B", "A"]
    # prefill: every pairwise crossover is non-positive -- energy and
    # latency verdicts already agree; static power only widens the gap
    for c in pre["crossovers_W"].values():
        assert c["P_star_W"] <= 0
    # decode: the write wall's latency penalty becomes an energy penalty
    # at a TINY static power -- the parameter-free headline
    approx(dec["crossovers_W"]["AvsB"]["P_star_W"], 0.0852, 2e-3)
    assert dec["crossovers_W"]["BvsC"]["P_star_W"] <= 0


def test_share_is_a_function_not_a_value():
    d = _load()
    sh = d["phases"]["prefill"]["static_share_of_total"]
    for k in ("A", "B", "C"):
        row = sh[k]
        vals = [row[f"{p}W"] for p in (0.1, 0.3, 1.0, 3.0, 10.0, 30.0)]
        assert all(0 < a < b < 1 for a, b in zip(vals, vals[1:]))
    scen = d["phases"]["prefill"]["scenarios"]["A"]
    p = 1.0
    approx(sh["A"]["1.0W"],
           p * scen["T_s"] / (scen["E_dyn_J"] + p * scen["T_s"]), 1e-9)


def test_peak_concurrency_counts_and_boundary():
    d = _load()
    c = d["counts"]
    assert c["single_die_single_pass"]["crossbars"] == 256
    assert c["chain48_pipelined"]["dies"] == 48
    assert c["chain48_pipelined"]["crossbars"] == 48 * 256
    approx(c["per_die_avg_dynamic_W"], 0.905, 2e-2)
    approx(c["pipelined_peak_dynamic_W_estimate"],
           48 * c["per_die_avg_dynamic_W"], 1e-9)
    assert "di/dt" in d["boundary_sentence"]
    assert "OUT of scope" in d["boundary_sentence"]
    assert "schedule-level concurrency" in d["boundary_sentence"]


def test_idle_power_input_exists_and_unset_in_shipped_configs():
    from scripts import fabric
    for lv in fabric.default().levels:
        assert lv.idle_power_w is None          # dynamic-only account unchanged


def test_anchored_bracket_is_derived_and_bounding():
    """C57-a: the literature route yields NO static point value (neither
    chip publishes one) -- the anchors bound the ACTIVE-class scale, and
    the decode flip threshold reads 0.33-1.7% of it. The share stays a
    function; the point value stays a DR item."""
    d = _load()
    ab = d["anchored_bracket"]
    approx(ab["active_class_scale_W"][0], 0.0196 * 256, 1e-9)   # ~5.0 W
    approx(ab["active_class_scale_W"][1], 0.101 * 256, 1e-9)    # ~25.9 W
    lo, hi = ab["threshold_as_share_of_active_scale"]
    assert 0.003 < lo < 0.004 and 0.016 < hi < 0.018
    assert "DERIVED" in ab["caliber"]
    assert "DR item" in ab["caliber"]


def test_bracket_provenance_and_denominator_labels():
    """C57-b (review round): the 5.0-25.9 W interval is a CROSS-TECHNOLOGY
    extrapolation (130 nm RRAM end vs 14 nm PCM end) -- third provenance
    class, order-of-magnitude scaling only, NeuRRAM end primary because the
    production die is the Wan device; and the 0.33-1.7% figure must carry
    its denominator caliber (full-stream peak active power -- decode's own
    active power would raise it an order of magnitude, exact value DR)."""
    d = _load()
    ab = d["anchored_bracket"]
    assert "cross-technology extrapolation" in ab["scale_provenance"]
    assert "ORDER-OF-MAGNITUDE" in ab["scale_provenance"]
    assert "NeuRRAM end" in ab["scale_provenance"]        # primary-end rule
    assert "FULL-STREAM" in ab["share_denominator_caliber"]
    assert "order of magnitude" in ab["share_denominator_caliber"]
    assert "denominator" in ab["statement"]               # labeled in prose
    assert "0.085 W" in ab["statement"]                   # absolute survives
