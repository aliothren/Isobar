"""Group 12 -- T2 static contention (link_occupancy), pure-function checks.

The same function will consume D2D links when workstream C6 lands -- these
assertions are level-agnostic on purpose.
"""
import dataclasses

from _util import approx

import scripts.crossbar_comm as cc
from scripts import fabric

F = fabric.default()
CYC = 1e-9

FLOWS = [
    {"level": "glb<->macro", "src": "glb", "dst": "macro0",
     "volume": 1000.0, "distance": 2.0},
    {"level": "glb<->macro", "src": "glb", "dst": "macro1",
     "volume": 4000.0, "distance": 5.0},
    {"level": "core<->crossbar", "src": "core0.0", "dst": "xb0",
     "volume": 9000.0, "distance": 0.5},
]


def _with_bw(level_link_bw):
    """fabric variant with bandwidths set on selected links, by link name."""
    levels = []
    for lv in F.levels:
        if lv.link is not None and lv.link.name in level_link_bw:
            levels.append(dataclasses.replace(
                lv, link=dataclasses.replace(
                    lv.link,
                    bandwidth_words_per_cycle=level_link_bw[lv.link.name])))
        else:
            levels.append(lv)
    return dataclasses.replace(F, levels=levels)


def test_default_fabric_yields_zero_contention():
    """no bandwidth anywhere (the shipped default) -> the term is exactly 0,
    so run_op totals cannot move -- the W1 invariance guarantee."""
    occ = cc.link_occupancy(FLOWS, F, CYC)
    assert occ["serialization_s"] == 0.0
    assert occ["per_link"] == [] and occ["bottleneck"] is None


def test_occupancy_math_and_bottleneck():
    fab = _with_bw({"glb<->macro": 2.0})
    occ = cc.link_occupancy(FLOWS, fab, CYC)
    assert len(occ["per_link"]) == 2                  # only the limited level
    approx(occ["per_link"][0]["seconds"], 1000.0 / 2.0 * CYC, 1e-12)
    approx(occ["serialization_s"], 4000.0 / 2.0 * CYC, 1e-12)
    assert occ["bottleneck"]["dst"] == "macro1"       # heaviest link wins


def test_unlimited_level_does_not_participate():
    """a limit on one level must not conjure occupancy on another."""
    fab = _with_bw({"core<->crossbar": 1.0})
    occ = cc.link_occupancy(FLOWS, fab, CYC)
    assert all(pl["level"] == "core<->crossbar" for pl in occ["per_link"])
    approx(occ["serialization_s"], 9000.0 * CYC, 1e-12)


def test_zero_volume_links_never_bottleneck():
    fab = _with_bw({"glb<->macro": 1.0})
    flows = FLOWS + [{"level": "glb<->macro", "src": "glb", "dst": "macro7",
                      "volume": 0.0, "distance": 9.0}]
    occ = cc.link_occupancy(flows, fab, CYC)
    assert all(pl["dst"] != "macro7" for pl in occ["per_link"])


def test_max_composition_rule():
    """the T2 term enters the critical path by max(compute, serialization),
    never by sum -- pin the composition run_op uses."""
    fab = _with_bw({"glb<->macro": 2.0})
    ser = cc.link_occupancy(FLOWS, fab, CYC)["serialization_s"]
    approx(ser, 2.0e-6, 1e-12)                        # 4000 words / 2 w/c @ 1ns
    assert max(3.0e-6, ser) == 3.0e-6                 # compute-bound: free
    assert max(1.0e-9, ser) == ser                    # link-bound: serialized
