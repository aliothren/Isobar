"""Group 14 -- the interconnect scheme registry (workstream W2).

The load-bearing test here is the IDENTITY set: with the shipped `star`
topology every cost path must reproduce its pre-W2 value exactly, because star
is the model those values were computed under. If any of these move, the
rewiring changed semantics rather than plumbing.
"""
import dataclasses

from _util import approx

import scripts.crossbar_comm as cc
from scripts import fabric, interconnect as ic, placement
from scripts import placement_aware as pa

F = fabric.default()
SEQ = placement.sequential_fill(F)


# ------------------------------------------------------------------ identities
def test_pitch_bridges_the_two_coordinate_systems():
    """slot units x pitch == global leaf-grid units, per level."""
    assert (F.pitch("macro"), F.pitch("core"), F.pitch("crossbar")) == (6, 3, 1)


def test_star_reproduces_the_legacy_hop_constants():
    for lvl, want_max, want_pitch in (("macro", 2.0, 6), ("core", 1.0, 3),
                                      ("crossbar", 2.0, 1)):
        s = ic.build(F, lvl, SEQ)
        approx(s.max_hops(), want_max, 1e-12)
        approx(s.max_hops() * F.pitch(lvl), want_max * want_pitch, 1e-12)
    hops = cc.level_max_hops()
    approx(hops["glb<->macro"], 12.0, 1e-12)
    approx(hops["macro<->core"], 3.0, 1e-12)
    approx(hops["core<->crossbar"], 2.0, 1e-12)


def test_star_mean_hops_equals_the_legacy_energy_distance():
    """the energy overlay's 1.3125 is exactly star's mean hub->node distance."""
    approx(ic.build(F, "macro", SEQ).mean_hops(), 1.3125, 1e-12)
    approx(pa.hops_to_center(F.slots("macro")), 1.3125, 1e-12)


def test_star_energy_path_matches_the_place_fn_prior():
    levels = {"router": {"fanout": 8, "unit_pJ": 48.3, "volume": 10,
                         "energy_J": 2.668e-5}}
    layout = {"router": {"pattern": "to_center", "reference_hops": 1.0}}
    old = pa.position_aware_cost(levels, layout, pa.place_grid)
    new = pa.position_aware_cost(levels, layout, placement=SEQ, fabric=F)
    assert new["position_aware"] == old["position_aware"]


# ------------------------------------------------------------------ star props
def test_star_gives_every_node_a_private_resource():
    s = ic.build(F, "macro", SEQ)
    res = [s.path(ic.HUB, i)[0] for i in range(8)]
    assert len(set(res)) == 8, "star must not share a resource between nodes"
    assert len(s.resources()) == 8


def test_hub_is_the_centroid():
    s = ic.build(F, "macro", SEQ)
    approx(s.hub_coord()[0], 0.875, 1e-12)
    approx(s.hub_coord()[1], 0.875, 1e-12)


def test_node_to_node_interface_works():
    """the (a, b) form -- D2D hand-offs are node-to-node, not hub-centric."""
    s = ic.build(F, "macro", SEQ)
    approx(s.hops(0, 5), 3.0, 1e-12)          # (0,0) -> (2,1)
    approx(s.hops(0, 0), 0.0, 1e-12)


# ------------------------------------------------------------------ registry
def test_unknown_topology_is_rejected():
    try:
        ic.validate_params("wormhole", {}, where="test")
    except ValueError as e:
        assert "unknown topology" in str(e)
        return
    raise AssertionError("unknown topology accepted")


def test_unexpected_param_is_rejected():
    try:
        ic.validate_params("star", {"routing": "xy"}, where="test")
    except ValueError as e:
        assert "does not take" in str(e)
        return
    raise AssertionError("stray param accepted")


def test_bad_fabric_config_fails_at_load():
    """a wrong topology name must blow up when the config loads, not mid-run."""
    lv = [dataclasses.replace(l, link=dataclasses.replace(l.link, topology="nope"))
          if l.name == "macro" else l for l in F.levels]
    try:
        dataclasses.replace(F, levels=lv).validate()
    except ValueError:
        return
    raise AssertionError("invalid topology loaded")


def test_shipped_config_is_star_everywhere():
    for lv in F.levels:
        if lv.link is not None:
            assert lv.link.topology == "star", f"{lv.name} is not star"


