"""The simulated-annealing search over the die seating alpha.

The engine anneals the SEATING of a Pi at FIXED cuts (the layer grouping
gamma belongs to the interval DP, search_dp.py); every operator here
preserves cuts, set sizes and slot disjointness BY CONSTRUCTION, so
legality never degrades along a trajectory.

Three operator families:
  exchange   -- "permutation": one slot of set a <-> one slot of set b;
  migrate    -- one slot of a set to a TARGET slot: a free target is the
                plain move, an occupied target is the TWO-STEP
                evict+place (the displaced slot returns to the vacated
                seat). On a capacity-saturated host (e.g. 48 units on
                48 slots) every migration IS the two-step form by
                construction, not a special case;
  swap       -- whole-set pairwise, equal sizes only (the NMAP-style
                family; unequal sizes are skipped, never coerced).

Acceptance: Metropolis on a parameterized geometric schedule
(t(k) = t0 * alpha^k; t0 = 0 is the greedy mode: only strict
improvements accepted). Constrained mode is REJECTION: an infeasible
proposal is rejected and COUNTED, never penalized -- J semantics stay
pure. Multi-start runs the same schedule from an explicit set of start
layouts (which should include at least one feasible named baseline).
Everything is deterministic given the RNG seed; Schedule.tie_draw selects
between the two random-stream settings of the acceptance test (see
Schedule).

The objective is a plain callable J(pi) -> float. Incremental
evaluation is the evaluator's affair (objective.Objective re-scores only
the hand-offs a move touches; its incremental result equals the full
evaluation).

`constructive_path(pi_a, pi_b)` returns a list of engine deltas
transforming a into b (every intermediate legal, length <= the
mismatched-slot count): every path step is a member of the proposal
families with positive probability, so the chain is irreducible over
legal seatings at fixed cuts.
"""
import dataclasses as dc
import math
import os
import random
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import search_space as ss

FAMILIES = ("exchange", "migrate", "swap")


# ------------------------------------------------------------- proposals
def _sorted_but(tup, drop, add):
    return tuple(sorted([s for s in tup if s != drop] + [add]))


def propose(rng: random.Random, seat: Dict[str, Tuple[int, ...]],
            n_slots: int, families=FAMILIES):
    """One proposal -> (delta, kind); delta = {set: new sorted tuple}.
    Sizes and disjointness preserved by construction. May return
    (None, kind) when the drawn family has no legal instance (e.g. swap
    with all sizes distinct) -- the caller just redraws."""
    names = sorted(seat)
    kind = families[rng.randrange(len(families))]
    if kind == "exchange":
        a, b = rng.sample(names, 2)
        x = seat[a][rng.randrange(len(seat[a]))]
        y = seat[b][rng.randrange(len(seat[b]))]
        return {a: _sorted_but(seat[a], x, y),
                b: _sorted_but(seat[b], y, x)}, kind
    if kind == "migrate":
        a = names[rng.randrange(len(names))]
        x = seat[a][rng.randrange(len(seat[a]))]
        owner = {s: n for n in names for s in seat[n]}
        universe = range(n_slots) if isinstance(n_slots, int) else n_slots     # a collection = the usable slots (unit nodes excluded)
        targets = [t for t in universe if t not in seat[a]]
        t = targets[rng.randrange(len(targets))]
        if t not in owner:                        # free target: plain move
            return {a: _sorted_but(seat[a], x, t)}, kind
        b = owner[t]                              # occupied: two-step
        return {a: _sorted_but(seat[a], x, t),
                b: _sorted_but(seat[b], t, x)}, kind
    # swap: whole sets, equal sizes only
    a = names[rng.randrange(len(names))]
    peers = [b for b in names if b != a and len(seat[b]) == len(seat[a])]
    if not peers:
        return None, kind
    b = peers[rng.randrange(len(peers))]
    return {a: tuple(sorted(seat[b])), b: tuple(sorted(seat[a]))}, kind


def apply_delta(pi: ss.Pi, delta: Dict[str, Tuple[int, ...]]) -> ss.Pi:
    return dc.replace(pi, seat={**pi.seat, **delta})


