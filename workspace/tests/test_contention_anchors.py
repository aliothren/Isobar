"""Group 14 -- anchors for the published contention-impact numbers.

The three analysis scripts (analyze_contention_impact / placement_tradeoff /
contention_system) publish tables built from ONE mapper run re-scored
analytically. Everything except the mapper run itself is deterministic algebra
over the frozen ffn1 constants, so the whole scheme x layout table is pinned
here without a mapper. The system-level (whole-stack) multipliers additionally
need the other five ops' compute/write terms and are covered by the slow tier.

Anchors (ffn1 prefill S=512, bandwidth 16,384 words/cycle):
  busiest-wire multipliers   star 1 / mesh-centre 3 / mesh-2x4 4 / h-tree 4 /
                             mesh-corner 5 / bus 8
  op-latency multipliers     1.75x .. 13.96x, ratio bus:star = 8.00 exactly
  the energy-tie identity    star, bus-centre, and every scheme that routes
                             point-to-point from the same centroid share
                             mean_hops 1.3125 -- why the energy account cannot
                             separate them while their latency differs 8x.
"""
import dataclasses

from _util import approx

import scripts.crossbar_comm as cc
from scripts import fabric, interconnect as ic, placement

# The mechanism anchors below are pinned on the 3x3 grid (one empty slot) --
# the default fabric up to C27; since C27 the default is the fill-exact 2x4,
# kept in models/fabric/mlx300_3x3.yaml as the comparison variant. Rows with
# mesh=(2, 4) override the grid explicitly, so they read the same either way.
F = fabric.from_yaml("/home/workspace/models/fabric/mlx300_3x3.yaml")
# frozen ffn1 constants (same provenance as test_contention_scope)
VOL = 51_249_152.0            # one macro edge, v1 structured traffic
from scripts import anchors as an
CYC = an.CYCLE_S              # device cycle, CiMLoop-calibrated macro model (one source: the registry)
COMPUTE_S = 2.59584e-3        # ffn1 prefill compute latency
BW = 16_384.0                 # the tables' operating point

SCHEMES = [("star", {}, None, 1),
           ("mesh", {"routing": "xy", "hub": "corner"}, (2, 4), 4),
           ("mesh", {"routing": "xy", "hub": "center"}, None, 3),
           ("mesh", {"routing": "xy", "hub": "center"}, (2, 4), 4),
           ("h_tree", {"branching": 4}, None, 4),
           ("mesh", {"routing": "xy", "hub": "corner"}, None, 5),
           ("bus", {"driver": "center"}, None, 8)]


def _with(topology, params=None, bw=BW, mesh=None):
    levels = []
    for lv in F.levels:
        if lv.name == "macro":
            link = dataclasses.replace(lv.link, topology=topology,
                                       params=params or {},
                                       bandwidth_words_per_cycle=bw)
            lv = dataclasses.replace(lv, link=link,
                                     mesh=mesh if mesh else lv.mesh)
        levels.append(lv)
    return dataclasses.replace(F, name=f"t-{topology}", levels=levels).validate()


def _flows(n=8):
    return [{"level": "glb<->macro", "level_name": "macro", "node": m,
             "src": "glb", "dst": f"macro{m}", "volume": VOL,
             "distance": 0.0} for m in range(n)]


def test_busiest_wire_table():
    """The one integer per variant that the whole scheme table reduces to."""
    for topo, params, mesh, want in SCHEMES:
        fab = _with(topo, params, mesh=mesh)
        occ = cc.link_occupancy(_flows(), fab, CYC,
                                placement.sequential_fill(fab))
        got = occ["bottleneck"]["volume"] / VOL
        assert abs(got - want) < 1e-12, \
            f"{topo} {params} {mesh or ''}: busiest wire {got} != {want}"


def test_op_latency_multipliers():
    """The published table: 1.75x (star) .. 13.96x (bus), exact ratio 8.00."""
    lat = {}
    for topo, params, mesh, want in SCHEMES:
        fab = _with(topo, params, mesh=mesh)
        ser = cc.link_occupancy(_flows(), fab, CYC,
                                placement.sequential_fill(fab)
                                )["serialization_s"]
        lat[(topo, str(params), str(mesh))] = max(COMPUTE_S, ser)
        approx(ser, want * VOL / BW * CYC, 1e-9)
    star = lat[("star", "{}", "None")]
    bus = lat[("bus", str({"driver": "center"}), "None")]
    approx(bus / star, 8.0, 1e-9)                    # scheme alone: 8.00x
    approx(star / COMPUTE_S, 1.7455, 1e-3)           # 1.75x vs stall-free
    approx(bus / COMPUTE_S, 13.9636, 1e-3)           # 13.96x vs stall-free