# ------------------------------------------------------------------ h_tree
def _htree(n=8, k=4, **params):
    return ic.HTree([(0.0, 0.0)] * n, dict(branching=k, **params))


def test_htree_depth_and_required_param():
    assert _htree(8, 4).depth == 2
    assert _htree(8, 2).depth == 3
    try:
        ic.HTree([(0, 0)] * 8, {})           # branching is required
    except ValueError as e:
        assert "requires" in str(e)
    else:
        raise AssertionError("missing branching accepted")


def test_htree_root_edge_is_the_bottleneck():
    """Every flow climbs to the root, so the top edges carry the whole subtree
    -- congestion in a tree is about depth and grouping, not distance."""
    h = _htree(8, 4)
    load = {}
    for i in range(8):
        for r in h.path(ic.HUB, i):
            load[r] = load.get(r, 0) + 1
    top = [v for r, v in load.items() if r.startswith("h_tree:d1")]
    leaf = [v for r, v in load.items() if r.startswith("h_tree:d2")]
    assert sorted(top) == [4, 4] and leaf == [1] * 8


def test_htree_merges_telescope_to_n_minus_1():
    """The lambda-1 decomposition: every merge charged once, at its outermost
    boundary, and the total is always |S| - 1."""
    h = _htree(8, 4)
    for nodes in ([0, 1, 2, 3, 4, 5, 6, 7], [0, 1, 2, 3], [0, 4], [5]):
        m = h.merges_by_depth(nodes)
        assert sum(m.values()) == len(nodes) - 1


def test_htree_same_parent_costs_nothing_at_the_coarse_level():
    """The design rule the collaborator's solver exploits: keep a reduction
    group inside one container and the expensive boundary is never crossed."""
    h = _htree(8, 4)
    assert h.merges_by_depth([0, 1, 2, 3])[1] == 0     # one group -> free
    assert h.merges_by_depth([0, 4])[1] == 1           # split -> one merge
    assert h.merges_by_depth([0, 4])[2] == 0


def test_htree_hops_are_zero_within_a_leaf_and_grow_with_the_lca():
    h = _htree(8, 4)
    approx(h.hops(0, 0), 0.0, 1e-12)
    assert h.hops(0, 1) < h.hops(0, 4)                 # same group vs across


def test_htree_level_length_must_match_depth():
    try:
        _htree(8, 4, level_length=[4, 2, 1])
    except ValueError as e:
        assert "level_length" in str(e)
        return
    raise AssertionError("mismatched level_length accepted")


# ------------------------------------------------------------ hyperedges (W2-3)
def _ts():
    from _util import fixture
    from scripts import traffic
    return traffic.extract(
        fabric=F,
        mapping_text=open(fixture("ffn1_prefill_map.txt")).read(),
        stats_text=open(fixture("ffn1_prefill_stats.txt")).read())


def test_hyperedge_counts_are_convention_free():
    """factors {C:4, P:2} -> 2 reduction groups of 4, whatever the index order."""
    ts = _ts()
    assert ts.hyperedge_shape("macro") == (2, 4)
    assert ts.hyperedge_shape("core") == (4, 1)        # M only: no reduction
    assert ts.hyperedge_shape("crossbar") == (8, 1)


def test_hyperedges_partition_the_instances():
    ts = _ts()
    for lvl, n in (("macro", 8), ("core", 4), ("crossbar", 8)):
        groups = ts.reduction_hyperedges(lvl)
        flat = sorted(i for g in groups for i in g)
        assert flat == list(range(n)), f"{lvl}: not a partition"
        n_groups, size = ts.hyperedge_shape(lvl)
        assert len(groups) == n_groups and all(len(g) == size for g in groups)


def test_hyperedges_feed_the_lambda_1_metric():
    """The two structures compose: a reduction group from the mapping, scored
    by the tree scheme. All four C-instances of a group in one subtree costs
    nothing at the coarse boundary; split across subtrees costs one merge."""
    ts = _ts()
    groups = ts.reduction_hyperedges("macro")
    h = _htree(8, 4)
    clustered = h.merges_by_depth([0, 1, 2, 3])        # one group of 4
    split = h.merges_by_depth(groups[0])               # [0, 2, 4, 6]: straddles
    assert clustered[1] == 0 and split[1] == 1
