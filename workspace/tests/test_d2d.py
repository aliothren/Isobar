"""Group 15 -- D2D (W3) acceptance: the die level joins the registry.

The former xfail_single_die_d2d_degenerate_invariant lived in group 4/5; W3
closed the gap, and per the XPASS protocol its honest replacement is this
group. The acceptance the xfail's docstring demanded -- single-die fabric =>
zero inter-die cost AND the pre-D2D totals (replace the flat charge, never add
to it) -- is tests 1 and 2 below.
"""
from _util import approx

from scripts import fabric, interconnect as ic, placement
from scripts import llm_workload as lw
import scripts.crossbar_comm as cc

MULTI = "models/fabric/mlx300_multidie.yaml"
CFG = lw.GptConfig()


def _multi():
    import os
    return fabric.from_yaml(os.path.join("/home/workspace", MULTI))


# ------------------------------------------------ 1. single-die degeneracy
def test_single_die_fabric_is_exactly_free():
    """Shipped default: every layer on the one die -> zero energy, zero
    latency, zero flows. The pre-D2D totals are untouched by construction
    (the overlay contributes nothing and the flat charge is not edited)."""
    d = lw.die_to_die_activation(CFG, S=512, phase="prefill")
    assert d["energy_J"] == 0.0
    assert d["latency_s"] == 0.0
    assert d["flows"] == []
    assert d["n_dies"] == 1
    assert d["n_boundaries"] == CFG.n_layers - 1     # boundaries exist, cost 0


# ------------------------------------------------ 2. replace, never add
def test_adjacent_dies_add_no_energy_beyond_the_flat_charge():
    """reference_hops = 1 declares the flat CiMLoop price covers one boundary
    traversal. Sequential assignment on the 6x4 grid puts most consecutive
    layers on ADJACENT dies (hops = 1) -> those boundaries bill zero surplus;
    only the row-wrap boundaries (hops > 1) bill the difference."""
    fab = _multi()
    d = lw.die_to_die_activation(CFG, S=512, phase="prefill", fabric=fab)
    words = 512 * CFG.d_model
    pj = fab.level("die").link.pj_per_word
    # 6x4 row-major: 23 boundaries = 20 in-row steps (hops 1, surplus 0)
    # + 3 row wraps (5,y)->(0,y+1): hops 5+1=6, surplus 5 each
    expected_surplus = 3 * 5.0
    approx(d["energy_J"], words * pj * 1e-12 * expected_surplus, 1e-12)


def test_surplus_never_negative():
    """A single-hop (or co-located) boundary must never REFUND energy."""
    fab = _multi()
    asg = [0, 1] + [1] * (CFG.n_layers - 2)          # one hop, then co-located
    d = lw.die_to_die_activation(CFG, S=512, phase="prefill", fabric=fab,
                                 assignment=asg)
    assert d["energy_J"] == 0.0                       # hops 1 -> surplus 0
    assert d["latency_s"] > 0.0                       # the traversal still takes time


# ------------------------------------------------ 3. conservation
def test_boundary_count_and_volume_closed_forms():
    """n_boundaries = n_layers - 1; each boundary carries the hidden state:
    S*d_model (prefill) / d_model (decode). The same volume is ffn2's output
    (P=S, M=d_model), i.e. what Timeloop's own output counters bill for that
    op -- the reconciliation anchor."""
    for phase, words in (("prefill", 512 * CFG.d_model), ("decode", CFG.d_model)):
        d = lw.die_to_die_activation(CFG, S=512, phase=phase)
        assert d["n_boundaries"] == CFG.n_layers - 1
        assert d["words"] == words * (CFG.n_layers - 1)
    ffn2 = [op for op in lw.block_ops(CFG, S=512, phase="prefill")
            if op.name == "ffn2"][0]
    assert ffn2.P * ffn2.M == 512 * CFG.d_model       # boundary == ffn2 output


