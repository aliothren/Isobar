"""Group 10 -- the explicit Placement object.

The two identities proved here are what make A-3's rewiring safe: the default
placement reproduces the legacy nested floorplan bit for bit, and the legacy
place_grid/place_linear geometries become instances of the same machinery
(place_linear as a fabric VARIANT -- a hardware arrangement, not a placement).
"""
import dataclasses

from _util import approx

import scripts.crossbar_comm as cc
from scripts import fabric, placement
from scripts import placement_aware as pa
from scripts.fabric import Level


# The legacy priors these tests reproduce bit for bit (place_grid, the 1.3125
# mean hops, the nested floorplan) ARE the 3x3 grids -- the default fabric up
# to C27. Since C27 the default is the fill-exact 2x4 (`test_fabric` checks it);
# the comparison variant is loaded here explicitly.
F = fabric.from_yaml("/home/workspace/models/fabric/mlx300_3x3.yaml")
SEQ = placement.sequential_fill(F)


def test_sequential_reproduces_nested_floorplan():
    xb, core, macro, die, gshape = cc.nested_floorplan(8, 4, 8)
    leaf = SEQ.leaf_coords(F)
    assert len(leaf) == 256
    for gid, (x, y) in xb.items():
        assert leaf[gid] == (x, y), f"gid {gid}: {leaf[gid]} vs legacy {(x, y)}"
    for m, (cx, cy) in enumerate(SEQ.level_coords(F, "macro")):
        approx(cx, macro[m][0], 1e-12)
        approx(cy, macro[m][1], 1e-12)
    for (mc, cc_), (cx, cy) in zip(sorted(core), SEQ.level_coords(F, "core")):
        approx(cx, core[(mc, cc_)][0], 1e-12)
        approx(cy, core[(mc, cc_)][1], 1e-12)


def test_macro_slots_equal_place_grid():
    assert [tuple(map(float, s)) for s in F.slots("macro")] \
        == [tuple(map(float, c)) for c in pa.place_grid(8)]


def test_place_linear_is_a_fabric_variant():
    """a line of 8 macros doesn't fit the 3x3 die mesh: it is a different
    hardware arrangement. Express it as a mesh-(8,1) fabric variant."""
    variant_levels = [dataclasses.replace(lv, mesh=(8, 1))
                      if lv.name == "macro" else lv for lv in F.levels]
    fv = dataclasses.replace(F, name="mlx300-linear", levels=variant_levels)
    fv.validate()
    p = placement.sequential_fill(fv)
    assert [tuple(map(float, s)) for s in p.slots["macro"]] \
        == [tuple(map(float, c)) for c in pa.place_linear(8)]


def test_verify_rejects_illegal_placements():
    good = SEQ.slots
    bad_cases = {
        "duplicate slot": {**good, "macro": [good["macro"][0]] * 8},
        "out of range": {**good, "macro": [(9, 9)] + list(good["macro"][1:])},
        "wrong count": {**good, "macro": good["macro"][:4]},
        "unknown level": {**good, "nonexistent": [(0, 0)]},
        "missing level": {k: v for k, v in good.items() if k != "core"},
    }
    for label, slots in bad_cases.items():
        try:
            placement.Placement("mlx300", slots).verify(F)
        except ValueError:
            continue
        raise AssertionError(f"illegal placement accepted: {label}")
    try:
        placement.Placement("otherchip", good).verify(F)
    except ValueError:
        pass
    else:
        raise AssertionError("fabric-name mismatch accepted")


def test_json_roundtrip():
    p = placement.from_json(SEQ.to_json(), F)
    assert p == SEQ


def test_changing_slots_moves_the_right_coords():
    """swap two macros' slots: their crossbars' coords swap, the rest stay."""
    tbl = list(SEQ.slots["macro"])
    tbl[0], tbl[7] = tbl[7], tbl[0]
    swapped = dataclasses.replace(SEQ, slots={**SEQ.slots, "macro": tbl}).verify(F)
    a, b = SEQ.leaf_coords(F), swapped.leaf_coords(F)
    per_macro = 32
    assert [b[g] for g in range(0, per_macro)] \
        == [a[g] for g in range(7 * per_macro, 8 * per_macro)]
    for g in range(per_macro, 7 * per_macro):
        assert a[g] == b[g], f"untouched crossbar {g} moved"