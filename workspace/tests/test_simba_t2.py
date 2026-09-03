"""Group 35 -- T2, the Fig 15 data-placement experiment (C45, step 1,
day 6), governed by SIMBA_PREREG amendment A2 and graded by its criteria
table. As with group 34, the pins freeze the OUTCOME -- including the
double-sided T2b band failure (tier-2, one mechanism both ways; prereg
§8). Moving any number here is a model change that re-opens the triage.
"""
from _util import approx

from scripts.simba_targets import (RESNET50, T2_ACTIVE, T2_CENTER_NODE,
                                   t2_baseline_homes, t2_candidate_splits,
                                   t2_greedy_homes, t2_run)


def test_active_dies_and_center():
    """A2-1/A2-8: row-major first 32; center = (2,2) = node 14."""
    assert T2_ACTIVE == list(range(32))
    assert T2_CENTER_NODE == 14


def test_frozen_splits_and_speedups():
    """The per-layer outcome table, pinned. Frozen tilings come from A2's
    baseline-scored enumeration; speedups are ours (max end) vs the
    figure's pixel-read bars in the prereg record."""
    res = t2_run()
    L = res["layers"]
    assert L["res3a_branch1"]["frozen_split"] == {"K": 2, "P": 4, "Q": 4}
    assert L["res2[a-c]_branch2c"]["frozen_split"] == {"P": 4, "Q": 8}
    assert L["res4a_branch1"]["frozen_split"] == {"K": 32}
    assert L["res2[a-c]_branch2b"]["frozen_split"] == {"K": 32}
    assert L["res5[a-c]_branch2b"]["frozen_split"] == {"K": 32}
    assert L["res4[b-f]_branch2a"]["frozen_split"] == {"K": 2, "C": 4,
                                                      "P": 2, "Q": 2}
    for name, want in (("res3a_branch1", 1.9838), ("res2[a-c]_branch2c", 1.0),
                       ("res4a_branch1", 1.0619), ("res2[a-c]_branch2b", 1.0311),
                       ("res5[a-c]_branch2b", 1.0301),
                       ("res4[b-f]_branch2a", 1.7922)):
        approx(L[name]["speedup_max_end"], want, 1e-3)
    # A3 pessimistic end: speedups COMPRESS toward 1 (the pre-stated
    # direction) -- small gains nearly vanish, the big two soften
    for name, want in (("res3a_branch1", 1.8621), ("res4a_branch1", 1.0134),
                       ("res2[a-c]_branch2b", 1.0068),
                       ("res5[a-c]_branch2b", 1.0067),
                       ("res4[b-f]_branch2a", 1.4981)):
        approx(L[name]["speedup_pess"], want, 1e-3)
    for d in L.values():
        assert d["speedup_pess"] <= d["speedup_max_end"] + 1e-9
    # greedy never LOSES (the tier-3 reversal condition never triggers)
    for d in L.values():
        assert d["speedup_max_end"] >= 1.0 - 1e-12
    # the model's best-gaining layer coincides with the figure's
    best = max(L, key=lambda n: L[n]["speedup_max_end"])
    assert best == "res3a_branch1"


def test_res2c_tie_is_the_self_aligned_baseline():
    """The zero-gain tie on res2[a-c]_branch2c is a declared-convention
    artifact: under the frozen pure-partition tiling the sequential
    baseline is ALREADY data-local (every IA slice and OA block homes on
    its own consumer/producer), so there is nothing for greedy to move --
    recorded in the prereg §8, not regraded."""
    import scripts.simba_targets as st
    op = RESNET50["res2[a-c]_branch2c"]
    _, ia_g, oa_g, _ = st._t2_blocks(op, {"P": 4, "Q": 8}, st.simba_fabric())
    ia_h, oa_h = t2_baseline_homes(len(ia_g), len(oa_g))
    assert all([T2_ACTIVE[i] for i in g] == [h] for g, h in zip(ia_g, ia_h))
    assert all(T2_ACTIVE[g[0]] == h for g, h in zip(oa_g, oa_h))


def test_corner_vs_center_subcase():
    """A2-8: direction holds (center wins) but only through the one-shot
    propagation term -- 1.0044 vs the measured ~1.05, the same degenerate
    class as T1a; serialization itself is position-flat under dedup
    multicast of a single slice (the A2-8 pre-stated risk, realized)."""
    res = t2_run()
    sub = res["res4a_corner_vs_center"]
    assert sub["corner_over_center"] > 1.0
    approx(sub["corner_over_center"], 1.0041, 1e-3)
    approx(sub["corner"]["serialization_s"],
           sub["center"]["serialization_s"], 1e-12)     # position-flat
    # A3: the packet bracket CONTAINS the measured ~1.05 -- the packet
    # term is the position-sensitive piece the optimistic end cannot see.
    # (The A2-8 prereg expectation "~1.78" was an arithmetic slip in h:
    # corner max distance is 9, not 10 -- (5,5) is not an active die;
    # formula and code agree, recorded in the outcome record.)
    approx(sub["corner_over_center_pess"], 1.6220, 1e-3)
    assert sub["corner_over_center"] <= 1.05 <= sub["corner_over_center_pess"]


def test_enumeration_respects_layer_dims():
    """3x3 layers cannot take P/Q chip splits (halo deferral), so their
    candidate set is K x C only; 1x1 layers get the full space."""
    for name in ("res2[a-c]_branch2b", "res5[a-c]_branch2b"):
        for cand in t2_candidate_splits(RESNET50[name]):
            assert set(cand) <= {"K", "C"}, (name, cand)
    assert any("P" in c for c in t2_candidate_splits(RESNET50["res3a_branch1"]))


def test_greedy_is_deterministic():
    op = RESNET50["res3a_branch1"]
    a = t2_greedy_homes(op, {"K": 2, "P": 4, "Q": 4})
    b = t2_greedy_homes(op, {"K": 2, "P": 4, "Q": 4})
    assert a == b
