"""S4 day 10 (C64-e): linkage gates L1-L3 (group 54)."""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from scripts import search_baselines as sb
from scripts import search_dp as sd
from scripts import search_eval as se
from scripts import search_linkage as sl
from scripts import search_sa as sa


def test_l1_constrained_solver_structure_and_bite():
    """L1 (re-scoped to the exact D.2 solver): the solution is feasible
    (every prefill stage <= B), decode never below the unconstrained
    k = 1 sum, a looser budget never costs more decode, the 120 ms
    proposal still BITES (k* > 1), and a budget below the largest
    single-layer stage is infeasible."""
    c = sl.constrained(sl.B_PREFILL_S)
    assert c["feasible"] and c["k"] > 1
    assert c["t_prefill_s"] <= sl.B_PREFILL_S + 1e-12
    assert c["t_decode_s"] >= c["t_decode_unconstrained_s"]
    loose = sl.constrained(2.0)
    assert loose["feasible"] and loose["k"] == 1
    assert loose["t_decode_s"] <= c["t_decode_s"]
    tight = sl.constrained(0.5 * c["meta"]["tau_p_range_s"][0])
    assert not tight["feasible"]


def test_l2_session_e_matches_full_score():
    """L2: the diff-driven SessionE equals the full score's e_J along
    engine-generated deltas (reject-then-move-on sequences included)."""
    W = se.Workload2p7B()
    pi = sb.generate("snake", W)
    J = sl.SessionE(W, pi)
    assert abs(J(pi) - se.score(pi, W, d2d_gbps=sl.GRS).e_J) < 1e-12
    rng = random.Random(5)
    for _ in range(6):
        delta, _ = sa.propose(rng, pi.seat, 576)
        if delta is None:
            continue
        pi = sa.apply_delta(pi, delta)
        assert abs(J(pi) - se.score(pi, W, d2d_gbps=sl.GRS).e_J) < 1e-12


def test_l3_dp_table_is_seat_dependent_and_deterministic():
    """L3 (re-scoped): the D.2 cost table built twice at one seating is
    identical, and built at a different seating differs -- the table
    now carries the seating (intra-layer hand-offs included)."""
    W = se.Workload2p7B()
    a1, m1 = sd.standing_instance()
    a2, m2 = sd.standing_instance()
    assert a1 == a2 and m1["d2d_total_s"] == m2["d2d_total_s"]
    b, mb = sd.standing_instance(sb.generate("random", W, seed=0))
    assert b.taus != a1.taus
    assert abs(mb["d2d_total_s"] - m1["d2d_total_s"]) > 1e-6
