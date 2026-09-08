"""Group 44 -- A6 (C59): per-scheme ENERGY wire models (O8 closed).

Pins the energy_hops contract: identity for point-to-point schemes (the
day-2 gate -- nothing shipped moves), the serpentine bus line, the
h-tree physical table (== the registered literals, per the ruling), the
re-run tradeoff readout (tie broken, the new physically-correct bus
tie, span ~1.06x, latency side untouched), and the A5-linkage coverage
(a bus variant at the CROSSBAR level charges the full local line
through the same flow machinery the overlay column reads)."""
import dataclasses
import json
import os

from _util import approx

from scripts import anchors, fabric, interconnect as ic, placement

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)

F24 = fabric.default()
F33 = fabric.from_yaml(os.path.join(WS, "models", "fabric", "mlx300_3x3.yaml"))


def _tradeoff():
    return json.load(open(os.path.join(WS, "analysis", "placement_tradeoff.json")))


def test_point_to_point_schemes_are_identity():
    """The day-2 gate in miniature: for star and mesh the driven wire IS the
    route, so energy_hops == hops everywhere -- every shipped account is
    C59-invariant by construction."""
    for fab in (F24, F33):
        pl = placement.sequential_fill(fab)
        for lvl in ("macro", "core", "crossbar"):
            s = ic.build(fab, lvl, pl)
            for i in range(len(s.slots)):
                approx(s.energy_hops(ic.HUB, i), s.hops(ic.HUB, i), 1e-12)
            approx(s.mean_energy_hops(), s.mean_hops(), 1e-12)
    slots = placement.sequential_fill(F24).slots["macro"]
    m = ic.Mesh(slots, {"routing": "xy", "hub": "center"})
    for i in range(8):
        approx(m.energy_hops(ic.HUB, i), m.hops(ic.HUB, i), 1e-12)


def test_bus_serpentine_line_is_endpoint_and_driver_blind():
    """The ruling: line = (N-1) slot pitches, charged whole to every
    transfer; endpoints and driver position are energy-irrelevant (both
    stay latency-relevant: hops() still reads Manhattan-to-driver)."""
    slots = placement.sequential_fill(F24).slots["macro"]
    for driver in ("center", "corner"):
        b = ic.Bus(slots, {"driver": driver})
        vals = {b.energy_hops(a, x) for a in range(8) for x in range(8) if a != x}
        vals |= {b.energy_hops(ic.HUB, i) for i in range(8)}
        assert vals == {7.0}                      # N-1, nothing else
        approx(b.mean_energy_hops(), 7.0, 1e-12)
    b_c = ic.Bus(slots, {"driver": "center"})
    b_k = ic.Bus(slots, {"driver": "corner"})
    assert b_c.hops(ic.HUB, 0) != b_k.hops(ic.HUB, 0)   # latency still differs


def test_bus_star_component_ratio_both_grids():
    """The pre-registered component-tier ratio, both-handed: 7/1.3125 =
    5.33x on the 3x3 host where the 1.3125 tie was pinned (the pre-reg's
    anchor), and 7/1.5 = 4.67x on the 2x4 default (the pre-reg conflated
    the grids -- recorded, not adjusted)."""
    s33 = placement.sequential_fill(F33).slots["macro"]
    s24 = placement.sequential_fill(F24).slots["macro"]
    approx(ic.Bus(s33, {"driver": "center"}).mean_energy_hops()
           / ic.Star(s33).mean_energy_hops(), 7.0 / 1.3125, 1e-12)
    approx(ic.Bus(s24, {"driver": "center"}).mean_energy_hops()
           / ic.Star(s24).mean_energy_hops(), 7.0 / 1.5, 1e-12)


def test_htree_physical_table_matches_registry():
    """The ruling: the geometry rule's output for the shipped lambda-1 host
    is registered as LITERALS; latency hops keep the flat default."""
    slots = placement.sequential_fill(F24).slots["macro"]
    t = ic.HTree(slots, {"branching": 4})
    assert tuple(t.physical_level_length()) == anchors.HTREE_MACRO_LEVEL_LENGTH_SLOTS
    assert anchors.HTREE_MACRO_LEVEL_LENGTH_SLOTS == (2.0, 1.0)
    approx(t.energy_hops(ic.HUB, 0), 3.0, 1e-12)    # physical root->leaf
    approx(t.hops(ic.HUB, 0), 2.0, 1e-12)           # flat latency default kept
    assert t.energy_hops(0, 1) < t.energy_hops(0, 7)  # deeper LCA, longer wire


def test_tradeoff_tie_broken_and_new_bus_tie():
    """Day-3 readout against the pre-registration: the star<->bus artifact
    tie is DEAD; the new physically-correct tie (bus-centre == bus-corner)
    is alive; the span went 1.007x -> ~1.06x; the latency side did not
    move; star/mesh rows are C59-invariant by construction (their energy
    path reads mean_energy_hops == mean_hops)."""
    d = _tradeoff()
    rows = {r["key"]: r for r in d["variants"]}
    star, bus_c, bus_k = rows["star/2x4"], rows["bus/centre"], rows["bus/corner"]
    assert bus_c["energy_J"] > star["energy_J"] * 1.04          # tie broken
    approx(bus_c["energy_J"], bus_k["energy_J"], 1e-12)         # the new tie
    approx(bus_c["energy_J"], 2.858e-3, 2e-3)
    approx(star["energy_J"], 2.7113e-3, 2e-3)
    span = max(r["energy_J"] for r in d["variants"]) / min(
        r["energy_J"] for r in d["variants"])
    assert 1.04 < span < 1.08                                    # ~1.06x
    lats = {round(r["latency_s"] * 1e3, 2) for r in d["variants"]}
    assert len(lats) == 1                                        # latency untouched
    approx(rows["htree/2x4"]["energy_J"], 2.7513e-3, 2e-3)       # root-weighted


def test_crossbar_level_bus_charges_full_local_line():
    """The A5-linkage coverage (user's supplement 2): a bus variant at the
    CROSSBAR level flows through the same build_flows distances the C58
    overlay column reads -- each in-core transfer charges the full local
    line (8 slots -> 7 slot pitches), not the distance to the hub."""
    import shutil
    import tempfile

    import scripts.crossbar_comm as cc
    levels = [dataclasses.replace(
        lv, link=dataclasses.replace(lv.link, topology="bus", params={}))
        if lv.name == "crossbar" else lv for lv in F24.levels]
    fv = dataclasses.replace(F24, name="xbar-bus", levels=levels).validate()
    td = tempfile.mkdtemp()
    try:
        for src, dst in (("ffn1_prefill_map.txt", "timeloop-mapper.map.txt"),
                         ("ffn1_prefill_stats.txt", "timeloop-mapper.stats.txt")):
            shutil.copy(os.path.join(HERE, "fixtures", src),
                        os.path.join(td, dst))
        flows, _, _, _ = cc.build_flows(td, fabric=fv, verbose=False)
    finally:
        shutil.rmtree(td, ignore_errors=True)
    xb = [f for f in flows if f["level"] == "core<->crossbar"]
    assert xb and all(f["distance"] == 7.0 for f in xb)   # pitch 1 x (N-1)
    core = [f for f in flows if f["level"] == "macro<->core"]
    assert {f["distance"] for f in core} != {7.0}         # star level untouched