def test_layout_lever_depends_on_the_grid_shape():
    """On the fill-exact 2x4 the hub position does NOT move the peak (4x both
    ways -- the elongated grid funnels a full column either way). The layout
    lever on the peak is a property of the squarer grid; the 3x3 comparison
    below shows it (3V -> 5V = 1.67x)."""
    def peak24(params):
        fab = _with("mesh", params, mesh=(2, 4))
        return cc.link_occupancy(_flows(), fab, CYC,
                                 placement.sequential_fill(fab)
                                 )["bottleneck"]["volume"] / VOL
    assert peak24({"routing": "xy", "hub": "center"}) ==         peak24({"routing": "xy", "hub": "corner"}) == 4.0


def test_layout_alone_costs_1_67x_under_mesh_3x3():
    """Centre -> corner glb, identical mesh NoC, 3x3 grid: 5V/3V = 1.67x."""
    def ser(params):
        fab = _with("mesh", params)
        return cc.link_occupancy(_flows(), fab, CYC,
                                 placement.sequential_fill(fab)
                                 )["serialization_s"]
    centre = ser({"routing": "xy", "hub": "center"})
    corner = ser({"routing": "xy", "hub": "corner"})
    approx(corner / centre, 5.0 / 3.0, 1e-12)


def test_the_energy_tie_identity():
    """Why the energy account cannot see contention: star and bus-centre share
    mean_hops 1.3125 (so identical re-priced energy) while their busiest wire
    differs 8x. Same for the corner pair at 1.75."""
    slots = placement.sequential_fill(F).slots["macro"]
    star = ic.Star(slots)
    bus_c = ic.Bus(slots, {"driver": "center"})
    bus_k = ic.Bus(slots, {"driver": "corner"})
    mesh_k = ic.Mesh(slots, {"routing": "xy", "hub": "corner"})
    approx(star.mean_hops(), 1.3125, 1e-12)
    approx(bus_c.mean_hops(), 1.3125, 1e-12)         # the 8.00x-latency tie
    approx(bus_k.mean_hops(), 1.75, 1e-12)
    approx(mesh_k.mean_hops(), 1.75, 1e-12)          # the 1.60x-latency tie
    # and the latency side of the same pairs, at the operating point:
    for topo, params, want in (("star", {}, 1), ("bus", {"driver": "center"}, 8)):
        fab = _with(topo, params)
        occ = cc.link_occupancy(_flows(), fab, CYC,
                                placement.sequential_fill(fab))
        approx(occ["bottleneck"]["volume"] / VOL, float(want), 1e-12)


def test_bus_serializes_everything_regardless_of_driver():
    """One shared medium: the level's whole traffic on one resource, and the
    driver position moves energy (mean_hops) but never contention."""
    for driver in ("center", "corner", "node:3"):
        fab = _with("bus", {"driver": driver})
        occ = cc.link_occupancy(_flows(), fab, CYC,
                                placement.sequential_fill(fab))
        assert len(occ["per_link"]) == 1
        approx(occ["bottleneck"]["volume"], 8 * VOL, 1e-9)


def test_partial_occupancy_couples_layout_to_active_slots():
    """The decode counter-example's mechanism: with only SOME nodes active, a
    corner hub can beat the centre hub -- flows from nodes co-located with (or
    adjacent to) the hub ride fewer shared segments. Pinned so the 'corner is
    always worse' shortcut cannot creep into docs."""
    active = [f for f in _flows() if f["node"] in (0, 1, 3)]  # top-left corner
    def peak(params):
        fab = _with("mesh", params)
        occ = cc.link_occupancy(active, fab, CYC,
                                placement.sequential_fill(fab))
        return occ["bottleneck"]["volume"] / VOL
    # corner hub sits at (0,0): node 0 rides nothing, 1 and 3 one segment each
    assert peak({"routing": "xy", "hub": "corner"}) < \
        peak({"routing": "xy", "hub": "center"})


# ------------------------------------------- v3: the physical wire accounting
def _flows_v3():
    """The real ffn1 fixture's edge volumes, both directions kept (in = inputs
    down, out = partial sums up), through the same traffic extraction the
    analysis scripts use -- no synthetic VOL."""
    import os
    from scripts import traffic
    here = os.path.dirname(os.path.abspath(__file__))
    fx = os.path.join(here, "fixtures")
    ts = traffic.extract(fabric=F,
                         mapping_text=open(os.path.join(fx, "ffn1_prefill_map.txt")).read(),
                         stats_text=open(os.path.join(fx, "ffn1_prefill_stats.txt")).read())
    ev = ts.edge_volumes()["macro"]
    return [{"level": "glb<->macro", "level_name": "macro", "node": m,
             "src": "glb", "dst": f"macro{m}", "volume": ev["in"] + ev["out"],
             "down": ev["in"], "up": ev["out"], "distance": 0.0}
            for m in range(8)]


