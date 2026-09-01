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

def test_exact_total_energy_closes_the_summary_rounding():
    """Hygiene 22 (C40): `tl_output_parsing.exact_total_energy_J` sums the
    per-component 'Energy (total)' lines -- on the frozen ffn1 fixture
    2697.92 uJ, where the rounded per-compute summary path (pytimeloop's
    parse) gives 2699.48 uJ: a +0.058% overcount from print precision.
    run_mlx_layer now ships the exact value (the rounded one stays on
    `energy_summary_J`); published JSON energies move by <= 0.5% at the
    next regeneration and the ledger's residual row closes then."""
    import os
    import re
    from scripts import tl_output_parsing as tlp
    here = os.path.dirname(os.path.abspath(__file__))
    txt = open(os.path.join(here, "fixtures", "ffn1_prefill_stats.txt")).read()
    exact = tlp.exact_total_energy_J(txt)
    approx(exact, 2697.92e-6, 1e-4)
    i = txt.find("Computes =")
    computes = int(txt[i:].splitlines()[0].split()[-1])
    rounded = 0.0
    for l in txt[i:].splitlines()[1:]:
        if "=" in l:
            e, v = l.rsplit("=", 1)
            if e.strip() != "Total":
                try:
                    rounded += float(v.strip()) * computes / 1e15
                except ValueError:
                    pass
    approx(rounded / exact, 1.00058, 1e-4)
    # IDENTITY, not just a golden (C40-r): the sum must agree with the
    # stats file's OWN Summary 'Energy:' line within its print precision
    # (3 significant digits) -- this re-validates at every regeneration
    m = re.search(r"^Energy:\s*([\d.eE+]+) uJ", txt, re.M)
    approx(exact, float(m.group(1)) * 1e-6, 2.5e-3)
    # the temporal-reduction / address-generation adders are separate line
    # items in Timeloop's account and are INCLUDED in the sum; under this
    # architecture's ERTs they are all zero today (so they add nothing) --
    # a future ERT pricing them cannot be silently dropped
    assert not re.search(r"Temporal Reduction Energy \(total\)\s*:\s*[1-9]", txt)
    assert not re.search(r"Address Generation Energy \(total\)\s*:\s*[1-9]", txt)
