"""Group 48 -- the O19 batch weaves (C63): switch (item 2), cmesh (item 3).

Switch pins: the contract (constant hops, port resources, C59/C60
identities), the two pre-registered short tests -- placement-irrelevance
measured on permuted seatings, and the star-degeneration identity AS
REFINED at test-writing time (before any published sentence): it holds
for NODE-TO-NODE flows (the weave's real habitat, die-level hand-offs);
for HUB-ROOTED flows the switch honestly funnels through its single hub
port while star is the N-port idealization -- both behaviors pinned.
Plus the readout file's expectations."""
import json
import os
import random

from _util import approx

import scripts.crossbar_comm as cc
from scripts import anchors, fabric, interconnect as ic, placement

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
F48 = fabric.from_yaml(os.path.join(WS, "models", "fabric",
                                    "mlx300_multidie48.yaml"))


def _chain_flows(asg):
    return [{"level": "die<->die", "level_name": "die", "nodes": (a, b),
             "src": f"die{a}", "dst": f"die{b}", "volume": 100.0,
             "width": 1.0, "distance": 0.0}
            for a, b in zip(asg, asg[1:])]


def _die_fab(topology, params):
    import dataclasses
    levels = [dataclasses.replace(
        lv, link=dataclasses.replace(lv.link, topology=topology,
                                     params=params,
                                     bandwidth_words_per_cycle=1024.0))
        if lv.name == "die" else lv for lv in F48.levels]
    return dataclasses.replace(F48, name=f"t-{topology}",
                               levels=levels).validate()


# ------------------------------------------------------------ switch (item 2)
def test_switch_contract():
    s = ic.Switch([(i, 0) for i in range(8)], {})
    vals = {s.hops(a, b) for a in range(8) for b in range(8) if a != b}
    vals |= {s.hops(ic.HUB, i) for i in range(8)}
    assert vals == {1.0}                        # the declared constant
    assert s.hops(3, 3) == 0.0 and s.path(3, 3) == []
    assert len(s.resources()) == 9              # N ports + the hub port
    assert ic.Switch.DUPLEX
    approx(s.energy_hops(0, 5), s.hops(0, 5), 1e-12)   # C59 identity
    approx(s.router_hops(0, 5), s.hops(0, 5), 1e-12)   # C60 identity
    t = ic.Switch([(i, 0) for i in range(8)], {"hops": 2.5})
    approx(t.hops(0, 7), 2.5, 1e-12)            # the constant is a param


def test_switch_placement_irrelevance_is_measured():
    """The topology short test: ANY seating permutation gives the identical
    occupancy readout -- per-resource load multisets equal, bottleneck
    equal."""
    fab = _die_fab("switch", {})
    pl = placement.sequential_fill(fab)
    base = list(range(48))
    rng = random.Random(7)
    for _ in range(3):
        perm = base[:]
        rng.shuffle(perm)
        o1 = cc.link_occupancy(_chain_flows(base), fab, anchors.CYCLE_S, pl)
        o2 = cc.link_occupancy(_chain_flows(perm), fab, anchors.CYCLE_S, pl)
        assert (sorted(e["volume"] for e in o1["per_link"])
                == sorted(e["volume"] for e in o2["per_link"]))
        approx(o1["bottleneck"]["volume"], o2["bottleneck"]["volume"], 1e-12)


def test_switch_star_degeneration_node_to_node():
    """The refined identity: on NODE-TO-NODE flows (die hand-offs, the
    switch's habitat) switch and star produce the same load multiset and
    bottleneck -- star is the idealized switch, per its own docstring."""
    fsw, fst = _die_fab("switch", {}), _die_fab("star", {})
    pl_sw = placement.sequential_fill(fsw)
    pl_st = placement.sequential_fill(fst)
    asg = list(range(48))
    osw = cc.link_occupancy(_chain_flows(asg), fsw, anchors.CYCLE_S, pl_sw)
    ost = cc.link_occupancy(_chain_flows(asg), fst, anchors.CYCLE_S, pl_st)
    assert (sorted(e["volume"] for e in osw["per_link"])
            == sorted(e["volume"] for e in ost["per_link"]))
    approx(osw["bottleneck"]["volume"], ost["bottleneck"]["volume"], 1e-12)


