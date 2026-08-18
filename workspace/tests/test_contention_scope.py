"""Group 13 -- the measured SCOPE of the contention tier (workstream W1).

These tests pin what T2 does and does NOT do, so the boundary stays honest as
the model grows. The placement-invariance test is deliberately a `test_` (the
current, correct behaviour of a private-link model), not an `xfail`: the gap it
documents is O5, and closing O5 means REPLACING this assertion with its routed
counterpart in the same change -- see the docstring note below.
"""
import dataclasses

from _util import approx

import scripts.crossbar_comm as cc
from scripts import fabric, placement

F = fabric.default()
CYC = 1.449e-6

# a two-macro flow set: same volumes, different distances
FLOWS = [
    {"level": "glb<->macro", "src": "glb", "dst": "macro0",
     "volume": 4000.0, "distance": 1.5},
    {"level": "glb<->macro", "src": "glb", "dst": "macro7",
     "volume": 4000.0, "distance": 12.0},
]


def _bw(v):
    return dataclasses.replace(F, levels=[
        dataclasses.replace(lv, link=dataclasses.replace(
            lv.link, bandwidth_words_per_cycle=v))
        if lv.link is not None and lv.link.cimloop_component else lv
        for lv in F.levels])


def test_occupancy_ignores_distance_by_construction():
    """O5 boundary: equal volumes at very different distances occupy equally.
    A private-link model has no shared segments for distance to congest.
    When routed contention lands, this assertion must be REPLACED (the far
    flow will then load intermediate segments), not deleted."""
    occ = cc.link_occupancy(FLOWS, _bw(1000.0), CYC)
    secs = sorted(pl["seconds"] for pl in occ["per_link"])
    approx(secs[0], secs[1], 1e-12)


def test_occupancy_is_volume_aware():
    """what it DOES see: unequal volumes give unequal occupancy."""
    flows = [dict(FLOWS[0]), dict(FLOWS[1], volume=16000.0)]
    occ = cc.link_occupancy(flows, _bw(1000.0), CYC)
    by_dst = {pl["dst"]: pl["seconds"] for pl in occ["per_link"]}
    approx(by_dst["macro7"] / by_dst["macro0"], 4.0, 1e-12)
    assert occ["bottleneck"]["dst"] == "macro7"


def test_permuting_placement_does_not_change_serialization():
    """the same statement at the pipeline level, on real per-level volumes:
    a placement permutation is invisible to the contention term."""
    from scripts import traffic

    seq = placement.sequential_fill(F)
    tbl = list(seq.slots["macro"])
    tbl[0], tbl[7] = tbl[7], tbl[0]
    alt = dataclasses.replace(seq, slots={**seq.slots, "macro": tbl}).verify(F)

    # synthetic flows standing in for a run (volumes per level, placement-fixed)
    def flows_for(pl):
        coords = pl.level_coords(F, "macro")
        hub = (sum(c[0] for c in coords) / 8, sum(c[1] for c in coords) / 8)
        return [{"level": "glb<->macro", "src": "glb", "dst": f"macro{m}",
                 "volume": 51_249_152.0,
                 "distance": abs(coords[m][0] - hub[0]) + abs(coords[m][1] - hub[1])}
                for m in range(8)]

    a = cc.link_occupancy(flows_for(seq), _bw(1024.0), CYC)["serialization_s"]
    b = cc.link_occupancy(flows_for(alt), _bw(1024.0), CYC)["serialization_s"]
    approx(a, b, 1e-12)
