"""S3 day 7 (C64-d): the ordering instance's pins (group 51).

P1 identity anchor -- the objective reproduces the FILED check-C
ladder before any search runs; P2 incremental == full along engine
walks (the spec section 8(a) line-load structure's pin); P3 J sees
stage unions only (within-stage op swaps are exactly invariant);
P4 the control-leg anchor. Official numbers come from the script,
not from here.
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from scripts import search_baselines as sb
from scripts import search_ordering as so
from scripts import search_sa as sa


def _J(pairs):
    W = so.host()
    return W, so.CrossTrafficJ(W, pairs)


def test_p1_objective_reproduces_the_filed_fanout_ladder():
    """P1: every named rung equals the filed check-C fan-out column
    (2-decimal file tolerance) AND the incremental value equals the
    independent full link_occupancy evaluation."""
    W, J = _J(so.pairs_fanout())
    for name, filed in so.FILED_FANOUT_M.items():
        pi = sb.generate(name, W, seed=0)
        j = J(pi)
        assert abs(j / 1e6 - filed) < 0.005, (name, j)
    for name in ("clustered", "random"):
        pi = sb.generate(name, W, seed=0)
        j = J(pi)
        full = J.full_check(pi)
        assert abs(j - full) <= 1e-9 * full


def test_p2_incremental_matches_full_along_engine_walks():
    """P2: the line-load structure stays exactly on the full evaluation
    across engine-generated moves (exchange / migrate / swap), checked
    at several points along a random walk."""
    W, J = _J(so.pairs_fanout())
    pi = sb.generate("snake", W, seed=0)
    J(pi)
    rng = random.Random(17)
    for step in range(24):
        delta, _ = sa.propose(rng, pi.seat, 576)
        if delta is None:
            continue
        pi = sa.apply_delta(pi, delta)
        j = J(pi)
        if step % 6 == 5:
            full = J.full_check(pi)
            assert abs(j - full) <= 1e-9 * full
    assert all(c >= 0 for c in J.load.values())     # exact counts


def test_p3_within_stage_op_swap_is_invariant():
    """P3: J depends on stage unions only -- swapping the seats of two
    same-size ops INSIDE one layer leaves J exactly unchanged (integer
    counts: exact equality, not tolerance)."""
    W, J = _J(so.pairs_fanout())
    pi = sb.generate("sequential", W, seed=0)
    j0 = J(pi)
    a, b = "ffn1@L3", "ffn2@L3"                     # same layer, both 5
    assert len(pi.seat[a]) == len(pi.seat[b])
    pi2 = sa.apply_delta(pi, {a: tuple(sorted(pi.seat[b])),
                              b: tuple(sorted(pi.seat[a]))})
    assert J(pi2) == j0


def test_p4_control_chain_anchor():
    """P4: the control leg reproduces the filed check-C chain column."""
    W, J = _J(so.pairs_chain())
    for name in ("clustered", "snake", "sequential"):
        pi = sb.generate(name, W, seed=0)
        assert abs(J(pi) / 1e6 - so.FILED_CHAIN_M[name]) < 0.005
