"""Group 19 -- the per-operator cost ledger (scripts/op_breakdown.py).

The ledger is pure bookkeeping over quantities the platform already
computes; what can go wrong is conservation (an item silently dropped or
double-counted) and silence about unmodeled costs. Both are pinned here on
the frozen ffn1 fixture (no mapper run).
"""
import os

from _util import approx, fixture

from scripts import placement_aware as pa
from scripts.op_breakdown import (UNMODELED, energy_items, latency_items,
                                  ENERGY_UNMODELED, LATENCY_UNMODELED, GROUP)


def _levels():
    return pa.perceive(fixture("ffn1_prefill_stats.txt"))


def test_energy_items_conserve_the_total():
    """sum(component rows) + sum(overlay rows) + write + rewrite + d2d +
    residual == CiMLoop total + overlay + write + rewrite + d2d, exactly
    (the placement re-pricing is an additional charge beyond CiMLoop's
    position-blind total); residual == CiMLoop total - components; every
    perceived component is a row."""
    lv = _levels()
    comp = sum(v["energy_J"] for v in lv.values())
    overlay = [("router", 8, 1.0e-6, 1.25, 1.3e-6)]           # +0.3 uJ re-pricing
    cimloop = comp + 5e-9                                    # 5 nJ unlisted lines
    items, resid = energy_items(lv, overlay, cimloop, write_J=2e-6, rewrite_J=0.0,
                                d2d_surplus_J=1e-7)
    numeric = [i for i in items if i["value"] != UNMODELED]
    approx(sum(i["value"] for i in numeric), cimloop + 0.3e-6 + 2e-6 + 1e-7, 1e-12)
    approx(resid, 5e-9, 1e-9)
    names = {i["item"] for i in items}
    for c in lv:
        assert f"component {c}" in names, c
        assert c in GROUP, f"component {c} has no group annotation"


def test_unmodeled_items_are_listed_not_absent():
    """Every unmodeled cost appears as a row carrying the marker -- never
    silently missing -- on both axes."""
    items, _ = energy_items(_levels(), [], 1.0)
    marked = {i["item"] for i in items if i["value"] == UNMODELED}
    assert marked == {n for n, _ in ENERGY_UNMODELED}
    items, _ = latency_items(1.0, 0.1, 0.5, 0.01)
    marked = {i["item"] for i in items if i["value"] == UNMODELED}
    assert marked == {n for n, _ in LATENCY_UNMODELED}


def test_latency_items_compose_to_both_bracket_ends():
    """Perfect overlap: write + max(compute, serial) + prop; zero overlap:
    write + compute + serial + prop; exposed network = the difference the
    network makes on each end."""
    for comp, ser in ((5.19e-3, 1.48e-3), (5.19e-3, 9.2e-3)):
        items, tot = latency_items(comp, 0.5e-3, ser, 1e-7, d2d_s=2.9e-3)
        val = {i["item"]: i["value"] for i in items if i["value"] != UNMODELED}
        approx(tot["perfect_overlap_s"], 0.5e-3 + max(comp, ser) + 1e-7, 1e-12)
        approx(tot["zero_overlap_s"], 0.5e-3 + comp + ser + 1e-7, 1e-12)
        exposed = val["network exposure (perfect-overlap end = max(compute, occupancy) − compute)"]
        approx(exposed, max(comp, ser) - comp, 1e-12)
        assert val["network exposure (zero-overlap end = occupancy)"] == ser
        assert val["die-to-die hand-off transfer (hidden state produced by this operator)"] == 2.9e-3


def test_unpriced_links_are_flagged():
    """A link component with zero energy (FIXLIST O1) is a row with the
    'unpriced' note, not a missing row."""
    items, _ = energy_items(_levels(), [], 1.0)
    flagged = [i for i in items if "not priced" in i["note"]]
    assert flagged, "no unpriced-link rows found in the ffn1 fixture"
    assert all(i["value"] == 0.0 for i in flagged)


def test_type_table_conserves_and_marks():
    """Whole-model operator-type view: counted shares sum to 1 under both
    conditions; under offload the attention ops carry the OFFLOADED marker
    and leave the denominator; every unmodeled operator type is a row."""
    from scripts.op_breakdown import (type_table, OFFLOADED, ATTN_OPS,
                                      MODEL_UNMODELED_TYPES)
    ops = []
    for name, e, l in (("qkv_proj", 2.0, 5.0), ("qk^t", 2.6, 13.9), ("av", 1.4, 7.4),
                       ("out_proj", 0.8, 5.2), ("ffn1", 2.7, 6.7), ("ffn2", 2.5, 13.4)):
        ops.append({"op": name, "energy_total_J": e * 1e-3,
                    "latency_total_s": {"perfect_overlap_s": l * 1e-3,
                                        "zero_overlap_s": (l + 1) * 1e-3}})
    for cond in ("on_chip", "offloaded"):
        tt = type_table(ops, 24, cond)
        counted = [r for r in tt["rows"] if r["op"] and not isinstance(r["energy_J"], str)]
        approx(sum(r["energy_share"] for r in counted), 1.0, 1e-12)
        approx(sum(r["latency_share"] for r in counted), 1.0, 1e-12)
        approx(sum(r["energy_J"] for r in counted), tt["totals"]["energy_J"], 1e-12)
        marked = {r["op"] for r in tt["rows"] if r["energy_J"] == OFFLOADED}
        assert marked == (set(ATTN_OPS) if cond == "offloaded" else set())
        unmod = {r["type"] for r in tt["rows"] if r["energy_J"] == UNMODELED}
        assert unmod == {n for n, _ in MODEL_UNMODELED_TYPES}
    assert type_table(ops, 24, "offloaded")["totals"]["energy_J"] < \
        type_table(ops, 24, "on_chip")["totals"]["energy_J"]