def test_switch_hub_port_funnels_honestly():
    """The refinement's other face (recorded BEFORE any published sentence):
    for HUB-ROOTED flows the switch has ONE hub port, so all hub traffic
    funnels through it (8 x 100 = 800), while star's N private hub links
    keep 100 each -- star is the N-port idealization, not the same
    device."""
    flows = [{"level": "die<->die", "level_name": "die", "node": n,
              "src": "hub", "dst": f"die{n}", "volume": 100.0,
              "down": 100.0, "up": 0.0, "distance": 0.0} for n in range(8)]
    fsw, fst = _die_fab("switch", {}), _die_fab("star", {})
    osw = cc.link_occupancy(flows, fsw, anchors.CYCLE_S,
                            placement.sequential_fill(fsw))
    ost = cc.link_occupancy(flows, fst, anchors.CYCLE_S,
                            placement.sequential_fill(fst))
    approx(osw["bottleneck"]["volume"], 800.0, 1e-12)   # the hub-port funnel
    approx(ost["bottleneck"]["volume"], 100.0, 1e-12)   # private links


def test_switch_readout_expectations_landed():
    d = json.load(open(os.path.join(WS, "analysis", "switch_weave.json")))
    sp = d["spread_worst_over_best"]
    assert sp["switch_count_mean"] == 1.0 and sp["switch_phys_mean"] == 1.0
    approx(sp["mesh_count_mean"], 6.553, 1e-3)          # the control arms
    approx(sp["ring_count_mean"], 12.255, 1e-3)
    approx(sp["torus_count_mean"], 3.574, 1e-3)
    assert d["expectations"]["switch_spread_exactly_1"]
    assert d["expectations"]["busiest_port_identical_across_orderings"]
    assert "N^2" in d["identity_note"]                  # the declared price


# ------------------------------------------------------------ cmesh (item 3)
def _macro_slots():
    return placement.sequential_fill(fabric.default()).slots["macro"]


def test_cmesh_k1_degenerates_to_mesh_exactly():
    """The pinned degeneration: [1,1] gives mesh hops for every pair
    including the HUB, and the identical shared-load structure (no access
    links, no ports)."""
    slots = _macro_slots()
    m = ic.Mesh(slots, {"routing": "xy", "hub": "center"})
    c = ic.CMesh(slots, {"routing": "xy", "hub": "center",
                         "concentration": [1, 1]})
    for a in list(range(8)) + [ic.HUB]:
        for b in range(8):
            approx(c.hops(a, b), m.hops(a, b), 1e-12)
    assert not any(":acc" in r or ":rport" in r for r in c.resources())


def test_cmesh_hand_distances_and_port_carrier():
    """Hand case [2,2] on the 2x4 macro grid (routers at tile centers):
    node0 (0,0) -> node7 (1,3): access 1.0 + grid 2.0 + access 1.0 = 4.0.
    The concentration carrier is the shared router LOCAL PORT (the C63-c
    amendment, filed before readouts): k tile nodes share it; the HUB is
    router-resident and attaches to no port."""
    slots = _macro_slots()
    c = ic.CMesh(slots, {"routing": "xy", "hub": "center",
                         "concentration": [2, 2]})
    approx(c.hops(0, 7), 4.0, 1e-12)
    pd = c.path_directed(ic.HUB, 7)
    assert ("cmesh:rport(0, 1)", "rx") in pd          # dest tile port shared
    assert not any("accHUB" in r or "rportHUB" in r for r, _ in pd)


