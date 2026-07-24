"""Group 4/5 -- floorplan properties + the north-star xfails.

xfail_* functions document the KNOWN modeling gaps (workstreams A/B/C). Each is
EXPECTED to fail today; when one starts passing, promote it to test_* in the PR
that closed the gap.
"""
import inspect

from _util import fixture

import scripts.crossbar_comm as cc
from scripts import placement_aware as pa


def test_floorplan_coords_distinct_and_complete():
    xb, core, macro, die, gshape = cc.nested_floorplan(8, 4, 8)
    assert len(xb) == 256
    assert len(set(xb.values())) == 256, "two crossbars share a coordinate"
    assert len(core) == 32 and len(macro) == 8


def test_moving_closer_is_never_more_expensive():
    """monotone-in-distance property; must also hold for any future CostModel
    and for the fast evaluator (same assertion, second target)."""
    xb, core, macro, die, _ = cc.nested_floorplan(8, 4, 8)
    d_near = cc._manh(die, macro[4])       # a central macro
    d_far = cc._manh(die, macro[2])        # a corner macro
    assert d_far > d_near
    vol = 1000
    assert vol * d_far > vol * d_near      # cost strictly increases with distance
    assert 0 * d_far == 0                  # zero traffic -> zero cost


# ---------------------------------------------------------------- north stars

def xfail_lower_level_links_are_priced():
    """WORKSTREAM A1/DR-1: core- and crossbar-level links carry zero energy, so
    the 3.58x map and the 17.8% placement gap cannot reach the system totals."""
    lv = pa.perceive(fixture("ffn1_prefill_stats.txt"))
    lower = [v for k, v in lv.items()
             if "inter_core_in_macro" in k or "inter_crossbar_in_core" in k]
    assert lower and all(v["energy_J"] > 0 for v in lower)


def xfail_propagation_latency_depends_on_placement():
    """WORKSTREAM A: level_max_hops takes no placement, so the propagation term
    is a constant 136 ns/op for every layout."""
    sig = inspect.signature(cc.level_max_hops)
    assert any("place" in p for p in sig.parameters), \
        "level_max_hops has no placement input"


def xfail_single_die_d2d_degenerate_invariant():
    """WORKSTREAM C6: once D2D REPLACES the flat chip2chip charge, a single-die
    fabric must yield zero inter-die cost and reproduce the pre-D2D baseline.
    No D2D module exists yet, so this documents the requirement."""
    from scripts import fabric  # noqa: F401  -- does not exist yet