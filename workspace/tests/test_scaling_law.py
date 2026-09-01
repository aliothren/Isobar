"""Group 28 -- the mapper-measured V(d, S) (O17c).

Pins the 48-run probe data (analysis/scaling_probes.json) and its derived
summary: (1) the input-trunk regime -- for every static op at d >= 2560
the busiest on-die wire is the input DOWN trunk and serial / compute =
d / (16,384 x 7) exactly ("knee ~ d", slope 1, the closed form the O29
boundary family uses); (2) the flip d* sits at ~1,220-1,350, NOT at the
ideal-capacity prediction 5,793 -- the prediction is falsified by >4x
(it ignored the macro fanout and exact die fill); (3) ffn2's row is
non-monotonic (0.0714 at d=4096 > 0.0446 at d=5120): the tiler's macro C
split changes -- the law is mapper-dependent where the tiler steps;
(4) S-independence of every probed ratio, attention included (qk^t's
volume follows S^2 but so does its compute); (5) the probes ran in the
column-split-only regime -- the row split (O15) stays unexercised -- and
the d = 2560 point reproduces the 2.7B block's measured ratios on a
different package (24 vs 48 dies): the die-internal law does not see the
package.
"""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
PROBES = json.load(open(os.path.join(WS, "analysis", "scaling_probes.json")))
SUMMARY = json.load(open(os.path.join(WS, "analysis", "scaling_law_summary.json")))
PTS = {(p["d"], p["S"]): {o["name"]: o for o in p["ops"]} for p in PROBES["points"]}
TRUNK = 16384.0 * 7
STATICS = ("qkv_proj", "out_proj", "ffn1", "ffn2")


def _updown(rec):
    return (max(e["down"] for e in rec["macro_edges"]),
            max(e["up"] for e in rec["macro_edges"]) * 2.0)   # 16-bit psums


def test_input_trunk_regime_is_the_closed_form_d_over_114688():
    """d >= 2560, statics with macro C split 1 (qkv/out/ffn1): busiest wire
    = the input trunk, down = S x d words per macro edge, ratio = d/114,688
    exactly. This is the boundary family's closed form."""
    assert TRUNK == SUMMARY["trunk_denominator"]
    for d in (2560, 4096, 5120, 6144, 8192):
        for name in ("qkv_proj", "out_proj", "ffn1"):
            r = PTS[(d, 512)][name]
            down, up = _updown(r)
            assert down > up, (d, name)
            approx(down, 512.0 * d, 1e-9)
            approx(r["serial_over_compute"], d / TRUNK, 1e-6), (d, name)


def test_the_flip_dstar_is_measured_at_1_2k_and_the_prediction_is_falsified():
    """The partial-sum UP regime exists only below d* ~ 1,220-1,350; the
    ideal-capacity prediction 1024 x sqrt(32) ~ 5,793 assumed the up
    traffic rides one die edge (it divides across the 8 macro edges) and
    that dies stay full -- off by > 4x. d* is a paper number: measured,
    with the two extra runs (d = 5120, 6144) proving the trunk line runs
    STRAIGHT through the predicted crossing."""
    ds = SUMMARY["dstar"]
    approx(ds["qkv_proj"], 1224, 2e-2)
    approx(ds["out_proj"], 1288, 2e-2)
    approx(ds["ffn1"], 1349, 2e-2)
    for name, v in ds.items():
        assert 1024 < v < 2560, name                     # bracketed by the grid
        assert SUMMARY["ideal_dstar"] / v > 4.0, name    # the falsification
    assert "ffn2" not in ds                              # down-dominated everywhere
    for d in (5120, 6144):                               # no valley at the prediction
        for name in ("qkv_proj", "out_proj", "ffn1"):
            down, up = _updown(PTS[(d, 512)][name])
            assert down > up
    # below the flip the mapper reshapes the point: at d = 1024 the die is
    # underfull and weights are replicated to split P (compute < S x t_MVM)
    assert PTS[(1024, 512)]["qkv_proj"]["compute_s"] < 0.9 * 512 * 7 * 1.4486e-6
    approx(PTS[(2560, 512)]["qkv_proj"]["compute_s"], 512 * 7 * 1.4485714e-6, 1e-3)