def test_cmesh_concentration_curve():
    """The amended pre-registration, landed: port load = k EXACTLY
    (monotone by construction); the overall bottleneck holds at the mesh
    grid funnel 4.0 until k* = 4 (the tie), then the router funnel takes
    over (8.0 at k = 8, the single-router extreme) -- concentration on
    this grid is free up to k = 4 and binding beyond."""
    d = json.load(open(os.path.join(WS, "analysis", "cmesh_weave.json")))
    r = d["rows"]
    assert d["expectations"]["port_equals_k_exactly"]
    assert d["expectations"]["port_monotone"]
    assert d["expectations"]["k1_degenerates_to_mesh_busiest_4"]
    assert [r[k]["busiest_overall"] for k in ("1", "2", "4", "8")] \
        == [4.0, 4.0, 4.0, 8.0]
    assert [r[k]["busiest_port"] for k in ("1", "2", "4", "8")] \
        == [0.0, 2.0, 4.0, 8.0]
    assert d["crossover_k_star"] == 4
    assert "rport" in r["8"]["bottleneck_resource"]   # the funnel binds


# ---------------------------------------------------------- express (optional)
def test_express_contract_and_degeneration():
    """Locked family: uniform station-free; skip >= extent -> EXACT mesh
    (hops AND count); physical hops == Manhattan == mesh pair-by-pair
    (express never saves wire length); the count/length split's third
    appearance -- one express traversal counts 1 over s slots of wire."""
    F33 = fabric.from_yaml(os.path.join(WS, "models", "fabric",
                                        "mlx300_3x3.yaml"))
    slots = placement.sequential_fill(F33).slots["macro"]
    m = ic.Mesh(slots, {"routing": "xy", "hub": "corner"})
    e9 = ic.Express(slots, {"routing": "xy", "hub": "corner", "skip": 9})
    e2 = ic.Express(slots, {"routing": "xy", "hub": "corner", "skip": 2})
    for a in list(range(8)) + [ic.HUB]:
        for b in range(8):
            approx(e9.hops(a, b), m.hops(a, b), 1e-12)
            approx(e9.router_hops(a, b), m.hops(a, b), 1e-12)
            approx(e2.hops(a, b), m.hops(a, b), 1e-12)   # phys == Manhattan
    i00, i20 = slots.index((0.0, 0.0)), slots.index((2.0, 0.0))
    approx(e2.router_hops(i00, i20), 1.0, 1e-12)         # one crossing
    approx(e2.hops(i00, i20), 2.0, 1e-12)                # two slots of wire
    assert e2.path(i00, i20) == ["express:xp(0, 0)-(2, 0)"]


def test_express_in_packet_guard():
    """Count != length -> per-router packet constants must not read hops:
    express joins torus/ring in the fabric validation guard."""
    import dataclasses
    levels = []
    for lv in fabric.default().levels:
        if lv.name == "macro":
            lv = dataclasses.replace(lv, link=dataclasses.replace(
                lv.link, topology="express",
                params={"routing": "xy", "hub": "center", "skip": 2},
                packet_payload_bytes=8.0))
        levels.append(lv)
    bad = dataclasses.replace(fabric.default(), name="pkt-xp", levels=levels)
    try:
        bad.validate()
    except ValueError as e:
        assert "router_hops" in str(e)
    else:
        raise AssertionError("packet params on express validated")


def test_express_price_curve_findings():
    """The readouts, both hands booked. 3x3: the pre-written risk landed as
    an exact TIE -- express s=2 and torus both zero the lever (1.000,
    busiest 3/3) at the same 2.0x wire. 6x8, THE UNREGISTERED FINDING:
    express s=2 makes the hub LEVER WORSE (2.000 vs mesh 1.667) while
    improving both absolutes (24->16, 40->32) -- a ratio can degrade under
    uniform-ish relief that helps the centre more; the lever is
    non-monotone in s (2.0 / 1.5 / 1.0); torus DOMINATES every express
    variant on this host (lever 1.000 at 2.0x wire <= every express
    price). Express's real value is the ABSOLUTE decompression (centre
    busiest 16 < mesh 24, the only weave below mesh)."""
    d = json.load(open(os.path.join(WS, "analysis", "express_weave.json")))
    h3, h6 = d["hosts"]["3x3_macro"], d["hosts"]["6x8_die"]
    approx(h3["mesh"]["lever"], 5.0 / 3.0, 1e-9)         # the pinned 5/3
    for k in ("express_s2", "torus"):
        assert h3[k]["lever"] == 1.0 and h3[k]["wire_x"] == 2.0
        approx(h3[k]["busiest_corner"], 3.0, 1e-12)      # the exact tie
    approx(h6["express_s2"]["lever"], 2.0, 1e-9)         # WORSE than mesh
    approx(h6["mesh"]["lever"], 5.0 / 3.0, 1e-9)
    assert h6["express_s2"]["busiest_center"] == 16.0    # yet absolutes drop
    assert h6["express_s2"]["busiest_corner"] == 32.0
    levers = [h6[f"express_s{s}"]["lever"] for s in (2, 3, 4)]
    assert levers == [2.0, 1.5, 1.0]                     # non-monotone path
    assert h6["torus"]["lever"] == 1.0
    assert all(h6["torus"]["wire_x"] <= h6[f"express_s{s}"]["wire_x"]
               for s in (2, 3, 4))                       # torus dominates


