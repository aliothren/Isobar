"""Slow suite -- one real mapper run end to end (minutes; run with --slow).

Uses a small synthetic 2x2-tiling matmul (C=512, M=256 on the 256(C)x128(M)
logical array -> P_V x P_H = 2x2). This is also the hand-checkable case that
will pin TrafficExtraction's hyperedge DISTRIBUTION when workstream B lands
(the conservation assertion below only pins volume).
"""
from _util import approx, golden

import scripts.crossbar_comm as cc
from scripts import llm_workload as lw

_CACHE = {}


def _run():
    if "r" not in _CACHE:
        _CACHE["r"] = lw.run_op(lw.Op("tiny2x2", "static", P=8, C=512, M=256),
                                phase="prefill")
    return _CACHE["r"]


def test_comm_dump_shape():
    flows, per_xb, gshape, xb_coord = cc.build_flows(_run()["output_dir"],
                                                     verbose=False)
    assert len(flows) == 8 + 32 + 256, "8 macro + 32 core + 256 crossbar edges"
    assert len(per_xb) == 256


def test_per_level_volume_conservation():
    """every level carries the same total words (v0 uniform model: true by
    construction; v1 structured model: becomes the hyperedge-vs-total
    conservation law). This assertion survives the v0->v1 re-baseline."""
    flows, _, _, _ = cc.build_flows(_run()["output_dir"], verbose=False)
    totals = {}
    for f in flows:
        totals[f["level"]] = totals.get(f["level"], 0.0) + f["volume"]
    vals = list(totals.values())
    for v in vals[1:]:
        approx(v, vals[0], 1e-6)


def test_position_spread_golden_v0():
    """max/min per-crossbar cost -- v0 (uniform traffic) golden. EXPECT this
    number to change when TrafficExtraction lands: re-baseline to v1 + changelog,
    do NOT 'fix' the code to preserve it."""
    _, per_xb, _, _ = cc.build_flows(_run()["output_dir"], verbose=False)
    g = golden("slow_golden_v0.json")
    approx(per_xb.max() / max(per_xb.min(), 1), g["tiny2x2_max_over_min"], 5e-3)


def test_energy_breakdown_identity():
    r = _run()
    s = sum(i["energy_J"] for i in r["levels"].values())
    assert 0.985 <= s / r["compute_J"] <= 1.005