"""Group 42 -- A5 day 2: the derived lower-level link unit prices (C58-a).

Pins the route-(b) derivation chain end to end: the silicon-calibrated
macro anchor in C25 value caliber, the C38 pitch-ratio scaling, the two
derived prices, the provenance labels (route b DERIVED vs the
pre-registered route-a EXAMPLE DEFAULT fallback), and the pre-registered
acceptance gate (the C25 ~2% ceiling reproduced by an independent
arithmetic). Moving any of these is a model change -- changelog first.
"""
import dataclasses
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)


def _load():
    return json.load(open(os.path.join(WS, "analysis", "lower_link_prices.json")))


def test_anchor_is_the_calibrated_macro_link_in_value_caliber():
    d = _load()
    an = d["anchor"]
    assert an["level"] == "macro" and an["reference_hops"] == 1.0
    approx(an["router_energy_J_ffn1"], 2.668e-05, 1e-6)
    approx(an["value_words_glb_macro_ffn1"], 8_912_896.0, 1e-9)
    approx(an["effective_pj_per_value_word"], 2.9934, 1e-3)
    # the C25 value volumes the prices will multiply (day 3+)
    v = d["value_volumes_ffn1"]
    approx(v["macro<->core"], 10_485_760.0, 1e-9)
    approx(v["core<->crossbar"], 25_165_824.0, 1e-9)


def test_prices_scale_by_declared_pitch_ratio():
    d = _load()
    assert d["slot_pitch_um"] == {"macro": 800.0, "core": 400.0,
                                  "crossbar": 100.0}
    core, xbar = d["prices"]["core"], d["prices"]["crossbar"]
    m = d["anchor"]["effective_pj_per_value_word"]
    approx(core["pj_per_word"], m * 0.5, 1e-9)       # 1.497
    approx(xbar["pj_per_word"], m * 0.125, 1e-9)     # 0.374
    for p in (core, xbar):
        assert p["route"] == "b"
        assert "DERIVED" in p["provenance"]
        assert "DR-1 replaces" in p["provenance"]


def test_fallback_is_labeled_example_default():
    """The pre-registered rule: (a) fires ONLY on a broken geometry chain
    and must carry its own provenance class."""
    from scripts import derive_lower_link_prices as dl
    from scripts import fabric
    f = fabric.default()
    broken = dataclasses.replace(
        f, levels=[dataclasses.replace(lv, slot_pitch_um=None)
                   if lv.name == "crossbar" else lv for lv in f.levels])
    out = dl.derive(broken)
    xb = out["prices"]["crossbar"]
    assert xb["route"] == "a" and xb["pj_per_word"] == 1.0
    assert "EXAMPLE DEFAULT" in xb["provenance"]
    assert out["prices"]["core"]["route"] == "b"     # unbroken level stays (b)


def test_ceiling_gate_reproduces_c25():
    """Two independent arithmetics agree: the derived prices charge ffn1 at
    ~1.9% of the operator (2 hops) -- inside the C25 ~2% ceiling."""
    d = _load()
    cg = d["ceiling_gate"]
    assert cg["verdict"] == "PASS"
    assert 0.015 < cg["share_of_operator"] < 0.025
    approx(cg["operator_energy_J_ffn1"], 2.7e-3, 0.1)
    approx(cg["total_at_2hops_J"], 5.03e-5, 2e-2)


# ------------------------------------------------- days 3-4 overlay (C58-b)
def _load_energy():
    return json.load(open(os.path.join(WS, "analysis", "lower_link_energy.json")))


def test_fabric_prices_tie_to_derivation():
    """G0: the fabric config is the single source the overlay reads; it must
    equal the day-2 derivation exactly -- a drift is a red, not a rounding."""
    from scripts import fabric
    d = _load()
    f = fabric.default()
    for name in ("core", "crossbar"):
        got = f.level(name).link.pj_per_word
        want = d["prices"][name]["pj_per_word"]
        approx(got, want, 1e-9)
        assert "derived-C58a" in f.level(name).link.calibration
        assert "overlay-only" in f.level(name).link.calibration


def test_overlay_breakdown_table():
    """The rider (user, 2026-09-08): itemized rows -- words, mean hops, unit
    price, subtotal -- whose products ARE the charged energies."""
    d = _load_energy()
    core, xbar = d["levels"]["core"], d["levels"]["crossbar"]
    approx(core["words"], 10_485_760.0, 1e-9)
    approx(xbar["words"], 25_165_824.0, 1e-9)
    approx(core["mean_hops"], 1.0, 1e-9)      # star: cores sit one pitch out
    approx(xbar["mean_hops"], 1.5, 1e-9)
    for r in (core, xbar):
        approx(r["words"] * r["mean_hops"] * r["pj_per_word_per_hop"] * 1e-12,
               r["energy_J"], 1e-9)
    approx(core["energy_J"], 15.69e-6, 2e-3)
    approx(xbar["energy_J"], 14.12e-6, 2e-3)


def test_conservation_gate_is_c25_touched_extent():
    """G1 (rider): the charged volumes are the C25 value volumes -- the leaf
    ties EXACTLY to row reads / X + adc reads / (Z x Y_col), upper levels
    stay at or below the leaf total."""
    d = _load_energy()
    c = d["conservation"]
    approx(c["leaf_volume_words"], 25_165_824.0, 1e-9)
    approx(c["stats_identity_words"], c["leaf_volume_words"], 1e-9)
    assert c["upper_levels_words"]["glb<->macro"] <= c["leaf_volume_words"]
    assert c["upper_levels_words"]["macro<->core"] <= c["leaf_volume_words"]
    assert c["verdict"] == "PASS"


def test_ceiling_gate_day4():
    """G2: real-hops overlay total 29.8 uJ = 1.11% of the 2.70 mJ operator,
    inside the C25 ~2% ceiling and BELOW the day-2 flat-2-hop arithmetic
    (mean hops < 2 per level -- the pre-registered direction)."""
    d = _load_energy()
    g = d["gate"]
    assert g["verdict"] == "PASS"
    approx(g["overlay_total_J"], 29.82e-6, 2e-3)
    assert 0.008 < g["share_of_operator"] < 0.015
    assert g["overlay_total_J"] < g["day2_flat_2hop_J"]
    assert "untouched" in d["route"]          # the day-1 ruling travels along