def test_v5_single_op_table():
    """Published single-op readout under the physical wire accounting AND
    value units (C25), ffn1 prefill at 16,384 words/cycle: the busiest wire
    hides behind compute at every scheme (perfect-overlap end 1.00x) and
    the zero-overlap end reads star 1.071x, mesh-centre 1.214x, 2x4 1.286x,
    h-tree 1.286x, mesh-corner 1.357x, bus 1.589x; the serialization ratios
    scheme alone (bus / star) 8.27x and layout alone (corner / centre)
    1.67x. Retired (v3, counter units: 14x inputs, 48x outputs): 3.43 /
    10.29 / 13.71 / 13.71 / 17.14 / 27.68x."""
    want_sum = {("star", "{}", "None"): 1.071,
                ("mesh", "{'routing': 'xy', 'hub': 'center'}", "None"): 1.214,
                ("mesh", "{'routing': 'xy', 'hub': 'center'}", "(2, 4)"): 1.286,
                ("h_tree", "{'branching': 4}", "None"): 1.286,
                ("mesh", "{'routing': 'xy', 'hub': 'corner'}", "None"): 1.357,
                ("bus", "{'driver': 'center'}", "None"): 1.589}
    flows = _flows_v3()
    assert flows[0]["down"] == 65_536 and flows[0]["up"] == 1_048_576   # values, one macro edge
    ser = {}
    for topo, params, mesh, _ in SCHEMES:
        fab = _with(topo, params, mesh=mesh)
        ser[(topo, str(params), str(mesh))] = cc.link_occupancy(
            flows, fab, CYC, placement.sequential_fill(fab))["serialization_s"]
    for k, v in want_sum.items():
        approx(max(COMPUTE_S, ser[k]) / COMPUTE_S, 1.00, 1e-9)
        approx((COMPUTE_S + ser[k]) / COMPUTE_S, v, 5e-3)
    approx(ser[("bus", "{'driver': 'center'}", "None")]
           / ser[("star", "{}", "None")], 8.27, 5e-3)
    approx(ser[("mesh", "{'routing': 'xy', 'hub': 'corner'}", "None")]
           / ser[("mesh", "{'routing': 'xy', 'hub': 'center'}", "None")], 1.67, 5e-3)

def _with_on(base, topology, params=None, bw=BW, mesh=None):
    """`_with` on an explicit base fabric (the default is the 2x4 since C27)."""
    levels = []
    for lv in base.levels:
        if lv.name == "macro":
            link = dataclasses.replace(lv.link, topology=topology,
                                       params=params or {},
                                       bandwidth_words_per_cycle=bw)
            lv = dataclasses.replace(lv, link=link, mesh=mesh if mesh else lv.mesh)
        levels.append(lv)
    return dataclasses.replace(base, name=f"t-{topology}", levels=levels).validate()


def test_v6_single_op_table_on_the_2x4_default():
    """C27: the published single-op readout on the fill-exact 2x4 default,
    ffn1 prefill at 16,384 words/cycle. Perfect-overlap end 1.00x at every
    scheme; zero-overlap end star 1.071x, mesh centre 1.286x, mesh corner
    1.286x, h-tree 1.286x, bus 1.589x; scheme alone (bus / star) 8.27x;
    layout alone (corner / centre) 1.00x -- the 3x3's 1.67x lever does not
    exist on the elongated grid (see test_layout_lever_depends_on_the_grid_shape)."""
    base = fabric.default()
    assert base.level("macro").mesh == (2, 4)
    flows = _flows_v3()
    want_sum = {("star", "{}"): 1.071,
                ("mesh", "{'routing': 'xy', 'hub': 'center'}"): 1.286,
                ("mesh", "{'routing': 'xy', 'hub': 'corner'}"): 1.286,
                ("h_tree", "{'branching': 4}"): 1.286,
                ("bus", "{'driver': 'center'}"): 1.589}
    ser = {}
    for (topo, ps), v in want_sum.items():
        params = eval(ps)
        fab = _with_on(base, topo, params)
        ser[(topo, ps)] = cc.link_occupancy(flows, fab, CYC, placement.sequential_fill(fab))["serialization_s"]
        approx(max(COMPUTE_S, ser[(topo, ps)]) / COMPUTE_S, 1.00, 1e-9)
        approx((COMPUTE_S + ser[(topo, ps)]) / COMPUTE_S, v, 5e-3)
    approx(ser[("bus", "{'driver': 'center'}")] / ser[("star", "{}")], 8.27, 5e-3)
    approx(ser[("mesh", "{'routing': 'xy', 'hub': 'corner'}")]
           / ser[("mesh", "{'routing': 'xy', 'hub': 'center'}")], 1.00, 1e-9)
