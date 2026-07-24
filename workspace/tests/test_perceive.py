"""Group 1 -- perceive() faithfulness to the stats file.

Pins the class of bug found in July 2026: `base = Total scalar accesses x
Vector access energy` mixed a SCALAR count with a PER-VECTOR energy and
overstated the router baseline ~7300x. perceive() must report each component's
OWN `Energy (total)` sum, nothing reconstructed.
"""
from _util import approx, fixture, golden

from scripts import placement_aware as pa

RTOL = 2e-3


def _levels():
    return pa.perceive(fixture("ffn1_prefill_stats.txt"))


def test_component_energies_match_independent_extraction():
    lv, g = _levels(), golden("ffn1_golden_v0.json")
    for name, exp in g["component_energy_J"].items():
        assert name in lv, f"perceive lost component {name}"
        approx(lv[name]["energy_J"], exp, RTOL)


def test_fanouts():
    lv = _levels()
    assert lv["router"]["fanout"] == 8            # macro level
    assert lv["chip2chip_link"]["fanout"] == 1    # flat off-die port, single die
    assert lv["glb"]["fanout"] == 1


def test_every_component_carries_energy_field():
    # a stale/partial parse silently zeroing bases caused a div-by-zero cascade
    for name, info in _levels().items():
        assert "energy_J" in info, f"{name} missing energy_J"
        assert info["energy_J"] >= 0


def test_unit_bug_stays_dead():
    """energy_J must be the component's reported Energy(total), never the
    volume*unit_pJ reconstruction (scalar count x per-VECTOR energy: the July
    bug, ~7300x on the router). For every component where both fields exist,
    the naive product must WILDLY overshoot the true energy -- if energy_J ever
    tracks it, the reconstruction crept back in."""
    lv = _levels()
    r = lv["router"]
    assert r["energy_J"] < 1e-4, "router energy suspiciously large"
    # the bug site itself: naive product was 1.008e-2 J vs 2.668e-5 J true (~378x)
    assert r["volume"] * r["unit_pJ"] * 1e-12 > 100 * r["energy_J"]
    checked = 0
    for name, i in lv.items():
        if i["volume"] > 0 and i["unit_pJ"] > 0 and i["energy_J"] > 0:
            wrong = i["volume"] * i["unit_pJ"] * 1e-12
            # scalar count x per-vector energy overshoots by >= the block size;
            # ratio ~1 would mean the reconstruction replaced Energy(total)
            assert wrong > 1.5 * i["energy_J"], (
                f"{name}: energy_J ({i['energy_J']:.3e}) tracks volume*unit_pJ "
                f"({wrong:.3e}) -- the unit-mismatch reconstruction is back")
            checked += 1
    assert checked >= 5, "tripwire exercised too few components; check parsing"


def test_component_sum_matches_op_total():
    lv, g = _levels(), golden("ffn1_golden_v0.json")
    s = sum(i["energy_J"] for i in lv.values())
    total = g["op_energy_J"]
    assert 0.985 <= s / total <= 1.005, f"sum {s} vs op total {total}"