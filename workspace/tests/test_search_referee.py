"""S6 day 11 (C64-f): the referee-family gates R1-R5 (group 55).
Arm argmin runs are day 12; today gates the arms themselves."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from scripts import check_c_crosstraffic as cx
from scripts import search_baselines as sb
from scripts import search_referee as sr
from scripts import search_space as ss


def _named(W, names=("clustered", "snake", "random")):
    return {n: sb.generate(n, W, seed=0) for n in names}


def test_r1_e2_is_the_chain_component_of_e0():
    W = cx.host()
    E0, E2 = sr.MixJ(W, sr.MU), sr.make_E2(cx.host())
    chain_leg = sr.MixJ(cx.host(), {"chain": 1.0})
    for pi in _named(W).values():
        assert abs(E2(pi) - chain_leg(pi)) == 0.0
        # and E0 = 0.5*chain + 0.5*fanout by construction
        fan = sr.MixJ(cx.host(), {"fanout": 1.0})
        assert abs(E0(pi) - 0.5 * E2(pi) - 0.5 * fan(pi)) < 1e-6


def test_r2_e3_is_ring_hosted_and_not_degenerate():
    E3a, E3b = sr.make_E3(), sr.make_E3()
    E0 = sr.make_E0()
    W = cx.host()
    pis = _named(W)
    vals_a = {n: E3a(pi) for n, pi in pis.items()}
    vals_b = {n: E3b(pi) for n, pi in pis.items()}
    assert vals_a == vals_b                        # deterministic
    assert any(abs(vals_a[n] - E0(pi)) > 1e-3
               for n, pi in pis.items())           # a different judge
    assert len(set(vals_a.values())) > 1           # not flat: it can choose
    assert next(iter(E3a.legs.values())).W.fab.name.startswith(
        "xtraffic-ring")


def test_r3_e1_hand_check_on_a_tiny_seating():
    """E1 arithmetic by hand: two stages of one die each at (0,0) and
    (3,4) -> centroid distance 7; chain pair volume V at weight 0.5;
    the fanout pattern has no pair for a 2-stage chain."""
    W = cx.host()
    E1 = sr.make_E1(W)
    assert E1(sb.generate("sequential", W)) > 0
    # exact hand case: two 1-die stages at (0,0) and (3,4) -> centroid
    # Manhattan distance 3 + 4 = 7; one chain pair at weight 1
    xy = E1.slots
    idx_of = {tuple(map(int, xy[i])): i for i in range(len(xy))}
    pi2 = ss.Pi(n_blocks=2, cuts=(1, 2),
                seat={"qkv_proj@L0": (idx_of[(0, 0)],),
                      "qkv_proj@L1": (idx_of[(3, 4)],)})
    val = sr.DistanceProxyJ(W, {"chain": 1.0})(pi2)
    assert abs(val - sr.so.V * 7.0) < 1e-9


def test_r4_isolation_probe_rankings_differ():
    """R4: the arms rank the named seatings differently -- from the
    filed arithmetic E1's top pick (compact) cannot match E0's mix top
    (dispersed end)."""
    W = cx.host()
    pis = {n: sb.generate(n, W, seed=0)
           for n in ("clustered", "sequential", "random")}
    E0, E1 = sr.make_E0(), sr.make_E1()
    top0 = min(pis, key=lambda n: E0(pis[n]))
    top1 = min(pis, key=lambda n: E1(pis[n]))
    assert top1 == "clustered"
    assert top0 != top1


def test_r5_arms_deterministic():
    W = cx.host()
    pi = sb.generate("snake", W, seed=0)
    for name in sr.ARMS:
        assert sr.make_arm(name)(pi) == sr.make_arm(name)(pi)


def test_r6_e2b_is_the_fanout_component_of_e0():
    """The day-11 review's symmetric one-hot arm: E2b == the fan-out
    leg of E0 (identity by construction, mirroring R1)."""
    W = cx.host()
    E2b = sr.make_E2b(cx.host())
    fan = sr.MixJ(cx.host(), {"fanout": 1.0})
    for n in ("clustered", "random"):
        pi = sb.generate(n, W, seed=0)
        assert E2b(pi) == fan(pi)
