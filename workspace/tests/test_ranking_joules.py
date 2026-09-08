"""Group 43 -- A5 day 5: the distance rankings in joules (C58-c).

Pins the structural identity (one per-leaf price across all three
levels under route b), the exact order preservation it forces on the
per-crossbar maps, the region re-score (committed 17.8% untouched;
physical-length variant 21.4%, order preserved -- the pre-registered
pin), and the search-side conditionality sentence."""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)


def _load():
    return json.load(open(os.path.join(WS, "analysis", "ranking_joules.json")))


def test_uniform_per_leaf_price_is_structural():
    """price ~ pitch (route b) => macro/8 == core/4 == crossbar/1, checked
    from the fabric + derivation, not from this file's own output."""
    from scripts import fabric
    d = _load()
    approx(d["uniform_per_leaf_pj"], 0.374176923, 1e-6)
    f = fabric.default()
    dv = json.load(open(os.path.join(WS, "analysis", "lower_link_prices.json")))
    per_leaf = [dv["anchor"]["effective_pj_per_value_word"] / 8.0,
                f.level("core").link.pj_per_word / 4.0,
                f.level("crossbar").link.pj_per_word]
    assert max(per_leaf) - min(per_leaf) < 1e-9


def test_map_orders_preserved_exactly():
    """The strengthened order pin, map half: joules ratio == distance ratio
    (one constant), and the distance ratios are the committed 1.70x/3.69x."""
    d = _load()
    m24 = d["per_crossbar_maps"]["2x4_default"]
    m33 = d["per_crossbar_maps"]["3x3_variant"]
    approx(m24["ratio_distance_ranking"], 1.697, 1e-3)
    approx(m33["ratio_distance_ranking"], 3.692, 1e-3)
    for m in (m24, m33):
        approx(m["ratio_joules"], m["ratio_distance_ranking"], 1e-12)
        assert "not an account entry" in m["caliber"]
    approx(m24["min_uJ"], 0.2023, 2e-3)      # the map now has units
    approx(m24["max_uJ"], 0.3433, 2e-3)
    approx(m33["max_uJ"], 0.2759, 2e-3)


def test_region_order_pin_and_joules():
    """The pre-registered region pin: committed index metric untouched at
    17.8%; the physical-length re-score (macro 800 / core 400 um) reads
    21.4% and the ORDER is preserved (dataflow order stays better)."""
    d = _load()
    r = d["region"]
    approx(r["index_drop_pct"], 17.81, 1e-2)
    approx(r["phys_drop_pct"], 21.38, 1e-2)
    assert r["order_pin"] == "PRESERVED"
    s, df = r["orders"]["size order"], r["orders"]["dataflow order"]
    assert df["vw_phys_leaf_total"] < s["vw_phys_leaf_total"]
    approx(s["energy_uJ_per_layer"], 8.579, 2e-3)
    approx(df["energy_uJ_per_layer"], 6.745, 2e-3)
    approx(r["gap_uJ_per_layer"], 1.834, 2e-3)
    approx(s["energy_uJ_model_pass"], 12 * s["energy_uJ_per_layer"], 1e-9)


def test_search_side_conditionality_sentence():
    """The sentence the search side eats: distance rankings ARE energy
    rankings exactly while price ~ length holds; a DR-1 breaking the
    proportionality can reorder -- recorded as a finding, never
    re-parameterized."""
    d = _load()
    s = d["search_side_sentence"]
    assert "price ~ length" in s
    assert "reorder" in s
    assert "never" in s and "adjustment" in s
    assert "EXACTLY" in d["structural_sentence"]
