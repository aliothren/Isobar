"""Group 40 -- the die-level D2D energy column (O27 pre-flight, post-v6).

Pins the never-before-surfaced energy column against its FIXLIST step-8
pre-registration: the convention gate (stored surplus reproduced), the
three numbers per scenario, and the expectation reconciliation --
including the two expectations the data OVERRULED (the review's
single-digit-percent share hand; the draft's no-anti-ordering hand)."""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)


def _load():
    return json.load(open(os.path.join(WS, "analysis", "d2d_energy_column.json")))


def test_b1_orderings_column():
    d = _load()["B1_orderings_48die"]
    approx(d["ratio_worst_best"], 6.553, 1e-3)         # = avg-hops ratio (gate)
    approx(d["tie_break"]["energy"], 1.745, 1e-3)      # latency-tied pair
    assert d["gate"] == "stored surplus reproduced exactly"
    # shares: SUB-percent everywhere (our arithmetic hand; the review's
    # single-digit-% hand missed -- both were filed, data decided)
    for tag, s in d["shares"].items():
        assert s["worst"] < 0.01, (tag, s)
        assert s["best"] < s["worst"]
    approx(d["shares"]["prefill_offloaded"]["worst"], 0.0076, 2e-2)


def test_b3_probe_inversion():
    """The draft expectation 'no anti-ordering' was OVERRULED: among
    non-optimal seatings, four-corners beats one-column on latency yet
    costs more D2D energy; the latency-BEST seating (clustered) is still
    energy-best -- the at-optimum claim survives."""
    d = _load()["B3_probe_4die"]
    approx(d["ratio_worst_best"], 16.0 / 3.0, 1e-3)    # 4.0/0.75 mean hops
    assert d["same_direction"] is False
    rows = {r["label"]: r for r in d["rows"]}
    best_lat = min(rows.values(), key=lambda r: r["lat_s"])
    best_e = min(rows.values(), key=lambda r: r["d2d_energy_J"])
    assert best_lat["label"] == best_e["label"] == "clustered at anchor"
    assert rows["four corners"]["lat_s"] < rows["one column"]["lat_s"]
    assert rows["four corners"]["d2d_energy_J"] > rows["one column"]["d2d_energy_J"]


def test_b2_chain_styles():
    d = _load()["B2_chain_2p7b"]
    approx(d["prefill_onchip"]["ratio_worst_best"], 1.083, 2e-3)
    approx(d["decode_offloaded"]["ratio_worst_best"], 1.145, 2e-3)
    for cond in d.values():
        assert cond["same_direction"] is False
        # choosing the latency-best style costs at most 8.3% of a
        # sub-percent account -> system-level freeness survives
        assert cond["cost_of_latency_best"] <= 0.084


def test_convention_is_the_repo_charge():
    d = _load()
    assert "flat + surplus" in d["convention"]
    assert "replace-never-add" in d["convention"]
