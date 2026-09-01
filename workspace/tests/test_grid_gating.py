"""Group 24 -- what gates the hub-position lever (C28), and the figure rule.

The 2x4 switch (C27) took the buffer-position lever from 1.67x to 1.00x;
"3x3 vs 2x4" mixes the aspect ratio with the occupancy structure. The
experiment (scripts/analyze_grid_gating.py) separates them on the same
ffn1 traffic and mapping: 3x3 with one empty slot, 2x4 filled, 4x4 and 2x8
with 8 of 16 slots in two fillings each. Pinned here: the busiest-wire loads
per grid x hub, the corner rule (corner busiest = N - macros in the hub's
column under xy routing), the verdict (the gate is the grid's width along
the routing's first axis: 2-wide grids have no lever whatever the filling,
wider grids read 1.5-1.67x; neither squareness nor the empty slot is the
condition), and the soft-placement lever (heaviest talker moved through the
slots), which exists on every grid (1.75x on the 2x4).
Also the figure rule (scripts/figstyle.py): identical series are merged or
annotated, never stacked silently.
"""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
G = json.load(open(os.path.join(WS, "analysis", "grid_gating.json")))
ROWS = {(r["grid"], r["hub"]): r for r in G["rows"]}


def test_hub_lever_table():
    want = {"3x3, one empty slot": (3.0, 5.0), "2x4, filled": (4.0, 4.0),
            "4x4, half-fill (rows 0-1)": (4.0, 6.0), "4x4, checkerboard": (4.0, 6.0),
            "2x8, half-fill (row 0)": (4.0, 4.0), "2x8, checkerboard": (4.0, 4.0)}
    for grid, (c, k) in want.items():
        approx(ROWS[(grid, "centre")]["busiest_x"], c, 1e-9)
        approx(ROWS[(grid, "corner")]["busiest_x"], k, 1e-9)
        approx(G["levers"][grid]["lever"], k / c, 1e-9)


def test_corner_rule_holds_in_every_cell():
    """Under dimension-order routing the corner hub's exit wire carries every
    macro not in the hub's own column: busiest = N - H."""
    for (grid, hub), r in ROWS.items():
        if hub == "corner":
            approx(r["busiest_x"], 8 - r["hub_column_slots"], 1e-9), grid
    # a 2-wide grid keeps half the macros in the hub's column -> no lever
    for grid in ("2x4, filled", "2x8, half-fill (row 0)", "2x8, checkerboard"):
        assert ROWS[(grid, "corner")]["hub_column_slots"] == 4


def test_verdict_is_the_width_along_the_routing_axis():
    assert G["verdict"].startswith("the grid's width along the routing's first axis")
    two_wide = [v["lever"] for g, v in G["levers"].items() if g.startswith("2x")]
    wider = [v["lever"] for g, v in G["levers"].items() if not g.startswith("2x")]
    assert all(abs(v - 1.0) < 1e-9 for v in two_wide) and len(two_wide) == 3
    assert all(1.49 < v < 1.68 for v in wider) and len(wider) == 3
    # neither squareness (the 4x2 half-fill block is not square) nor the empty
    # slot (the 4x4 fillings have none) is the condition
    approx(G["levers"]["4x4, half-fill (rows 0-1)"]["lever"], 1.5, 1e-9)
    approx(G["levers"]["4x4, checkerboard"]["lever"], 1.5, 1e-9)


def test_soft_placement_lever_survives_on_the_2x4():
    """The heaviest talker (x4) moved through the slots: 4 -> 7 on the 2x4
    (1.75x) whichever hub; 3 -> 6 / 5 -> 8 on the 3x3 (2.00x / 1.60x)."""
    for hub in ("centre", "corner"):
        r = ROWS[("2x4, filled", hub)]
        approx(r["heavy_min"], 4.0, 1e-9); approx(r["heavy_max"], 7.0, 1e-9); approx(r["soft_lever"], 1.75, 1e-9)
    approx(ROWS[("3x3, one empty slot", "centre")]["soft_lever"], 2.0, 1e-9)
    approx(ROWS[("3x3, one empty slot", "corner")]["soft_lever"], 1.6, 1e-9)
    approx(ROWS[("4x4, checkerboard", "corner")]["soft_lever"], 1.5, 1e-9)


def test_2x4_cell_recomputed_directly():
    """The 2x4 centre / corner cells through link_occupancy, independent of
    the script's bookkeeping."""
    import dataclasses
    import scripts.crossbar_comm as cc
    from scripts import anchors as an, fabric, placement, traffic
    base = fabric.default()
    assert base.level("macro").mesh == (2, 4)
    ts = traffic.extract(fabric=base,
                         mapping_text=open(os.path.join(HERE, "fixtures", "ffn1_prefill_map.txt")).read(),
                         stats_text=open(os.path.join(HERE, "fixtures", "ffn1_prefill_stats.txt")).read())
    ev = ts.edge_volumes()["macro"]
    flows = [{"level": "glb<->macro", "level_name": "macro", "node": m, "src": "glb", "dst": f"macro{m}",
              "volume": ev["in"] + ev["out"], "down": ev["in"], "up": ev["out"], "distance": 0.0} for m in range(8)]
    def occ(topology, params):
        levels = [dataclasses.replace(lv, link=dataclasses.replace(lv.link, topology=topology, params=params,
                                                                   bandwidth_words_per_cycle=16384.0))
                  if lv.name == "macro" else lv for lv in base.levels]
        fab = dataclasses.replace(base, name="t", levels=levels).validate()
        return cc.link_occupancy(flows, fab, an.CYCLE_S, placement.sequential_fill(fab))["serialization_s"]
    one = occ("star", {})
    approx(occ("mesh", {"routing": "xy", "hub": "center"}) / one, 4.0, 1e-9)
    approx(occ("mesh", {"routing": "xy", "hub": "corner"}) / one, 4.0, 1e-9)
    approx(one, G["one_edge_s"], 1e-9)


def test_figure_rule_helpers():
    from scripts import figstyle as fs
    groups = fs.group_identical([("a", [1, 2, 3]), ("b", [1, 2, 3]), ("c", [1, 2, 4]), ("d", [1, 2, 3])])
    assert [g[0] for g in groups] == [["a", "b", "d"], ["c"]]
    assert fs.merged_label(["a", "b"]) == "a = b (identical on this grid)" and fs.merged_label(["c"]) == "c"
    assert fs.merge_point_labels([("p", 1.0, 2.0), ("q", 1.0, 2.0), ("r", 1.0, 3.0)]) == \
        [("p = q (identical on this grid)", 1.0, 2.0), ("r", 1.0, 3.0)]
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    runs = fs.annotate_bar_ties(ax, [0, 1, 2, 3, 4], [1.0, 1.31, 1.31, 1.31, 3.3], skip_value=1.0)
    assert runs == [(1, 3)]
    plt.close(fig)