# ------------------------------------------------ 4. node-to-node paths
def test_node_to_node_paths_per_scheme():
    slots = [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (0, 2), (1, 2)]
    star = ic.Star(slots)
    assert star.path(0, 7) == ["star:link0", "star:link7"]   # via the hub switch
    hub = (0.875, 0.875)                                      # the slots' centroid
    approx(star.hops(0, 7),                                   # both spokes sum
           (hub[0] + hub[1]) + (abs(hub[0] - 1) + abs(hub[1] - 2)), 1e-12)
    mesh = ic.Mesh(slots, {"routing": "xy", "hub": "center"})
    assert mesh.path(0, 2) == ["mesh:seg(0, 0)-(1, 0)", "mesh:seg(1, 0)-(2, 0)"]
    assert mesh.path(0, 4) == ["mesh:seg(0, 0)-(1, 0)", "mesh:seg(1, 0)-(1, 1)"]
    bus = ic.Bus(slots, {"driver": "center"})
    assert bus.path(0, 7) == ["bus:medium"]
    tree = ic.HTree(slots, {"branching": 4})
    assert tree.path(0, 1) == ["h_tree:d2g0", "h_tree:d2g1"]   # sibling leaves:
    #   two leaf edges, no climb (hops therefore 0 -- the climb metric)
    assert len(tree.path(0, 4)) == 4                  # cross-parent: 2 up + 2 down


# ------------------------------------------------ 5. D2D contention
def test_die_flows_feed_link_occupancy():
    """The die level's flows go through the SAME occupancy function as the
    on-die tree -- level-agnostic for real. Sequential assignment on the die
    mesh: in-row boundary flows overlap on row segments; with a bandwidth set
    the busiest die wire serializes."""
    import dataclasses
    fab = _multi()
    lv = fab.level("die")
    fab = dataclasses.replace(
        fab, levels=[dataclasses.replace(
            l, link=dataclasses.replace(l.link, bandwidth_words_per_cycle=1024.0))
            if l.name == "die" else l for l in fab.levels]).validate()
    d = lw.die_to_die_activation(CFG, S=512, phase="prefill", fabric=fab)
    occ = cc.link_occupancy(d["flows"], fab, 1.449e-6,
                            placement.sequential_fill(fab))
    assert occ["serialization_s"] > 0.0
    assert all(e["resource"].startswith("die/") for e in occ["per_link"])
    # hand-check: row-major chain 0->1->...->23 on XY mesh -- consecutive flows
    # never share a segment EXCEPT the wrap flows crossing a row; every in-row
    # segment carries exactly one boundary flow, wraps ride x-segments back.
    loads = {e["resource"]: e["volume"] for e in occ["per_link"]}
    words = 512.0 * CFG.d_model
    # segment (0,0)-(1,0) carries flow 0->1 AND the wrap 5->6's x-walk back
    assert loads["die/mesh:seg(0, 0)-(1, 0)"] == 2 * words


def test_snake_assignment_beats_sequential_on_latency():
    """The layer->die assignment is a placement decision the model now sees:
    snake (boustrophedon) removes the row-wrap long hops entirely."""
    fab = _multi()
    mx, _ = fab.level("die").mesh
    snake = []
    for L in range(CFG.n_layers):
        row, col = divmod(L, mx)
        snake.append(row * mx + (mx - 1 - col if row % 2 else col))
    seq = lw.die_to_die_activation(CFG, S=512, phase="prefill", fabric=fab)
    snk = lw.die_to_die_activation(CFG, S=512, phase="prefill", fabric=fab,
                                   assignment=snake)
    assert snk["latency_s"] < seq["latency_s"]
    assert snk["energy_J"] == 0.0                     # every hop is 1 -> no surplus
    approx(snk["avg_die_hops"], 1.0, 1e-12)


