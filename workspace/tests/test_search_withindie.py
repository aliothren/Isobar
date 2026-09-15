"""S3 day 8 (C64-d): the within-die instance's pins (group 52).

W1 identity anchor -- the recomputed A3 fold reproduces the STORED
soft_lever.json a3_cells rows (the C49-b numbers) before any SA;
W2 the SA reaches the exhaustive optimum on the active cell (the
E-W1 expectation, pinned on the prefill/attn case);
W3 the safe cell (g = 2.0) is all-ties (the realized safe-cell
control of the S3 pre-registration).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from scripts import search_sa as sa
from scripts import search_withindie as sw


def test_w1_fold_reproduces_stored_a3_cells():
    stored = json.load(open(os.path.join(sw.A, "soft_lever.json")))
    fold = sw.fold_anchor_check()
    for phase, rows in fold.items():
        for mine, theirs in zip(rows, stored["phases"][phase]["a3_cells"]):
            for k in ("a3_stack_ratio", "a3_mech_ratio_attn",
                      "a3_mech_ratio_ffn"):
                assert abs(mine[k] - theirs[k]) <= 1e-9 * max(theirs[k], 1.0)


def test_w2_sa_hits_the_exhaustive_optimum():
    J = sw.WithinDieJ("attn", "prefill", sw.G_ACTIVE)
    ex = J.exhaustive()
    best_j = ex[0][0]
    pi0 = sw.mk_pi(sw.SHIPPED["attn"])
    r = sa.anneal(J, pi0, 8,
                  sa.Schedule(t0=0.02 * J.cost_of(sw.SHIPPED["attn"]),
                              alpha=0.98, steps=400), seed=0)
    assert abs(r.best_j - best_j) <= 1e-12 * best_j


def test_w3_safe_cell_is_all_ties():
    J = sw.WithinDieJ("ffn", "prefill", sw.G_SAFE)
    ex = J.exhaustive()
    assert abs(ex[-1][0] - ex[0][0]) <= 1e-15 * ex[0][0]
