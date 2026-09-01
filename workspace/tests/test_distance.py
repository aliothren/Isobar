"""Group 3 -- distance geometry, calibration-independence, level monotonicity."""
from _util import approx

from scripts import mlx_system as mlx
from scripts import placement_aware as pa


def test_macro_geometry_exact():
    approx(pa.hops_to_center(pa.place_grid(8)), 1.3125, 1e-12)
    approx(pa.hops_to_center(pa.place_linear(8)), 2.0, 1e-12)


def test_setting_spread_is_3x():
    vals = [fn(pf(8)) for pf in (pa.place_grid, pa.place_linear)
            for fn in pa.DISTANCE_MODELS.values()]
    approx(max(vals) / min(vals), 3.0, 1e-9)


def _pa_total(place_fn, ref_hops):
    levels = {"router": {"fanout": 8, "unit_pJ": 48.3, "volume": 10,
                         "energy_J": 2.668e-5}}
    layout = {"router": {"pattern": "to_center", "reference_hops": ref_hops}}
    return pa.position_aware_cost(levels, layout, place_fn)["position_aware"]


def test_placement_ratio_independent_of_reference_hops():
    """ratios must cancel the calibration constant (DR-4 hygiene)."""
    for ref in (1.0, 2.7):
        ratio = _pa_total(pa.place_linear, ref) / _pa_total(pa.place_grid, ref)
        approx(ratio, 2.0 / 1.3125, 1e-9)


def test_absolute_scales_inversely_with_reference_hops():
    approx(_pa_total(pa.place_grid, 2.0), _pa_total(pa.place_grid, 1.0) / 2.0, 1e-9)


def test_hop_latency_monotone_up_the_tree():
    """unit COSTS must be non-decreasing toward upper levels (bandwidth is
    exempt from this assertion -- it runs the other way)."""
    order = ["core<->crossbar", "macro<->core", "glb<->macro"]   # bottom -> top
    vals = [mlx.HOP_LATENCY_NS[k] for k in order]
    assert vals == sorted(vals), f"hop latency not monotone up the tree: {vals}"


def test_propagation_latency_golden():
    """The legacy worst-case geometry (12 / 3 / 2 hops -> 136 ns per operator)
    is the 3x3 grids' -- the default fabric up to C27, kept as the comparison
    variant. The fill-exact 2x4 / 4x2 default (C27) has longer worst-case
    paths: 16 / 4 / 2 hops -> 180 ns per operator, the +6 us of propagation
    on the 826 ms prefill stack between the v5 and v6 fixtures."""
    import scripts.crossbar_comm as cc
    from scripts import fabric
    f3 = fabric.from_yaml("/home/workspace/models/fabric/mlx300_3x3.yaml")
    hops = cc.level_max_hops(f3)
    assert set(hops) == {"glb<->macro", "macro<->core", "core<->crossbar"}
    approx(hops["glb<->macro"], 12.0, 1e-9)
    approx(hops["macro<->core"], 3.0, 1e-9)
    approx(hops["core<->crossbar"], 2.0, 1e-9)
    lat = pa.position_aware_latency(hops, mlx.HOP_LATENCY_NS)
    approx(lat["total_ns"], 136.0, 1e-9)
    hops24 = cc.level_max_hops(fabric.default())
    approx(hops24["glb<->macro"], 16.0, 1e-9)
    approx(hops24["macro<->core"], 4.0, 1e-9)
    approx(hops24["core<->crossbar"], 2.0, 1e-9)
    approx(pa.position_aware_latency(hops24, mlx.HOP_LATENCY_NS)["total_ns"], 180.0, 1e-9)