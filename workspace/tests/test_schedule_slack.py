"""Group 25 -- what the busiest-wire occupancy IS, and the schedule-slack input (O26 / C29).

For a given routing any schedule -- a compile-time one included -- spends at
least volume / bandwidth on each wire, so the busiest wire's occupancy is the
least serialization any schedule can reach: exact for private links and a
shared bus, a lower bound for a routed grid. The max end of the O7 bracket
is the exact ideal of a scheduled fabric and the optimistic bound of a NoC;
`schedule_slack` (fabric-level platform input, >= 1, default 1.0 = the
bound) expresses a schedule that cannot reach it and multiplies every
occupancy. Pins: the bound identity against explicit schedules on the
frozen ffn1 flows, the scaling and ordering under slack, the default and the
validation, and that every consumer of link_occupancy inherits the factor.
"""
import dataclasses
import glob
import os

from _util import approx

import scripts.crossbar_comm as cc
from scripts import anchors as an, fabric, placement, traffic

HERE = os.path.dirname(os.path.abspath(__file__))
CYC = an.CYCLE_S
BW = 16384.0
ORDER = [("star", {}), ("mesh", {"routing": "xy", "hub": "center"}),
         ("mesh", {"routing": "xy", "hub": "corner"}), ("h_tree", {"branching": 4}),
         ("bus", {"driver": "center"})]


def _fab(topology, params, slack=None):
    base = fabric.default()
    levels = [dataclasses.replace(lv, link=dataclasses.replace(lv.link, topology=topology, params=params,
                                                              bandwidth_words_per_cycle=BW))
              if lv.name == "macro" else lv for lv in base.levels]
    f = dataclasses.replace(base, name=f"t-{topology}", levels=levels)
    if slack is not None:
        f = dataclasses.replace(f, schedule_slack=slack)
    return f.validate()


def _flows(fab):
    ts = traffic.extract(fabric=fab,
                         mapping_text=open(os.path.join(HERE, "fixtures", "ffn1_prefill_map.txt")).read(),
                         stats_text=open(os.path.join(HERE, "fixtures", "ffn1_prefill_stats.txt")).read())
    ev = ts.edge_volumes()["macro"]
    return [{"level": "glb<->macro", "level_name": "macro", "node": m, "src": "glb", "dst": f"macro{m}",
             "volume": ev["in"] + ev["out"], "down": ev["in"], "up": ev["out"], "distance": 0.0}
            for m in range(8)]


def test_default_is_the_bound_in_every_shipped_config():
    for p in sorted(glob.glob("/home/workspace/models/fabric/*.yaml")):
        f = fabric.from_yaml(p)
        approx(f.schedule_slack, 1.0, 1e-12), p
        assert fabric.provenance(f)["schedule_slack"] == 1.0
    approx(fabric.default().schedule_slack, 1.0, 1e-12)


def test_slack_below_one_is_rejected():
    try:
        dataclasses.replace(fabric.default(), schedule_slack=0.5).validate()
    except ValueError as e:
        assert "schedule_slack" in str(e)
    else:
        raise AssertionError("slack < 1 accepted")


def test_the_occupancy_is_the_bound_of_every_explicit_schedule():
    """Three explicit schedules of the same flows on the same routing: the
    fully serial one (every component in turn), a per-wire greedy one (each
    wire streams its own components back to back) and the perfect one; all
    take at least the busiest wire's occupancy, the perfect one exactly it."""
    for topology, params in ORDER:
        fab = _fab(topology, params)
        occ = cc.link_occupancy(_flows(fab), fab, CYC, placement.sequential_fill(fab))
        assert occ["schedule_slack"] == 1.0
        bound = occ["serialization_s"]
        per_wire = {e["resource"]: e["seconds"] for e in occ["per_link"]}
        serial_all = sum(per_wire.values())                     # every component one after another
        greedy = max(per_wire.values())                        # each wire back to back, wires in parallel
        assert serial_all >= bound - 1e-15
        approx(greedy, bound, 1e-12)                           # the perfect schedule IS the bound
        # a bus is one resource: the serial schedule and the bound coincide
        if topology == "bus":
            approx(serial_all, bound, 1e-12)
        # private links: every wire carries one macro; the bound is a single flow's time
        if topology == "star":
            assert len(per_wire) == 16 and max(per_wire.values()) == bound


def test_slack_scales_every_occupancy_and_keeps_the_order():
    base_ser, slack_ser = {}, {}
    for topology, params in ORDER:
        f1, f15 = _fab(topology, params), _fab(topology, params, slack=1.5)
        o1 = cc.link_occupancy(_flows(f1), f1, CYC, placement.sequential_fill(f1))
        o15 = cc.link_occupancy(_flows(f15), f15, CYC, placement.sequential_fill(f15))
        approx(o15["serialization_s"], 1.5 * o1["serialization_s"], 1e-12)
        assert o15["bottleneck"]["resource"] == o1["bottleneck"]["resource"]
        for a, b in zip(o1["per_link"], o15["per_link"]):
            assert a["resource"] == b["resource"] and a["volume"] == b["volume"]
            approx(b["seconds"], 1.5 * a["seconds"], 1e-12)
        # the explicit override wins over the fabric's value
        o_over = cc.link_occupancy(_flows(f15), f15, CYC, placement.sequential_fill(f15), schedule_slack=1.0)
        approx(o_over["serialization_s"], o1["serialization_s"], 1e-12)
        base_ser[topology + str(params)] = o1["serialization_s"]
        slack_ser[topology + str(params)] = o15["serialization_s"]
    order1 = sorted(base_ser, key=base_ser.get)
    order15 = sorted(slack_ser, key=slack_ser.get)
    assert order1 == order15


def test_the_d2d_pipeline_inherits_the_factor():
    from scripts import llm_workload as lw
    from scripts.analyze_d2d import MULTI, UCFG, S, assignments, with_link
    base = fabric.from_yaml(MULTI)
    fab = with_link(base, "mesh", {"routing": "xy", "hub": "center"}, 64.0)
    asg = dict(assignments(fab))["far pairs (adversarial)"]
    stage = 0.0238
    d1 = lw.die_pipeline_interval(UCFG, S, "prefill", stage, fabric=fab, assignment=asg, cycle_seconds=CYC)
    fab2 = dataclasses.replace(fab, schedule_slack=2.0).validate()
    d2 = lw.die_pipeline_interval(UCFG, S, "prefill", stage, fabric=fab2, assignment=asg, cycle_seconds=CYC)
    approx(d2["net_s"], 2.0 * d1["net_s"], 1e-12)
    assert d1["net_s"] > 0
