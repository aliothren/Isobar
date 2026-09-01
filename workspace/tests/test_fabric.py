"""Group 9 -- the fabric config: single source of truth for physical structure.

A-1 must not move any number: the legacy constants derived from the config must
equal the values that were hardcoded before, and a bad config must refuse to
load.
"""
from _util import approx, fixture

from scripts import fabric
from scripts.fabric import Fabric, Level, Link


def test_mlx300_matches_legacy_constants():
    f = fabric.default()
    assert f.level("macro").per_parent == 8
    assert f.level("core").per_parent == 4
    assert f.level("crossbar").per_parent == 8
    assert f.count_below("crossbar") == 256
    assert f.count_below("die") == 1


def test_derived_dicts_unchanged():
    from scripts import mlx_system as mlx
    assert mlx.HOP_LATENCY_NS == {"glb<->macro": 5.0, "macro<->core": 2.0,
                                  "core<->crossbar": 1.0}
    assert mlx.LAYOUT == {"router": {"topology": "mesh_2d",
                                     "pattern": "to_center", "hop_scale": 1.0,
                                     "hop_latency_ns": 1.0,
                                     "reference_hops": 1.0}}
    from scripts import llm_workload as lw
    approx(lw.DIE_HOP_LATENCY_NS, 20.0, 1e-12)


def test_bandwidth_fields_default_to_unlimited():
    """the shipped config must not activate any stall tier."""
    f = fabric.default()
    for lv in f.levels:
        assert lv.hub_bandwidth_words_per_cycle is None
        if lv.link is not None:
            assert lv.link.bandwidth_words_per_cycle is None


def test_slots_row_major():
    f = fabric.default()                                   # C27: the fill-exact 2x4 / 4x2 grids
    assert f.slots("macro")[:4] == [(0, 0), (1, 0), (0, 1), (1, 1)]
    assert len(f.slots("macro")) == 8 and f.level("macro").mesh == (2, 4)
    assert f.level("crossbar").mesh == (4, 2) and len(f.slots("crossbar")) == 8
    f3 = fabric.from_yaml("/home/workspace/models/fabric/mlx300_3x3.yaml")   # the comparison variant
    assert f3.slots("macro")[:4] == [(0, 0), (1, 0), (2, 0), (0, 1)]
    assert len(f3.slots("macro")) == 8          # 3x3 grid, one slot empty


def test_verify_against_frozen_stats():
    from scripts import placement_aware as pa
    levels = pa.perceive(fixture("ffn1_prefill_stats.txt"))
    hier = {"n_macros": levels["router"]["fanout"],
            "n_cores": 32, "n_crossbars": 256}
    fabric.default().verify_against_stats(hier)         # must not raise


def test_bad_configs_refuse_to_load():
    def build(per_parent=4, mesh=(2, 2), upper_ns=5.0, lower_ns=1.0):
        return Fabric(name="bad", levels=[
            Level("die", 1, (1, 1), Link("a", upper_ns)),
            Level("core", per_parent, mesh, Link("b", lower_ns)),
        ])

    build().validate()                                   # sane baseline passes
    for kwargs in ({"per_parent": 8, "mesh": (2, 2)},    # more instances than slots
                   {"upper_ns": 1.0, "lower_ns": 5.0},   # cost not monotone upward
                   {"per_parent": 0}):                   # nonsensical count
        try:
            build(**kwargs).validate()
        except ValueError:
            continue
        raise AssertionError(f"bad config accepted: {kwargs}")


def test_mismatched_stats_raise():
    try:
        fabric.default().verify_against_stats(
            {"n_macros": 8, "n_cores": 32, "n_crossbars": 128})
    except ValueError:
        return
    raise AssertionError("diverged stats accepted")

def test_slot_pitch_is_carried_and_validated():
    """slot_pitch_um: platform input with example defaults. Nothing consumes it
    yet; this pins that (a) the shipped configs state it for every meshed
    level, (b) it is monotone up the tree, (c) the validator rejects zero /
    inverted values."""
    import dataclasses
    fab = fabric.default()
    pitched = [lv for lv in fab.levels if lv.slot_pitch_um is not None]
    assert [lv.name for lv in pitched] == ["die", "macro", "core", "crossbar"]
    vals = [lv.slot_pitch_um for lv in pitched]
    assert vals == sorted(vals, reverse=True)          # monotone up the tree
    bad = dataclasses.replace(
        fab, levels=[dataclasses.replace(lv, slot_pitch_um=0.0)
                     if lv.name == "core" else lv for lv in fab.levels])
    try:
        bad.validate()
        raise AssertionError("zero slot_pitch_um must be rejected")
    except ValueError:
        pass