# ------------------------------------------------ 6. pipelined operation
def _bw(fab, bw):
    import dataclasses
    return dataclasses.replace(
        fab, levels=[dataclasses.replace(
            l, link=dataclasses.replace(l.link, bandwidth_words_per_cycle=bw))
            if l.name == "die" else l for l in fab.levels]).validate()


def _snake(fab):
    mx, _ = fab.level("die").mesh
    out = []
    for L in range(CFG.n_layers):
        row, col = divmod(L, mx)
        out.append(row * mx + (mx - 1 - col if row % 2 else col))
    return out


def test_pipeline_interval_identities():
    """interval = max(stage, busiest-wire beat). Three pinned regimes:
    no bandwidth -> compute stage exactly; fast links -> compute stage;
    slow links -> the net term, linear in 1/bw."""
    fab = _multi()
    stage = 13.11e-3
    d0 = lw.die_pipeline_interval(CFG, 512, "prefill", stage, fabric=fab)
    assert d0["net_s"] == 0.0 and d0["interval_s"] == stage   # off by default

    words = 512.0 * CFG.d_model
    cyc = 1.449e-6
    for bw in (256.0, 64.0):
        d = lw.die_pipeline_interval(CFG, 512, "prefill", stage,
                                     fabric=_bw(fab, bw))
        approx(d["net_s"], 2 * words / bw * cyc, 1e-9)  # busiest wire = 2 boundaries
        assert d["interval_s"] == max(stage, d["net_s"])


def test_pipeline_assignment_ratio_is_the_load_ratio():
    """Below the knee the seq/snake interval ratio equals the busiest-wire
    load ratio (2/1) EXACTLY -- the placement effect, undiluted."""
    fab = _bw(_multi(), 8.0)                       # deep in the network regime
    stage = 13.11e-3
    seq = lw.die_pipeline_interval(CFG, 512, "prefill", stage, fabric=fab)
    snk = lw.die_pipeline_interval(CFG, 512, "prefill", stage, fabric=fab,
                                   assignment=_snake(fab))
    assert seq["network_bound"] and snk["network_bound"]
    approx(seq["interval_s"] / snk["interval_s"], 2.0, 1e-12)


def test_pipeline_bus_serializes_all_boundaries():
    """One shared interposer medium: every beat moves all 23 boundaries through
    it -> net = 23 * words/bw * cyc exactly, assignment-independent."""
    import dataclasses
    fab = _multi()
    lvls = []
    for l in fab.levels:
        if l.name == "die":
            l = dataclasses.replace(l, link=dataclasses.replace(
                l.link, topology="bus", params={"driver": "center"},
                bandwidth_words_per_cycle=256.0))
        lvls.append(l)
    fab = dataclasses.replace(fab, levels=lvls).validate()
    words, cyc = 512.0 * CFG.d_model, 1.449e-6
    for asg in (None, _snake(fab)):
        d = lw.die_pipeline_interval(CFG, 512, "prefill", 13.11e-3, fabric=fab,
                                     assignment=asg)
        approx(d["net_s"], 23 * words / 256.0 * cyc, 1e-9)


def test_adversarial_assignment_ordering():
    """avg hops: snake (1.0) < sequential (1.65) < far-pairs adversarial; the
    surplus energy follows the same order with snake at exactly zero."""
    fab = _multi()
    adv = []
    for L in range(CFG.n_layers):
        adv.append(L // 2 if L % 2 == 0 else 23 - L // 2)
    res = {}
    for name, asg in (("snake", _snake(fab)), ("seq", None), ("adv", adv)):
        res[name] = lw.die_to_die_activation(CFG, 512, "prefill", fabric=fab,
                                             assignment=asg)
    assert res["snake"]["avg_die_hops"] < res["seq"]["avg_die_hops"] \
        < res["adv"]["avg_die_hops"]
    assert res["snake"]["energy_J"] == 0.0
    assert res["seq"]["energy_J"] < res["adv"]["energy_J"]
