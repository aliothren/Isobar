"""Group 10 -- the reduction-clustered placement solver (search side).

The solver is the first consumer on the SEARCH side of the fabric/Placement work,
so these pin two different things:

  * the published comparison (0.89/1.48 -> 0.79/0.79 uJ, Figure 7). Merge COUNTS are
    pinned as integers because they are the real invariant -- the energies are just
    counts x two constants, and pinning both catches a constant drifting silently.
  * the D2D acceptance the fix list demands of O2: a single-die fabric must show
    zero die-crossing cost and reproduce the pre-D2D totals exactly ("replace the
    flat charge, don't add to it"). The die term must stay inert until a fabric
    actually has more than one die.
"""
import dataclasses
from collections import Counter

from _util import approx

from scripts import die_solver as ds
from scripts import fabric

# Published Figure 7 numbers, in uJ.
BASE_FLAT, BASE_DIST = 0.8894177280, 1.4823628800
OPT_FLAT, OPT_DIST = 0.7905935360, 0.7905935360

# (cross_core, cross_macro, cross_die) per matmul.
BASE_COUNTS = {"ffn1": (6, 2, 0), "ffn2": (6, 1, 0),
               "qkv_proj": (4, 1, 0), "attn_out_proj": (2, 0, 0)}
OPT_COUNTS = {"ffn1": (5, 0, 0), "ffn2": (6, 0, 0),
              "qkv_proj": (3, 0, 0), "attn_out_proj": (2, 0, 0)}


def _counts(rows):
    return {r.name: (r.cross_core, r.cross_macro, r.cross_die) for r in rows}


def _multi_die(n=4, mesh=(2, 2), **over):
    """The default fabric with its die level widened -- the schema already allows it."""
    f = fabric.default()
    levels = [dataclasses.replace(lv, per_parent=n, mesh=mesh) if lv.name == "die"
              else lv for lv in f.levels]
    f4 = dataclasses.replace(f, name=f"mlx300-{n}die", levels=levels).validate()
    return dataclasses.replace(ds.Geometry.from_fabric(f4), **over)


def test_geometry_comes_from_the_fabric():
    """No hardcoded counts: every number must trace back to the config."""
    f = fabric.default()
    g = ds.GEOM
    assert (g.dies, g.macros_per_die, g.cores_per_macro, g.xbars_per_core) == (
        f.level("die").per_parent, f.level("macro").per_parent,
        f.level("core").per_parent, f.level("crossbar").per_parent)
    assert g.xbars == f.count_below("crossbar") == 256
    assert g.cores == f.count_below("core") == 32


def test_encoder_block_footprint_is_216_tiles():
    assert sum(len(ds.tiles_of(n)) for n in ds.ORDER) == 216
    assert ds.grid("ffn2") == (6, 12)          # the deep reduction: n_C = 12 > 8/core


def test_both_placers_are_complete_and_disjoint():
    want = Counter(t for n in ds.ORDER for t in ds.tiles_of(n))
    for place in (ds.baseline_place, ds.optimizer_place):
        pl = place(ds.ORDER)
        assert Counter(pl.values()) == want, f"{place.__name__} lost/duplicated a tile"
        assert max(pl) < ds.GEOM.xbars


def test_baseline_golden():
    rows, flat, dist = ds.cost(ds.baseline_place(ds.ORDER))
    assert _counts(rows) == BASE_COUNTS
    approx(flat / 1e6, BASE_FLAT, 1e-9)
    approx(dist / 1e6, BASE_DIST, 1e-9)


def test_optimizer_golden():
    rows, flat, dist = ds.cost(ds.optimizer_place(ds.ORDER))
    assert _counts(rows) == OPT_COUNTS
    approx(flat / 1e6, OPT_FLAT, 1e-9)
    approx(dist / 1e6, OPT_DIST, 1e-9)


def test_optimizer_eliminates_every_cross_macro_merge():
    """The point of the placer: the expensive term goes to zero, so flat == dist."""
    rows, flat, dist = ds.cost(ds.optimizer_place(ds.ORDER))
    assert sum(r.cross_macro for r in rows) == 0
    assert flat == dist


def test_single_die_charges_nothing_for_d2d():
    """O2 acceptance, solver side: one die => no die crossings, and the totals are
    exactly the pre-D2D ones (the die term must REPLACE nothing when it is inert)."""
    assert fabric.default().level("die").per_parent == 1
    for place, flat, dist in ((ds.baseline_place, BASE_FLAT, BASE_DIST),
                              (ds.optimizer_place, OPT_FLAT, OPT_DIST)):
        rows, f, d = ds.cost(place(ds.ORDER))
        assert sum(r.cross_die for r in rows) == 0
        approx(f / 1e6, flat, 1e-9)
        approx(d / 1e6, dist, 1e-9)


def test_multi_die_fabric_that_still_fits_is_identical():
    """Widening the fabric to 4 dies must not move a number while the workload still
    fits on one die -- the die dimension is opt-in, not a silent surcharge."""
    g4 = _multi_die()
    assert g4.dies == 4 and g4.xbars == 1024
    rows, flat, dist = ds.cost(ds.baseline_place(ds.ORDER, g4), g4)
    assert _counts(rows) == BASE_COUNTS
    approx(flat / 1e6, BASE_FLAT, 1e-9)
    approx(dist / 1e6, BASE_DIST, 1e-9)


def test_die_crossing_without_a_stated_price_is_refused():
    """D2D energy is null in the fabric (DR-3). A placement that crosses a die may
    not be silently scored -- the caller has to own the assumption."""
    tiny = _multi_die(macros_per_die=1)          # 32 crossbars/die, ffn1 needs 72
    pl = ds.baseline_place(["ffn1"], tiny)
    rows, _, _ = ds.cost(pl, tiny, w_die=8.0)
    assert sum(r.cross_die for r in rows) > 0, "workload should span dies here"
    try:
        ds.cost(pl, tiny)
    except ValueError as e:
        assert "DR-3" in str(e)
        return
    raise AssertionError("unpriced die crossing was scored anyway")


def test_die_weight_is_charged_at_the_outermost_boundary_only():
    """Nested decomposition: each merge is counted once, at its outermost boundary."""
    tiny = _multi_die(macros_per_die=1)
    rows, _, _ = ds.cost(ds.baseline_place(["ffn1"], tiny), tiny, w_die=8.0)
    r = rows[0]
    assert r.cross_core >= r.cross_macro >= r.cross_die
    pure_core = r.cross_core - r.cross_macro
    pure_macro = r.cross_macro - r.cross_die
    expected = (ds.W_CORE * pure_core + ds.W_MACRO_DIST * pure_macro
                + 8.0 * r.cross_die) * ds._PARTIAL_WORDS * ds.ROUTER_PJ_PER_WORD
    approx(r.energy_dist_pj, expected, 1e-9)


def test_avg_hops_is_the_encoding_the_sim_consumes():
    """placement_sim_compare feeds these to HOP_DISTANCE; they must be derived from
    the placements, not transcribed (they were hand-written once and would rot)."""
    assert ds.avg_hops_per_merge(ds.baseline_place(ds.ORDER)) == {
        "ffn1": 2.0, "ffn2": 1.5, "qkv_proj": 1.75, "attn_out_proj": 1.0}
    assert ds.avg_hops_per_merge(ds.optimizer_place(ds.ORDER)) == {
        "ffn1": 1.0, "ffn2": 1.0, "qkv_proj": 1.0, "attn_out_proj": 1.0}