def test_ffn2_rides_the_tiler_step():
    """ffn2 (C = 4d) is non-monotonic in d: 0.0714 at 4096 drops to 0.0446
    at 5120 because the tiler's macro C split changes -- the law is
    mapper-dependent exactly where the tiler steps."""
    row = SUMMARY["d_law"]["ffn2"]["ratio"]
    grid = SUMMARY["d_grid"]
    r = dict(zip(grid, row))
    approx(r[4096], 0.0714, 1e-2)
    approx(r[5120], 0.0446, 1e-2)
    assert r[4096] > r[5120]                             # the step
    assert all(b == "down" for b in SUMMARY["d_law"]["ffn2"]["busiest"])


def test_every_probed_ratio_cancels_S():
    """S in {128..2048} at d = 1024: the statics' ratio is exactly flat,
    and so is qk^t's -- its busiest-wire volume follows S^2, but so does
    its compute. The 'attention follows S' exception is about absolute
    volume, not the knee ratio."""
    for name, want in (("qkv_proj", 0.0134), ("ffn2", 0.0357), ("qk^t", 0.0714)):
        row = SUMMARY["s_check"][name]
        assert len(row) == 5
        approx(row[0], want, 1e-2)
        for v in row[1:]:
            approx(v, row[0], 1e-9), name
    approx(PTS[(1024, 512)]["qk^t"]["serial_over_compute"], 1.0 / 14.0, 1e-3)


def test_the_regime_is_column_split_only_and_matches_the_2p7b_block():
    """Every static probe used the M (column) split -- the row split (O15)
    stays unexercised; and the d = 2560 probes reproduce the 2.7B block's
    measured ratios on a different package (24- vs 48-die fabric): the
    on-die law does not see the package."""
    assert "column split only" in PROBES["regime"]
    for p in PROBES["points"]:
        for o in p["ops"]:
            if o["kind"] == "static":
                assert o["split"] in (None, "M"), (p["d"], o["name"])
                assert o["policy"] == "spatial_multi_die"
            else:
                assert o["dies"] == 1 and o["policy"] == "reject"
    full = json.load(open(os.path.join(WS, "analysis", "scale_2p7b_per_op.json")))
    b27 = {r["name"]: r for r in full["phases"]["prefill"]}
    for name in STATICS:
        got = PTS[(2560, 512)][name]["serial_over_compute"]
        want = b27[name]["ondie_serial_ref_s"] / b27[name]["compute_s"]
        approx(got, want, 1e-3), name
    # 48 runs: 6 ops x 6 d values + 3 ops x 4 extra S values
    assert sum(len(p["ops"]) for p in PROBES["points"]) == 48


def test_scheme_multipliers_from_the_rescored_flows():
    """C33: the stored macro edges re-scored under mesh / bus (closed form,
    zero mapper). The routed multiplier is x4.00 EXACTLY at every d and op
    -- the 2x4 grid puts 4 macros' traffic on the busiest wire, and that is
    d-independent, so the plane's routed lines are measured, not
    extrapolated. The bus multiplier is NOT constant: it drifts with the up
    share (x13.3 at the underfull d = 1024 down to the deep-trunk
    asymptote x8.25 = (8 down + 16 up/down) as up -> 0) -- the O17b x10 at
    the production base is basis-specific. Star re-scoring must reproduce
    the stored serialization (the probes' fabric is the star)."""
    sch = SUMMARY["scheme_check"]
    for name, per in sch.items():
        for d, row in per.items():
            star = row["star (private links)"]
            stored = PTS[(int(d), 512)][name]["serial_over_compute"]
            approx(star, stored, 1e-9)
            approx(row["mesh, glb centre"] / star, 4.0, 1e-9), (name, d)
            assert 8.2 < row["bus (shared medium)"] / star < 13.4
    approx(sch["ffn1"]["8192"]["bus (shared medium)"] /
           sch["ffn1"]["8192"]["star (private links)"], 8.25, 1e-2)
    approx(sch["qkv_proj"]["1024"]["bus (shared medium)"] /
           sch["qkv_proj"]["1024"]["star (private links)"], 13.33, 1e-2)