# ------------------------------------------------- hier_wide (conditional A)
def test_hier_wide_degeneration_chain_and_lanes():
    """W=1 == cmesh exactly (paths modulo the name prefix, hops, counts);
    W=1 + [1,1] == mesh on hops; lanes: backbone segment lane = source
    node % W, HUB-sourced lane 0."""
    slots = _macro_slots()
    cm = ic.CMesh(slots, {"routing": "xy", "hub": "center",
                          "concentration": [2, 2]})
    h1 = ic.HierWide(slots, {"routing": "xy", "hub": "center",
                             "concentration": [2, 2], "channels": 1})
    hm = ic.HierWide(slots, {"routing": "xy", "hub": "center",
                             "concentration": [1, 1], "channels": 1})
    m = ic.Mesh(slots, {"routing": "xy", "hub": "center"})
    strip = lambda pd: [(r.split(":", 1)[1], t) for r, t in pd]
    for a in list(range(8)) + [ic.HUB]:
        for b in range(8):
            assert strip(h1.path_directed(a, b)) == strip(cm.path_directed(a, b))
            approx(h1.hops(a, b), cm.hops(a, b), 1e-12)
            approx(h1.router_hops(a, b), cm.router_hops(a, b), 1e-12)
            approx(hm.hops(a, b), m.hops(a, b), 1e-12)
    h2 = ic.HierWide(slots, {"routing": "xy", "hub": "center",
                             "concentration": [2, 2], "channels": 2})
    assert any(".c1" in r for r, _ in h2.path_directed(1, 7))   # src 1 -> lane 1
    assert any(".c0" in r for r, _ in h2.path_directed(0, 7))   # src 0 -> lane 0
    assert not any(".c1" in r for r, _ in h2.path_directed(ic.HUB, 7))


def test_cmesh_count_length_addendum_and_guard():
    """The C63-e addendum: cmesh's backbone step crosses ONE router over a
    tile pitch of wire -- router_hops now counts crossings (caught at
    hier_wide's contract time), and the packet guard lists cmesh AND
    hier_wide beside torus/ring/express."""
    import dataclasses
    slots = _macro_slots()
    cm = ic.CMesh(slots, {"routing": "xy", "hub": "center",
                          "concentration": [2, 2]})
    approx(cm.router_hops(0, 7), 1.0, 1e-12)     # one router crossing
    approx(cm.hops(0, 7), 4.0, 1e-12)            # four slots of wire
    for topo, params in (("cmesh", {"routing": "xy", "hub": "center",
                                    "concentration": [2, 2]}),
                         ("hier_wide", {"routing": "xy", "hub": "center",
                                        "concentration": [2, 2],
                                        "channels": 2})):
        levels = []
        for lv in fabric.default().levels:
            if lv.name == "macro":
                lv = dataclasses.replace(lv, link=dataclasses.replace(
                    lv.link, topology=topo, params=params,
                    packet_payload_bytes=8.0))
            levels.append(lv)
        bad = dataclasses.replace(fabric.default(), name=f"pkt-{topo}",
                                  levels=levels)
        try:
            bad.validate()
        except ValueError as e:
            assert "router_hops" in str(e)
        else:
            raise AssertionError(f"packet params on {topo} validated")


