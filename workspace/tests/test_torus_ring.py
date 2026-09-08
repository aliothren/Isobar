"""Group 45 -- A7 (C60): torus + ring join the registry.

Pins the folded-model contract (hops = physical length, router_hops =
crossing count -- the C60 clause-1 split), the hand-derived identities
on both grids, the C59 energy identity, the packet guard, and the day-3
readouts INCLUDING the recorded expectation flip: the 48-die ordering
spread WIDENS under ring (6.55x -> 12.26x -- a 1D cycle's far end is
longer than a 2D mesh's; "the ring removes the far end" is true against
a chain, false against the mesh) while torus narrows it (3.57x), and
the ordering roles swap (sequential rows is ring's native optimum at
exactly 1.0). Moving any number here is a model change -- changelog
first."""
import dataclasses
import json
import os

from _util import approx

from scripts import anchors, fabric, interconnect as ic, placement

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)

F24 = fabric.default()


def _readout():
    return json.load(open(os.path.join(WS, "analysis", "torus_ring.json")))


def _macro_torus(params=None):
    slots = placement.sequential_fill(F24).slots["macro"]
    return ic.Torus(slots, {"routing": "xy", "hub": "center", **(params or {})})


# ------------------------------------------------------- hand identities
def test_torus_folds_only_the_wide_axis():
    """2x4 macro grid (x width 2, y width 4): wrap + fold on y only --
    the pre-filed degenerate note, unchanged under the folded model."""
    t = _macro_torus()
    assert t._wraps == (False, True) and t._fold == (1.0, 2.0)


def test_torus_hand_distances_and_the_count_length_split():
    """Hand: node0 (0,0) -> node7 (1,3): x 1 + y min(3, 4-3)=1 -> count 2,
    physical 1x1 + 1x2 = 3 (mesh reads 4). The wrap route (0,0)->(0,3):
    ONE router crossing over TWO slot pitches -- the exact divergence the
    clause-1 split exists for."""
    t = _macro_torus()
    approx(t.router_hops(0, 7), 2.0, 1e-12)
    approx(t.hops(0, 7), 3.0, 1e-12)
    approx(t.router_hops(0, 6), 1.0, 1e-12)     # (0,0)->(0,3) wraps
    approx(t.hops(0, 6), 2.0, 1e-12)
    # an adjacent hop on the folded axis is also 2 pitches of wire
    approx(t.router_hops(0, 2), 1.0, 1e-12)     # (0,0)->(0,1)
    approx(t.hops(0, 2), 2.0, 1e-12)
    # C59 identity on the physical length (point-to-point scheme)
    for i in range(8):
        approx(t.energy_hops(ic.HUB, i), t.hops(ic.HUB, i), 1e-12)


def test_torus_wrap_wire_exists_only_when_used():
    """The corner-hub routes use the y wrap; its segment is a distinct
    resource the mesh never has."""
    slots = placement.sequential_fill(F24).slots["macro"]
    tk = ic.Torus(slots, {"routing": "xy", "hub": "corner"})
    mk = ic.Mesh(slots, {"routing": "xy", "hub": "corner"})
    wrap = "torus:seg(0, 0)-(0, 3)"
    assert wrap in tk.resources()
    assert all("(0, 0)-(0, 3)" not in r for r in mk.resources())


def test_torus_idealized_param_removes_the_fold():
    t = _macro_torus({"idealized": True})
    assert t._fold == (1.0, 1.0)
    approx(t.hops(0, 6), t.router_hops(0, 6), 1e-12)


def test_ring_hand_identities():
    """48-cycle, folded: neighbor = 1 crossing / 2 pitches; the far point
    is 24 crossings; the closing edge is seg47; every link is a resource."""
    r = ic.Ring([(i, 0) for i in range(48)], {})
    approx(r.router_hops(0, 47), 1.0, 1e-12)
    approx(r.hops(0, 47), 2.0, 1e-12)
    approx(r.router_hops(0, 24), 24.0, 1e-12)
    assert r.path(47, 0) == ["ring:seg47"]
    assert len(r.resources()) == 48
    approx(r.energy_hops(0, 47), r.hops(0, 47), 1e-12)


