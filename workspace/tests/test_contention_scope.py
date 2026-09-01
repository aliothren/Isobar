"""Group 13 -- what the contention tier does and does NOT follow, per scheme.

History worth keeping: before W2 this file asserted that occupancy is
placement-INVARIANT, with a note that closing O5 meant REPLACING those
assertions rather than deleting them. That is what happened. The invariance is
still true and still tested -- but only for `star`, where it is a property of
the model (private link per node, no shared segment), not a limitation. Under
`mesh` the routes overlap and placement moves contention, which is the whole
point of O5.
"""
import dataclasses

from _util import approx

import scripts.crossbar_comm as cc
from scripts import fabric, interconnect as ic, placement

# Group 13's mechanics are hand-checked on the 3x3 grid (hub slot (1,1), one
# empty slot); since C27 the default fabric is the fill-exact 2x4, so the 3x3
# comparison variant is loaded explicitly here.
F = fabric.from_yaml("/home/workspace/models/fabric/mlx300_3x3.yaml")
CYC = 1.449e-6
VOL = 51_249_152.0


def _with(topology, params=None, bw=1024.0, mesh=None):
    """Default fabric with the macro level's scheme (and optionally mesh) swapped."""
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


def _flows(fab, n=8):
    return [{"level": "glb<->macro", "level_name": "macro", "node": m,
             "src": "glb", "dst": f"macro{m}", "volume": VOL,
             "distance": 0.0} for m in range(n)]


def _perm(fab, i, j):
    seq = placement.sequential_fill(fab)
    tbl = list(seq.slots["macro"])
    tbl[i], tbl[j] = tbl[j], tbl[i]
    return dataclasses.replace(seq, slots={**seq.slots, "macro": tbl}).verify(fab)


# ------------------------------------------------------------------ star
def test_star_occupancy_is_volume_aware():
    fab = _with("star")
    fl = _flows(fab)
    fl[7]["volume"] = 4 * VOL
    occ = cc.link_occupancy(fl, fab, CYC)
    approx(occ["serialization_s"], 4 * VOL / 1024.0 * CYC, 1e-9)
    assert occ["bottleneck"]["dst"] == "macro7"


def test_star_occupancy_is_placement_invariant_BY_DESIGN():
    """A private-link model has no shared segment for distance to congest.
    True property of `star`, not a gap -- `mesh` below is the contrast."""
    fab = _with("star")
    a = cc.link_occupancy(_flows(fab), fab, CYC,
                          placement.sequential_fill(fab))["serialization_s"]
    b = cc.link_occupancy(_flows(fab), fab, CYC,
                          _perm(fab, 0, 7))["serialization_s"]
    approx(a, b, 1e-12)
    approx(a, VOL / 1024.0 * CYC, 1e-9)          # one flow, one private wire


# ------------------------------------------------------------------ mesh (O5)
def test_mesh_shares_segments_so_the_hot_link_carries_several_flows():
    """O5 closed: the busiest segment carries 3 macros' traffic on the 3x3 mesh
    (hand-checked), where star's busiest wire carries exactly one."""
    fab = _with("mesh")
    occ = cc.link_occupancy(_flows(fab), fab, CYC)
    approx(occ["serialization_s"], 3 * VOL / 1024.0 * CYC, 1e-9)
    assert occ["bottleneck"]["volume"] == 3 * VOL


def test_mesh_occupancy_follows_placement_when_flows_differ():
    """O5 closed, with the mechanism stated precisely.

    Under a routed scheme contention depends on WHICH SEGMENTS a flow rides, so
    a permutation only matters when the flows differ in volume -- with uniform
    volumes the load depends on the occupied slot SET alone, and permuting is
    provably a no-op (that is a fact about the model, not a bug). Real workloads
    are heterogeneous, and then placement decides: putting the heavy talker ON
    the hub costs nothing, putting it in a far corner loads the hot segment.
    """
    fab = _with("mesh")
    seq = placement.sequential_fill(fab)
    tbl = list(seq.slots["macro"])
    i_hub, i_corner = tbl.index((1, 1)), tbl.index((0, 0))
    swapped = dataclasses.replace(
        seq, slots={**seq.slots,
                    "macro": [tbl[i_hub] if k == i_corner else
                              tbl[i_corner] if k == i_hub else s
                              for k, s in enumerate(tbl)]}).verify(fab)

    heavy = _flows(fab)
    heavy[0]["volume"] = 4 * VOL          # node 0 is the heavy talker

    corner = cc.link_occupancy(heavy, fab, CYC, seq)["serialization_s"]
    on_hub = cc.link_occupancy(heavy, fab, CYC, swapped)["serialization_s"]

    approx(corner, 6 * VOL / 1024.0 * CYC, 1e-9)   # 4V heavy + 2 x 1V share it
    approx(on_hub, 3 * VOL / 1024.0 * CYC, 1e-9)   # heavy talker rides nothing
    assert on_hub < corner, "placement must move contention under a routed scheme"


def test_mesh_ranks_layouts_opposite_to_the_distance_map():
    """3x3 spreads distance badly (heatmap 3.62x) but congests less (peak 3V);
    2x4 is the reverse (1.50x, peak 4V). Two metrics, opposite orders -- pinned
    because it is the clearest evidence the model distinguishes layouts."""
    s33 = ic.Mesh([(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (0, 2), (1, 2)])
    s24 = ic.Mesh([(x, y) for y in range(4) for x in range(2)])

    def peak(m):
        load = {}
        for i in range(8):
            for r in m.path(ic.HUB, i):
                load[r] = load.get(r, 0) + 1
        return max(load.values()), sum(load.values())

    assert peak(s33) == (3, 10)
    assert peak(s24) == (4, 12)


def test_a_node_on_the_hub_traverses_no_segment():
    m = ic.Mesh([(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (0, 2), (1, 2)])
    assert m.hub_coord() == (1.0, 1.0)
    assert m.path(ic.HUB, 4) == []               # node 4 sits at (1,1)


def test_star_is_the_lower_bound_on_contention():
    """Cross-scheme invariant: sharing can only make it worse, never better."""
    fl_star = _flows(_with("star"))
    s = cc.link_occupancy(fl_star, _with("star"), CYC)["serialization_s"]
    m = cc.link_occupancy(_flows(_with("mesh")), _with("mesh"), CYC)["serialization_s"]
    assert s <= m
