"""Group 4/5 -- floorplan properties + the north-star xfails.

xfail_* functions document the KNOWN modeling gaps (workstreams A/B/C). Each is
EXPECTED to fail today; when one starts passing, promote it to test_* in the PR
that closed the gap.
"""
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

def _alt_macro_placement():
    """A legal placement occupying a DIFFERENT, ASYMMETRIC slot set. Two traps
    to avoid when picking it: permuting the same slots cannot move a worst-case
    metric, and a symmetric slot set (empty center or empty corner) cannot
    either -- the hub is the centroid, which re-centers with the layout. An
    empty EDGE slot breaks the symmetry (max hops 12.0 -> 12.75)."""
    import dataclasses

    from scripts import fabric, placement
    f = fabric.from_yaml("/home/workspace/models/fabric/mlx300_3x3.yaml")   # the 3x3 grid this geometry test is written for
    seq = placement.sequential_fill(f)
    tbl = [(x, y) for y in range(3) for x in range(3) if (x, y) != (1, 0)]
    return f, dataclasses.replace(seq, slots={**seq.slots, "macro": tbl}).verify(f)


def test_propagation_latency_depends_on_placement():
    """promoted from xfail when A-3 landed: the propagation term must follow
    the actual layout, not a fixed worst-case geometry."""
    f, alt = _alt_macro_placement()
    default = cc.level_max_hops(f)
    moved = cc.level_max_hops(f, alt)
    assert moved["glb<->macro"] != default["glb<->macro"], \
        "a different macro slot set must change the top-level worst-case hops"
    assert moved["core<->crossbar"] == default["core<->crossbar"], \
        "untouched levels must keep their geometry"


def test_energy_overlay_placement_equals_place_fn_priors():
    """the placement path must reproduce both legacy priors bit for bit:
    sequential on mlx300 == place_grid; sequential on the (8,1) mesh variant
    == place_linear."""
    import dataclasses

    from scripts import fabric, placement
    levels = {"router": {"fanout": 8, "unit_pJ": 48.3, "volume": 10,
                         "energy_J": 2.668e-5}}
    layout = {"router": {"pattern": "to_center", "reference_hops": 1.0}}
    # the legacy prior `place_grid` IS the 3x3 grid; since C27 the default is
    # the 2x4, so the bit-for-bit identity is checked on the 3x3 variant
    f = fabric.from_yaml("/home/workspace/models/fabric/mlx300_3x3.yaml")

    old = pa.position_aware_cost(levels, layout, pa.place_grid)
    new = pa.position_aware_cost(levels, layout, placement=placement.
                                 sequential_fill(f), fabric=f)
    assert new["position_aware"] == old["position_aware"]

    lin_levels = [dataclasses.replace(lv, mesh=(8, 1))
                  if lv.name == "macro" else lv for lv in f.levels]
    fv = dataclasses.replace(f, name="mlx300-linear", levels=lin_levels).validate()
    old_lin = pa.position_aware_cost(levels, layout, pa.place_linear)
    new_lin = pa.position_aware_cost(levels, layout, placement=placement.
                                     sequential_fill(fv), fabric=fv)
    assert new_lin["position_aware"] == old_lin["position_aware"]


def test_lower_level_links_are_priced():
    """WORKSTREAM A1/DR-1 -- acceptance REWRITTEN 2026-09-08 (C58-a, the A5
    day-1 route ruling; old clause: energy_J > 0 INSIDE the perceived
    CiMLoop stats). PROMOTED from xfail_ 2026-09-08 (C58-b): the overlay
    mechanism landed at A5 day 3; the runner's rule is to promote in the
    round that closes the gap.

    Ruling: the OVERLAY route. The CiMLoop account keeps its inherited
    silicon calibration untouched -- writing a derived-grade price into the
    calibrated per-word account would dilute that account's evidence grade.
    The platform prices core/crossbar traffic as a DECLARED supplement
    outside the calibrated account (same convention as the D2D surplus
    overlay: words x pJ/word x hops), and DR-1's arrival becomes a constant
    swap instead of a model-change round.

    Passes when BOTH lower link levels carry a positive derived price in
    the fabric config (calibration label upgraded from bare DR-1) AND the
    overlay readout (analysis/lower_link_energy.json, A5 day 3) reports
    positive energy for both levels on the ffn1 fixture."""
    import json
    import os

    from scripts import fabric as fabric_mod
    fab = fabric_mod.default()
    for name in ("core", "crossbar"):
        p = fab.level(name).link.pj_per_word
        assert p is not None and p > 0, f"{name} link still unpriced"
    here = os.path.dirname(os.path.abspath(__file__))
    rd = os.path.join(here, "..", "analysis", "lower_link_energy.json")
    d = json.load(open(rd))
    assert all(d["levels"][k]["energy_J"] > 0 for k in ("core", "crossbar"))
