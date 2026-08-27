"""Group 21 -- the external attention unit as an interface (O9).

The unit is a black box (rate, average cost, K/V memory, link); what can go
wrong is the bookkeeping around it: the stream volumes must equal what the
die stops doing, the limits must reduce to the die-side numbers, decode
must scale with the context, and the streams must route to the attach point.
"""
import dataclasses

from _util import approx

from scripts import fabric, interconnect as ic, placement
from scripts import llm_workload as lw
import scripts.crossbar_comm as cc

CFG = lw.GptConfig()
FAB = fabric.from_yaml("/home/workspace/models/fabric/mlx300_multidie48.yaml")
UNIT = FAB.attention_unit


def test_streams_equal_what_the_die_stops_doing():
    """K + V sent to the unit == the cells the two attention ops would have
    programmed on the die (write_cells of qk^t and av); Q == one third of the
    Q/K/V projection's output; the attention output == out_proj's input."""
    for phase, Pq in (("prefill", 512), ("decode", 1)):
        st = lw.offload_streams(CFG, 512, phase)
        ops = {o.name: o for o in lw.block_ops(CFG, 512, phase)}
        assert st["kv_out"] == ops["qk^t"].write_cells + ops["av"].write_cells
        assert st["q_out"] == Pq * ops["qkv_proj"].M // 3
        assert st["attn_back"] == Pq * ops["out_proj"].C


def test_infinite_unit_reduces_to_the_die_side():
    """Rate, K/V bandwidth and link all infinite -> the chain vanishes and the
    end-to-end numbers equal the die-side ones."""
    inf = dataclasses.replace(UNIT, mac_per_second=1e300, kv_words_per_second=1e300,
                              link_bandwidth_words_per_cycle=1e300, call_overhead_s=0.0)
    c = lw.attention_unit_cost(CFG, 512, "prefill", inf)
    assert c["chain_s"] < 1e-12 and c["unit_s"] < 1e-12


def test_decode_chain_grows_linearly_with_context():
    """The K/V read of the whole context dominates decode on the unit: time
    and energy at 2x the context are ~2x (the per-step terms are tiny)."""
    c1 = lw.attention_unit_cost(CFG, 512, "decode", UNIT, context=512)
    c2 = lw.attention_unit_cost(CFG, 512, "decode", UNIT, context=1024)
    assert 1.9 < c2["kv_s"] / c1["kv_s"] < 2.1
    assert 1.9 < c2["kv_J"] / c1["kv_J"] < 2.1
    assert c1["kv_read_words"] == 2 * 512 * CFG.d_model


def test_unit_link_hops_come_from_the_die_placement():
    """Die-side quantities carry the die placement: the offload streams' link
    energy is priced at the mean hop count from the 24 attention dies to the
    attach point under the canonical 48-die snake seating (routed grid, hub
    at the centre: 84 hops / 24 = 3.5), the same number from every entry
    (default, the 48-die fabric, a fabric without dies). Hops move the link
    energy only -- never a latency, never the unit's internal costs."""
    h = lw.unit_link_hops()
    assert h == 3.5
    assert lw.unit_link_hops(FAB, "snake") == h
    assert lw.unit_link_hops(fabric.from_yaml("/home/workspace/models/fabric/mlx300.yaml")) == h
    c1 = lw.attention_unit_cost(CFG, 512, "prefill", UNIT)
    c2 = lw.attention_unit_cost(CFG, 512, "prefill", UNIT, hops=h)
    assert c1["link_hops"] == UNIT.link_reference_hops and c2["link_hops"] == h
    approx(c2["link_J"] / c1["link_J"], h / UNIT.link_reference_hops, 1e-9)
    assert c2["chain_s"] == c1["chain_s"] and c2["unit_s"] == c1["unit_s"]
    assert c2["compute_J"] == c1["compute_J"] and c2["kv_J"] == c1["kv_J"]


def test_shipped_generic_unit_magnitudes():
    """Generic public figures (2 T MAC/s, 1 pJ/MAC, LPDDR4-class 25.6 GB/s,
    GRS-class link): prefill chain 0.527 ms per layer (unit 0.359 + link
    0.168); energy 679 uJ per layer at the reference hop and 732 uJ at the
    placement's 3.5 hops (what the scripts publish); decode chain 0.042 ms
    per layer, K/V-read bound. Pinned so a silent default change shows."""
    cp = lw.attention_unit_cost(CFG, 512, "prefill", UNIT)
    approx(cp["chain_s"], 0.5265e-3, 2e-3)
    approx(cp["unit_s"], 0.3587e-3, 2e-3)
    approx(cp["energy_J"], 679.5e-6, 2e-3)
    approx(lw.attention_unit_cost(CFG, 512, "prefill", UNIT, hops=lw.unit_link_hops())["energy_J"],
           731.9e-6, 2e-3)
    cd = lw.attention_unit_cost(CFG, 512, "decode", UNIT)
    approx(cd["chain_s"], 0.0419e-3, 5e-3)
    assert cd["kv_s"] > 0.9 * cd["chain_s"]


def test_end_to_end_dividend_never_exceeds_die_side():
    """The unit is a pipeline stage: beat = max(die stage B, unit stage), so the
    end-to-end dividend <= the die-side one, with equality only when the unit
    keeps pace (here: 1 unit at 2 T MAC/s keeps pace, 8.6 < 10.6 ms)."""
    from _util import golden
    per = golden("stack_per_op_v4.json")["phases"]["prefill"]["per_op"]["star (private links)"]
    stage_A, stage_B = lw.half_layer_stages(per)
    c = lw.attention_unit_cost(CFG, 512, "prefill", UNIT)
    unit_stage = c["unit_s"] * CFG.n_layers / UNIT.n_units
    assert unit_stage < stage_B                      # the generic unit keeps pace
    assert stage_A / max(stage_B, unit_stage) <= stage_A / stage_B + 1e-12
    slow = dataclasses.replace(UNIT, mac_per_second=0.25e12)
    c2 = lw.attention_unit_cost(CFG, 512, "prefill", slow)
    assert c2["unit_s"] * CFG.n_layers > stage_B      # a 0.25 T unit becomes the bottleneck


def test_streams_route_to_the_attach_point_and_share_die_wires():
    """The offload flows are node-to-node flows die -> HUB / HUB -> die; with
    them on the 48-chain the busiest wire carries more than the hand-offs
    alone, and the attention dies are the even units of the chain."""
    import dataclasses as dc
    from scripts.analyze_d2d import assignments, with_link, UNITS
    fm = with_link(FAB, "mesh", {"routing": "xy", "hub": "center"}, 256.0)
    pl = placement.sequential_fill(fm)
    ucfg = lw.GptConfig(n_layers=UNITS, name="units48")
    snake = dict(assignments(fm))["snake"]
    adies = lw.attention_dies_of_chain(CFG.n_layers, snake)
    assert len(adies) == CFG.n_layers and adies[0] == snake[0]
    d = lw.die_to_die_activation(ucfg, 512, "prefill", fabric=fm, assignment=snake)
    base = cc.link_occupancy(d["flows"], fm, 1.449e-6, pl)["bottleneck"]["volume"]
    flows = d["flows"] + lw.offload_flows(CFG, 512, "prefill", adies)
    occ = cc.link_occupancy(flows, fm, 1.449e-6, pl)
    assert occ["bottleneck"]["volume"] > base
    assert all(f["nodes"][0] == ic.HUB or f["nodes"][1] == ic.HUB
               for f in lw.offload_flows(CFG, 512, "prefill", adies))
