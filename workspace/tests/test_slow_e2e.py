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


def test_per_level_volume_conservation_v1():
    """v1 (structured) conservation: the LEAF level ties exactly to Timeloop's
    own counters, and upper levels carry at most the leaf total (strictly less
    wherever the mapping multicasts -- per-level equality was an artifact of
    the uniform model, not physics)."""
    import os

    from scripts import crossbar_stats as cbs
    out_dir = _run()["output_dir"]
    flows, _, _, _ = cc.build_flows(out_dir, verbose=False)
    totals = {}
    for f in flows:
        totals[f["level"]] = totals.get(f["level"], 0.0) + f["volume"]
    txt = open(os.path.join(out_dir, "timeloop-mapper.stats.txt")).read()
    stats_total = (cbs._per_tensor_volume(txt, "row_drivers")
                   + cbs._per_tensor_volume(txt, "adc"))
    approx(totals["core<->crossbar"], stats_total, 1e-6)
    assert totals["glb<->macro"] <= totals["core<->crossbar"] + 1e-6
    assert totals["macro<->core"] <= totals["core<->crossbar"] + 1e-6


def test_position_spread_golden_v2():
    """max/min per-crossbar cost over ACTIVE crossbars -- v2 golden (value
    units, C25; the v1 structured golden read the same 1.25, the v0 uniform
    golden was retired at the B re-baseline; see CHANGELOG)."""
    import numpy as np

    _, per_xb, _, _ = cc.build_flows(_run()["output_dir"], verbose=False)
    act = per_xb[np.asarray(per_xb) > 0]
    g = golden("slow_golden_v2.json")
    assert len(act) == g["tiny2x2_n_active"]
    approx(act.max() / act.min(), g["tiny2x2_max_over_min_active"], 5e-3)


def test_default_config_has_zero_contention():
    r = _run()
    assert r["contention_latency_s"] == 0.0
    assert r["bottleneck_link"] is None


def test_energy_breakdown_identity():
    r = _run()
    s = sum(i["energy_J"] for i in r["levels"].values())
    assert 0.985 <= s / r["compute_J"] <= 1.005


def test_save_flows_on_disk_schema():
    """the auto-dumped per-pair comm files: 296 rows, stable columns/keys."""
    import csv
    import json
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        files = cc.save_flows(_run()["output_dir"], tag="d8check", dest_dir=td)
        csv_p = [f for f in files if f.endswith(".csv")][0]
        json_p = [f for f in files if f.endswith(".json")][0]
        with open(csv_p) as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["level", "src", "dst", "volume_words",
                           "distance_hops", "volume_x_distance"]
        assert len(rows) - 1 == 296
        with open(json_p) as f:
            j = json.load(f)
        for key in ("flows", "per_crossbar_cost"):
            assert key in j, f"JSON missing {key}"
        assert len(j["flows"]) == 296