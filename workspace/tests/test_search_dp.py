"""S4 day 9 (C64-e): the interval DP gates D1-D5 (group 53).

Correctness gates per the day-9 pre-registration: a failed gate is a
bug, not a finding. The synthetic instances are DECLARED MEANINGLESS
(they exercise the DP against brute force; their numbers are not
readings).
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from scripts import search_dp as sd


def _rand_instance(rng, L, G, budget):
    taus = tuple(tuple(rng.uniform(0.5, 2.0) for _ in G) for _ in range(L))
    fees = tuple(0.0 if b == 0 else rng.uniform(0.0, 0.8)
                 for b in range(L))
    return sd.Instance(taus=taus, fees=fees, G=tuple(G), budget=budget)


def test_d1_dp_equals_brute_force_on_synthetic_instances():
    """D1: exact optimality vs exhaustive enumeration -- heterogeneous
    taus, random fees, randomly-thinned sparse G, both calibers."""
    rng = random.Random(9)
    for trial in range(6):
        L = rng.randrange(4, 8)
        G = sorted(rng.sample([1, 2, 3, 5, 7], rng.randrange(2, 4)))
        budget = L * max(G) - rng.randrange(0, L)
        inst = _rand_instance(rng, L, G, budget)
        for k in (1, 2, 3):
            for caliber in ("pipe", "single"):
                v_dp, plan = sd.solve(inst, k, caliber)
                v_bf = sd.brute(inst, k, caliber)
                assert abs(v_dp - v_bf) < 1e-12, (trial, k, caliber)
                if plan:
                    assert sum((j - i) * g for i, j, g in plan) \
                        <= inst.budget


def test_d2_sparse_axis_honored_and_o10_echo():
    """D2: a size absent from G never appears in a plan; the layer-level
    O10 echo -- 16 absent, 17 present, the set sparse."""
    G = sd.layer_feasible_sizes()
    assert 17 in G and 16 not in G
    assert G == sorted(set(G))
    rng = random.Random(3)
    inst = _rand_instance(rng, 6, [2, 5], 30)
    for k in (1, 2, 3):
        _, plan = sd.solve(inst, k, "pipe")
        assert all(g in (2, 5) for _, _, g in plan)


def test_d3_uniform_degeneracy_and_single_k1():
    """D3 (re-scoped after the accounting review): on the UNIFORM-LAYER
    reference instance the DP lands on balanced cuts with minimal
    g = 17 everywhere -- the structural degeneracy claim; on the
    standing seating (per-layer times now seat-dependent) only the
    re-price and the single-caliber k = 1 preference are asserted."""
    u, um = sd.uniform_reference_instance()
    for k in (2, 4, 8):
        v, plan = sd.solve(u, k, "pipe")
        sizes = sorted(j - i for i, j, _ in plan)
        m = um["L"] // k
        assert sizes == sorted([m] * k) or max(sizes) - min(sizes) == 1
        assert all(g == 17 for _, _, g in plan)
        assert abs(v - (m * um["tau"] + um["fee"])) < 1e-12
    inst, meta = sd.standing_instance()
    v1, _ = sd.solve(inst, 1, "single")
    v2, _ = sd.solve(inst, 2, "single")
    assert abs(v1 - v2) < 1e-12        # cutting is free: single is cut-blind
    assert abs(v1 - (sum(t[0] for t in inst.taus))) < 1e-12


def test_d3b_standing_costs_are_the_evaluator_s():
    """The DP == EVALUATOR identity (the third mismatch's pin): at the
    A4 seating, (a) the DP's single-caliber total + propagation equals
    the evaluator's serial latency, and (b) for balanced plans at
    k in {2, 8, 32} the DP's pipe interval equals the evaluator's pipe
    interval on a Pi carrying those very cuts -- both to 1e-9."""
    import dataclasses as dc
    from scripts import search_eval as se
    from scripts import search_space as ss
    inst, meta = sd.standing_instance()
    W = se.Workload2p7B()
    pi = ss.pi_from_a4_payload()
    sc = se.score(pi, W, caliber="single", d2d_gbps=sd.GRS_GBPS)
    v1, _ = sd.solve(inst, 1, "single")
    prop = sc.per_phase["prefill"]["decomp"]["propagation_s"]
    assert abs(v1 + prop - sc.t_opt_s) < 1e-9 * sc.t_opt_s
    for k in (2, 8, 32):
        v, plan = sd.solve(inst, k, "pipe")
        cuts = tuple(j for _, j, _ in plan)            # segment ends
        pik = dc.replace(pi, cuts=cuts)
        sp = se.score(pik, W, caliber="pipe", d2d_gbps=sd.GRS_GBPS)
        assert abs(v - sp.t_opt_s) < 1e-9 * sp.t_opt_s


def test_d4_determinism_and_budget_accounting():
    inst, meta = sd.standing_instance()
    v_a, p_a = sd.solve(inst, 8, "pipe")
    v_b, p_b = sd.solve(inst, 8, "pipe")
    assert v_a == v_b and p_a == p_b
    assert sum((j - i) * g for i, j, g in p_a) == 544     # 17 x 32


def test_d5_reconstruction_reprices_exactly():
    """D5: solve() itself asserts the re-price; exercise it on a
    heterogeneous instance too (the assert inside solve is the gate)."""
    rng = random.Random(21)
    inst = _rand_instance(rng, 7, [1, 3, 5], 35)
    for k in (2, 3, 4):
        v, plan = sd.solve(inst, k, "pipe")
        assert plan and v < sd.INF