# ------------------------------------------------------ constructive path
def constructive_path(pi_a: ss.Pi, pi_b: ss.Pi
                      ) -> List[Dict[str, Tuple[int, ...]]]:
    """Engine deltas transforming pi_a's seating into pi_b's (same sets,
    same sizes, same cuts). Monotone: every delta fixes at least one
    mismatched slot and never unfixes one, so len(path) <= the initial
    mismatch count. Every delta is an exchange or a migrate -- members
    of the proposal families."""
    if sorted(pi_a.seat) != sorted(pi_b.seat):
        raise ValueError("seatings name different sets")
    for n in pi_a.seat:
        if len(pi_a.seat[n]) != len(pi_b.seat[n]):
            raise ValueError(f"set {n}: sizes differ")
    seat = {n: tuple(sorted(v)) for n, v in pi_a.seat.items()}
    target_owner = {s: n for n, v in pi_b.seat.items() for s in v}
    deltas = []
    while True:
        owner = {s: n for n, v in seat.items() for s in v}
        mism = sorted(s for s, b in target_owner.items()
                      if owner.get(s) != b)
        if not mism:
            break
        s = mism[0]
        b = target_owner[s]
        # a slot b holds now but does not keep -- exists by counting
        x = min(t for t in seat[b] if target_owner.get(t) != b)
        if s in owner:                            # exchange s <-> x
            a = owner[s]
            delta = {a: _sorted_but(seat[a], s, x),
                     b: _sorted_but(seat[b], x, s)}
        else:                                     # s free: migrate x -> s
            delta = {b: _sorted_but(seat[b], x, s)}
        seat.update(delta)
        deltas.append(delta)
    return deltas


# ------------------------------------------------------------ the anneal
@dataclass(frozen=True)
class Schedule:
    t0: float = 1.0               # 0.0 = greedy (strict improvements only)
    alpha: float = 0.995
    steps: int = 2000
    # a move whose cost change is non-positive is always accepted; tie_draw
    # says whether such a move still consumes one draw of the random stream
    # (True: the stream of the paper's confirmation runs; False: the stream
    # of the runs marked sa_tie_draw = False in run_experiments.py). The
    # accepted moves are the same either way; only the subsequent proposals
    # differ, so a seed reproduces a run only under the same setting.
    tie_draw: bool = True


@dataclass
class SAResult:
    best_pi: ss.Pi
    best_j: float
    start_j: float
    accepted: int = 0
    proposed: int = 0
    rejected_infeasible: int = 0
    no_instance: int = 0          # drawn family had no legal instance
    kind_counts: Dict[str, int] = field(default_factory=dict)


def anneal(J: Callable[[ss.Pi], float], pi0: ss.Pi, n_slots: int,
           schedule: Schedule = Schedule(), seed: int = 0,
           families=FAMILIES,
           feasible: Optional[Callable[[ss.Pi], bool]] = None) -> SAResult:
    rng = random.Random(seed)
    pi, j = pi0, J(pi0)
    if feasible is not None and not feasible(pi0):
        raise ValueError("infeasible start: the seed set must contain a "
                         "feasible solution (section-6 guardrail)")
    res = SAResult(best_pi=pi, best_j=j, start_j=j)
    for k in range(schedule.steps):
        t = schedule.t0 * (schedule.alpha ** k)
        delta, kind = propose(rng, pi.seat, n_slots, families)
        res.proposed += 1
        res.kind_counts[kind] = res.kind_counts.get(kind, 0) + 1
        if delta is None:
            res.no_instance += 1
            continue
        pi2 = apply_delta(pi, delta)
        if feasible is not None and not feasible(pi2):
            res.rejected_infeasible += 1
            continue
        j2 = J(pi2)
        dj = j2 - j
        if schedule.tie_draw:
            accept = dj < -1e-15 or (t > 0.0 and rng.random() < (1.0 if dj <= 0.0 else math.exp(-dj / t)))
        else:
            accept = dj <= 0.0 or (t > 0.0 and rng.random() < math.exp(-dj / t))
        if accept:
            pi, j = pi2, j2
            res.accepted += 1
            if j < res.best_j - 1e-15:
                res.best_pi, res.best_j = pi, j
    return res


def multistart(J, seeds: Dict[str, ss.Pi], n_slots: int,
               schedule: Schedule = Schedule(), seed: int = 0,
               families=FAMILIES, feasible=None
               ) -> Tuple[str, Dict[str, SAResult]]:
    """One anneal per named seed (each start's RNG derived from the base
    seed + the seed's name, deterministic); returns (best start's name,
    all results). Ties break on the seed name (sorted order)."""
    out = {}
    for i, name in enumerate(sorted(seeds)):
        out[name] = anneal(J, seeds[name], n_slots, schedule,
                           seed=seed * 1000003 + i, families=families,
                           feasible=feasible)
    best = min(sorted(out), key=lambda n: out[n].best_j)
    return best, out
