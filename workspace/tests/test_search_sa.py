"""S3 day 6 (C64-d): the SA-body engine gates G1-G5 (group 50).

Correctness gates, not findings: the pre-registration declares a
failed gate a bug to fix and record, never a bookable flip. The toy
objectives here are DECLARED MEANINGLESS (they exercise machinery;
their numbers are not readings). No instance runs on day 6.
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
sys.path.insert(0, WS)

from scripts import analyze_d2d as d2d
from scripts import fabric
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_sa as sa
from scripts import search_space as ss


def _w355():
    return se.Workload355M(fabric.from_yaml(d2d.MULTI), 256.0)


def _w27():
    return se.Workload2p7B()


def _toy_J(pi):
    """Declared-meaningless toy: weighted slot-index sum (unit u wants a
    low slot index, heavier with u)."""
    return float(sum((int(n[4:]) + 1) * min(v) for n, v in pi.seat.items()))


# ------------------------------------------------------------------- G1
def test_g1_random_walks_stay_legal():
    """G1: every state visited by random operator walks is legal(), both
    classes, all three families (sizes/disjointness by construction)."""
    for W, steps in ((_w355(), 120), (_w27(), 60)):
        inv = W.inventory()
        n_slots = W.fab.level("die").per_parent
        pi = sb.generate("snake", W)
        rng = random.Random(7)
        for _ in range(steps):
            delta, kind = sa.propose(rng, pi.seat, n_slots)
            if delta is None:
                continue
            pi = sa.apply_delta(pi, delta)
            ok, why = ss.legal(pi, W.fab, inv)
            assert ok, f"{kind}: {why}"


def test_g1_saturated_migration_is_two_step():
    """On the saturated 355M host every migrate proposal must be the
    two-step form (two sets touched) -- no slot is ever free."""
    W = _w355()
    pi = sb.generate("snake", W)
    rng = random.Random(3)
    seen = 0
    for _ in range(200):
        delta, kind = sa.propose(rng, pi.seat, 48, families=("migrate",))
        assert delta is not None and len(delta) == 2
        seen += 1
    assert seen == 200


# ------------------------------------------------------------------- G2
def test_g2_scoresession_matches_full_on_engine_deltas():
    """G2: incremental == full extends to ENGINE-generated deltas
    (exchange / two-step migrate / free-slot migrate / whole-set swap),
    not just the S1 pin's random swaps."""
    W = _w27()
    pi = sb.generate("snake", W)
    n_slots = W.fab.level("die").per_parent
    sess = se.ScoreSession(pi, W)
    rng = random.Random(11)
    checked = 0
    while checked < 12:
        delta, _ = sa.propose(rng, sess.pi.seat, n_slots)
        if delta is None:
            continue
        inc = sess.update(delta)
        full = se.score(sess.pi, W)
        assert abs(inc.t_opt_s - full.t_opt_s) < 1e-12
        assert abs(inc.e_J - full.e_J) < 1e-12
        checked += 1


# ------------------------------------------------------------------- G3
def test_g3_greedy_monotone_and_deterministic():
    """G3: t0=0 accepts only strict improvements (best == final, never
    above start), and same-seed reruns are bit-identical."""
    W = _w355()
    pi0 = sb.generate("sequential", W)
    sched = sa.Schedule(t0=0.0, steps=400)
    r1 = sa.anneal(_toy_J, pi0, 48, sched, seed=5)
    r2 = sa.anneal(_toy_J, pi0, 48, sched, seed=5)
    assert r1.best_j <= r1.start_j
    assert r1.best_j < r1.start_j          # the toy space is improvable
    assert r1.best_pi.seat == r2.best_pi.seat and r1.best_j == r2.best_j
    assert (r1.accepted, r1.proposed) == (r2.accepted, r2.proposed)
    r3 = sa.anneal(_toy_J, pi0, 48, sched, seed=6)
    assert r3.proposed == r1.proposed      # same budget, any outcome


def test_g3_metropolis_still_tracks_best():
    """At t>0 worse moves may be accepted, but best_j is monotone and
    <= start; the returned best must reproduce its own J."""
    W = _w355()
    pi0 = sb.generate("random", W, seed=1)
    r = sa.anneal(_toy_J, pi0, 48, sa.Schedule(t0=50.0, alpha=0.98,
                                               steps=400), seed=2)
    assert r.best_j <= r.start_j
    assert abs(_toy_J(r.best_pi) - r.best_j) < 1e-12


# ------------------------------------------------------------------- G4
def test_g4_constructive_path_both_classes():
    """G4: constructive_path lands exactly on the target, every
    intermediate legal, length <= initial mismatch count."""
    cases = [(_w355(), ("snake", "random"), 1),
             (_w355(), ("sequential", "clustered"), 4),
             (_w27(), ("snake", "clustered"), 0),
             (_w27(), ("sequential", "random"), 3)]
    for W, (na, nb), seedb in cases:
        inv = W.inventory()
        a = sb.generate(na, W, seed=0)
        b = sb.generate(nb, W, seed=seedb)
        mismatch = sum(1 for n in b.seat for s in b.seat[n]
                       if s not in a.seat[n])
        path = sa.constructive_path(a, b)
        assert len(path) <= mismatch
        pi = a
        for delta in path:
            pi = sa.apply_delta(pi, delta)
            ok, why = ss.legal(pi, W.fab, inv)
            assert ok, why
        assert {n: tuple(sorted(v)) for n, v in pi.seat.items()} == \
               {n: tuple(sorted(v)) for n, v in b.seat.items()}


def test_g4_path_refuses_mismatched_inventories():
    W = _w355()
    a = sb.generate("snake", W)
    bad = ss.Pi(n_blocks=a.n_blocks, cuts=a.cuts,
                seat={**a.seat, "unit0": a.seat["unit0"] + (99,)})
    try:
        sa.constructive_path(a, bad)
        assert False, "sizes differ: must refuse"
    except ValueError:
        pass


# ------------------------------------------------------------------- G5
def test_g5_rejection_mode_never_accepts_infeasible():
    """G5: with a feasibility predicate, no visited-accepted state is
    infeasible; rejections are counted, never penalized (J untouched)."""
    W = _w355()
    pi0 = sb.generate("sequential", W)

    def feas(pi):                     # toy constraint: unit0 stays low
        return pi.seat["unit0"][0] < 8

    assert feas(pi0)
    r = sa.anneal(_toy_J, pi0, 48, sa.Schedule(t0=30.0, alpha=0.98,
                                               steps=400), seed=9,
                  feasible=feas)
    assert feas(r.best_pi)
    assert r.rejected_infeasible > 0
    assert r.proposed == 400

    try:
        sa.anneal(_toy_J, sb.generate("random", W, seed=0), 48,
                  sa.Schedule(steps=1), seed=0,
                  feasible=lambda pi: False)
        assert False, "infeasible start must refuse (guardrail)"
    except ValueError:
        pass


# ------------------------------------------------------------ multistart
def test_multistart_deterministic_and_picks_min():
    W = _w355()
    seeds = {n: sb.generate(n, W, seed=0)
             for n in ("sequential", "snake", "random")}
    best1, out1 = sa.multistart(_toy_J, seeds, 48,
                                sa.Schedule(t0=0.0, steps=200), seed=4)
    best2, out2 = sa.multistart(_toy_J, seeds, 48,
                                sa.Schedule(t0=0.0, steps=200), seed=4)
    assert best1 == best2
    assert all(out1[n].best_j == out2[n].best_j for n in seeds)
    assert out1[best1].best_j == min(r.best_j for r in out1.values())
