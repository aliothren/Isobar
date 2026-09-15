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
    """L1: the constrained optimum is the smallest feasible k (T_decode
    is monotone increasing in k -- each cut adds a decode fee), the
    B = 120 ms proposal BITES (k* = 8 != unconstrained k = 1), and the
    first-bite edge at 921.11 ms behaves on both sides."""
    c = sl.constrained(sl.B_PREFILL_S)
    tds = [r["t_decode_s"] for r in sorted(c["table"],
                                           key=lambda r: r["k"])]
    assert all(b > a for a, b in zip(tds, tds[1:]))
    feas_ks = [r["k"] for r in c["table"] if r["feasible"]]
    assert c["opt"]["k"] == min(feas_ks) == 8
    assert c["unconstrained_k"] == 1
    assert sl.constrained(0.922)["opt"]["k"] == 1     # just above the edge
    assert sl.constrained(0.921)["opt"]["k"] == 2     # just below


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


def test_l3_backfill_identity_at_reference_hops():
    """L3: fees at hops = 1 differ from the reference only by the 20 ns
    propagation term -- no cut decision changes, shift < 1e-6."""
    inst, meta = sd.standing_instance()
    ns = se.NS_PER_HOP_D2D * 1e-9
    fees = tuple(0.0 if b == 0 else meta["fee_s"] + 1.0 * ns
                 for b in range(meta["L"]))
    inst1 = sd.Instance(taus=inst.taus, fees=fees, G=inst.G,
                        budget=inst.budget)
    for k in (2, 8, 32):
        v_ref, p_ref = sd.solve(inst, k, "pipe")
        v_act, p_act = sd.solve(inst1, k, "pipe")
        assert [i for i, _, _ in p_ref] == [i for i, _, _ in p_act]
        assert abs(v_act - v_ref) / v_ref < 1e-6