def test_hier_wide_fidelity_readout():
    """The third outcome, neither pre-written hand: every variant ties the
    poured-mesh 4.000x, but the binding resource MIGRATES to the local
    gateway port at every W -- the backbone's width cannot be consumed on
    this host (W = 1/2/4 identical), so the poured reading was right
    numerically and wrong structurally. That sentence is the fidelity
    upgrade's deliverable."""
    d = json.load(open(os.path.join(WS, "analysis", "hier_wide.json")))
    r = d["rows"]
    approx(r["mesh (poured)"]["x_vs_star"], 4.0, 1e-9)
    for W in (1, 2, 4):
        row = r[f"hier_wide W={W}"]
        approx(row["x_vs_star"], 4.0, 1e-9)      # the numeric tie
        assert "rport" in row["bottleneck"]      # the migrated bottleneck
    assert "seg" in r["mesh (poured)"]["bottleneck"]
    assert "MIGRATED BOTTLENECK" in d["verdict"]
    assert "wrong structurally" in d["verdict"]


# --------------------------------------------- routing params (conditional B)
def test_routing_defaults_are_byte_neutral():
    """The neutrality gate in miniature: default reply=retrace and
    routing=xy reproduce the pre-C63-f paths verbatim."""
    slots = _macro_slots()
    m0 = ic.Mesh(slots, {"routing": "xy", "hub": "center"})
    assert m0.reply == "retrace"
    m1 = ic.Mesh(slots, {"routing": "xy", "hub": "center",
                         "reply": "retrace"})
    for a in list(range(8)) + [ic.HUB]:
        for b in list(range(8)) + [ic.HUB]:
            if a == b:
                continue
            assert m0.path_directed(a, b) == m1.path_directed(a, b)
    # THE STRONGER IDENTITY, caught by this very pin's first draft: for
    # hub flows, retrace-of-XY IS the YX path (a single-bend dimension-
    # order route walked backwards runs y-then-x) -- the reply knob is
    # PATH-IDENTICAL on its whole hub-flow domain, not merely load-equal.
    my = ic.Mesh(slots, {"routing": "xy", "hub": "center", "reply": "yx"})
    for i in range(8):
        assert my.path_directed(i, ic.HUB) == m0.path_directed(i, ic.HUB)


def test_routing_knob_findings():
    """Item B's honest close, pinned: (1) THE SINK-FUNNEL INVARIANT -- the
    reply knob is provably inert in the busiest-wire account (hub flows
    are conservation-fixed at the sink's incident segments; non-hub flows
    never consult it): every reply variant ties on every pattern. (2) the
    o1turn PARITY stand-in never beats plain XY on any tested pattern
    (all-pairs 12 vs 8 / 9 vs 6; mirror 4 vs 2 / 2 vs 1) -- the fractional
    50/50 oracle is outside the resource interface; the knob ships as a
    condition-enumeration arm with this warning, not as an optimization."""
    d = json.load(open(os.path.join(WS, "analysis", "routing_params.json")))
    r = d["rows"]
    for h in ("2x4", "3x3"):
        for pat in ("up0.5", "up2.0", "allpairs", "mirror"):
            for base in ("xy", "o1turn"):
                assert (r[f"{h}|{pat}|{base} + retrace"]["busiest"]
                        == r[f"{h}|{pat}|{base} + yx reply"]["busiest"])
    assert r["2x4|allpairs|o1turn + retrace"]["busiest"] == 12.0
    assert r["2x4|allpairs|xy + retrace"]["busiest"] == 8.0
    assert r["2x4|mirror|o1turn + retrace"]["busiest"] == 4.0
    assert r["2x4|mirror|xy + retrace"]["busiest"] == 2.0
    assert d["checks"]["2x4"]["down_bound_unmoved_at_up0.5"]
    assert not d["checks"]["2x4"]["relief_at_up2.0"]       # the refutation
    assert "conservation" in d["invariant"]