def test_packet_params_refused_on_folded_schemes():
    """C60 clause 1: per-router packet constants must not silently read the
    folded physical length -- the combination refuses to validate."""
    levels = []
    for lv in F24.levels:
        if lv.name == "macro":
            lv = dataclasses.replace(lv, link=dataclasses.replace(
                lv.link, topology="torus",
                params={"routing": "xy", "hub": "center"},
                packet_payload_bytes=8.0))
        levels.append(lv)
    bad = dataclasses.replace(F24, name="pkt-torus", levels=levels)
    try:
        bad.validate()
    except ValueError as e:
        assert "router_hops" in str(e)
    else:
        raise AssertionError("packet params on a folded scheme validated")


# ------------------------------------------------------- day-3 readouts
def test_on_die_portrait():
    """The three-sentence portrait, as measured (two recorded refinements:
    the count saving exists only for ECCENTRIC hubs -- from a central hub
    wrap never helps a path <= half-width, count means are EQUAL; and the
    mean physical regression is up to 2x on these small grids, exceeding
    clause 2's 'slight')."""
    d = _readout()["on_die"]
    g24, g33 = d["2x4"], d["3x3"]
    approx(g24["torus/center"]["count_mean"], g24["mesh/center"]["count_mean"], 1e-12)
    approx(g24["torus/corner"]["count_mean"], 1.5, 1e-12)   # mesh corner: 2.0
    approx(g24["mesh/corner"]["count_mean"], 2.0, 1e-12)
    approx(g24["torus/center"]["phys_mean"], 2.5, 1e-12)    # vs mesh 1.5
    approx(g33["torus/center"]["phys_mean"], 2.5, 1e-12)    # vs mesh 1.25 (2x)
    approx(g33["torus/corner"]["count_mean"], 1.25, 1e-12)  # mesh corner: 1.75


def test_hub_lever_erased_on_the_squarer_grid():
    """The pre-registered net benefit, landed in its strongest form: the
    3x3 corner/centre peak lever (the pinned 5/3) reads 1.00 under torus
    -- torus is the hardware antidote to hub-position sensitivity. The
    2x4 stays 1.00/1.00 (already hub-insensitive on the peak, pinned)."""
    d = _readout()["on_die"]
    approx(d["3x3"]["mesh_corner_over_center_peak"], 5.0 / 3.0, 1e-9)
    approx(d["3x3"]["torus_corner_over_center_peak"], 1.0, 1e-9)
    approx(d["2x4"]["mesh_corner_over_center_peak"], 1.0, 1e-9)
    approx(d["2x4"]["torus_corner_over_center_peak"], 1.0, 1e-9)
    approx(d["3x3"]["torus/corner"]["peak_wire_vol"], 3.0, 1e-9)  # was 5.0


def test_die_ordering_spread_flip_and_role_swap():
    """THE RECORDED FLIP (pre-registered as the two-handed possibility):
    ring WIDENS the 48-die ordering spread (6.55x -> 12.26x) instead of
    narrowing it -- a 1D cycle's far end is longer than a 2D mesh's; the
    honest company sentence is that ring makes the ordering MORE critical
    while being exactly optimal for its native in-order flow (sequential
    rows = 1.000), and it is TORUS that relaxes ordering criticality
    (3.57x). The mesh gate (stored avg_hops reproduced) is asserted in
    the generating script."""
    d = _readout()["die_level"]
    sp = d["spread_worst_over_best"]
    approx(sp["mesh_count_mean"], 6.553, 1e-3)
    approx(sp["ring_count_mean"], 12.255, 1e-3)
    approx(sp["torus_count_mean"], 3.574, 1e-3)
    o = d["orderings"]
    approx(o["snake"]["mesh"]["count_mean"], 1.0, 1e-9)
    approx(o["sequential rows"]["ring"]["count_mean"], 1.0, 1e-9)
    approx(o["snake"]["ring"]["count_mean"], 1.745, 1e-3)
    approx(o["far pairs (adversarial)"]["torus"]["count_mean"], 3.574, 1e-3)
    # uniform fold cancels in ratios: phys spread == count spread
    approx(sp["ring_phys_mean"], sp["ring_count_mean"], 1e-9)
