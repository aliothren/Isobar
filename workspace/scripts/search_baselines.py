"""The named seating baselines (the default fill and the prescribed rules).

Seven generators, ONE signature: generate(name, W, seed) -> Pi. Every
output passes legal(); seeded runs are deterministic. Baselines are
SEATING baselines: gamma ships as singleton cuts (1..L) -- the layer
grouping belongs to the interval DP (search_dp.py), not to a seating
heuristic.

Sources:
  random          -- random fill of the usable slots
  sequential      -- the default fill: operators in chain order onto the
                     slots in row-major order
  snake           -- the standing serpentine
  least_manhattan -- SIAM's rule, collected verbatim: consecutive-level
                     least-Manhattan sequential placement
  clustered       -- Gemini's rectangular clustering (own
                     implementation): one compact rectangle per stage
  nmap_greedy     -- NMAP (DATE 2004), original structure verbatim:
                     dynamic max-comm-with-mapped constructive + ONE
                     fixed O(U^2) pairwise-swap sweep, on NMAP's OWN
                     cost (comm x centroid distance; this cost is used
                     only inside the baseline, never by the evaluator)
  heaviest_first  -- Graham/LPT lineage: heaviest boundary placed onto
                     the least-stretched line available
"""
import os
import random
import sys
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import llm_workload as lw
from scripts import placement as pm
from scripts import search_space as ss

NAMES = ("random", "sequential", "snake", "least_manhattan", "clustered",
         "nmap_greedy", "heaviest_first")


# ------------------------------------------------------------ chain info
def _chain_info(W):
    """(ordered set names, per-set die counts, in-words of the boundary
    INTO each set, layer index of each set) from the workload's declared
    inventory + frozen chain."""
    inv = W.inventory()
    names = list(inv)
    if names[0].startswith("unit"):
        words = {n: 512 * lw.GptConfig().d_model for n in names}
        layer = {n: int(n[4:]) for n in names}
    else:
        base = lw.block_chain(W.cfg, W.S, "prefill", on_chip=getattr(W, "offload", None) is None,
                              max_dies=W.fab.level("die").per_parent,
                              dims=getattr(W, "tiling_dims", ("M", "C")))
        per = {e["name"]: e["in_words"] for e in base}
        words = {n: per[n.rsplit("@L", 1)[0]] for n in names}
        layer = {n: int(n.rsplit("@L", 1)[1]) for n in names}
    return names, dict(inv), words, layer


def _slots_xy(W):
    return pm.sequential_fill(W.fab).slots["die"]


def _usable(W):
    """The slots a die-set may take: every slot of the grid minus the
    reserved unit nodes of an offload configuration."""
    reserved = W.offload.reserved_slots() if getattr(W, "offload", None) is not None else set()
    return [i for i in range(W.fab.level("die").per_parent) if i not in reserved]


def _mk_pi(W, names, inv, order_of_slots):
    seat, cur = {}, 0
    for n in names:
        seat[n] = tuple(order_of_slots[cur:cur + inv[n]])
        cur += inv[n]
    L = (max(int(n.rsplit("@L", 1)[1]) for n in seat) + 1
         if "@L" in names[0] else len(names))
    return ss.Pi(n_blocks=L, cuts=tuple(range(1, L + 1)), seat=seat)


def _centroid(slots_xy, idxs):
    xs = [slots_xy[i][0] for i in idxs]
    ys = [slots_xy[i][1] for i in idxs]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _manh(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# ------------------------------------------------------------ generators
def _gen_random(W, seed):
    names, inv, _, _ = _chain_info(W)
    order = _usable(W)
    random.Random(seed).shuffle(order)
    return _mk_pi(W, names, inv, order)


def _gen_sequential(W, seed):
    names, inv, _, _ = _chain_info(W)
    return _mk_pi(W, names, inv, _usable(W))


def _gen_snake(W, seed):
    names, inv, _, _ = _chain_info(W)
    xy = _slots_xy(W)
    mx, _my = W.fab.level("die").mesh
    order = sorted(_usable(W),
                   key=lambda i: (xy[i][1],
                                  xy[i][0] if xy[i][1] % 2 == 0
                                  else -xy[i][0]))
    return _mk_pi(W, names, inv, order)


def _gen_least_manhattan(W, seed):
    """SIAM: sets in chain order; each set's dies = the free slots nearest
    (Manhattan) to the PREVIOUS set's centroid."""
    names, inv, _, _ = _chain_info(W)
    xy = _slots_xy(W)
    free = set(_usable(W))
    seat, prev_c = {}, xy[0]
    for n in names:
        picks = sorted(free, key=lambda i: (_manh(xy[i], prev_c), i))[:inv[n]]
        seat[n] = tuple(picks)
        free -= set(picks)
        prev_c = _centroid(xy, picks)
    L = (max(int(n.rsplit("@L", 1)[1]) for n in seat) + 1
         if "@L" in names[0] else len(names))
    return ss.Pi(n_blocks=L, cuts=tuple(range(1, L + 1)), seat=seat)


def _gen_clustered(W, seed):
    """RECTANGULAR clustering, as Gemini defines it: a constructive
    rectangle tiling (blob growth would fragment the tail and scatter
    stages). The grid is tiled into equal
    rectangles, one per stage (smallest divisor-pair rectangle that fits
    the stage's die count, enough rectangles for all stages); stages walk
    the rectangle grid in snake order (consecutive stages adjacent);
    within its rectangle a stage takes the first `need` slots row-major
    (dropping trailing corner slots keeps it connected). Connectivity,
    perfect tiling and determinism hold BY CONSTRUCTION."""
    names, inv, _, layer = _chain_info(W)
    xy = _slots_xy(W)
    gw, gh = W.fab.level("die").mesh
    by_layer: Dict[int, List[str]] = {}
    for n in names:
        by_layer.setdefault(layer[n], []).append(n)
    n_stages = len(by_layer)
    need = max(sum(inv[n] for n in members) for members in by_layer.values())
    best = None
    for rw in range(1, gw + 1):
        if gw % rw:
            continue
        for rh in range(1, gh + 1):
            if gh % rh or rw * rh < need:
                continue
            if (gw // rw) * (gh // rh) < n_stages:
                continue
            waste = rw * rh - need
            if best is None or waste < best[0]:
                best = (waste, rw, rh)
    if best is None:
        raise AssertionError(
            f"clustered: no divisor rectangle >= {need} slots tiles the "
            f"{gw}x{gh} grid into >= {n_stages} stages")
    _, rw, rh = best
    idx_of = {(int(x), int(y)): i for i, (x, y) in enumerate(xy)}
    cols, rows = gw // rw, gh // rh
    rects = []
    for ry in range(rows):
        run = list(range(cols)) if ry % 2 == 0 else list(range(cols))[::-1]
        for rx in run:
            rects.append((rx, ry))
    seat = {}
    for si, li in enumerate(sorted(by_layer)):
        rx, ry = rects[si]
        slots = [idx_of[(rx * rw + dx, ry * rh + dy)]
                 for dy in range(rh) for dx in range(rw)]
        cur = 0
        for n in by_layer[li]:
            seat[n] = tuple(slots[cur:cur + inv[n]])
            cur += inv[n]
    L = (max(int(n.rsplit("@L", 1)[1]) for n in seat) + 1
         if "@L" in names[0] else len(names))
    return ss.Pi(n_blocks=L, cuts=tuple(range(1, L + 1)), seat=seat)


def _nmap_cost(seat, names, words, xy):
    c = 0.0
    for prev, cur in zip(names, names[1:]):
        c += words[cur] * _manh(_centroid(xy, seat[prev]),
                                _centroid(xy, seat[cur]))
    return c


def _nmap_construct(W):
    """NMAP initialize(), per the original: the
    set with maximum communication demand is seated at the mesh centre
    (the max-neighbour interior); then, REPEATEDLY, the unmapped set
    communicating most with the already-mapped ones is selected
    (dynamic, not a static descending order) and seated on the free
    slots minimising its comm x distance cost to the mapped sets.
    Multi-die adaptation, declared: a 'core' is a die-set, distance is
    to the mapped neighbour's centroid, and a set takes the cheapest
    `need` slots."""
    names, inv, words, _ = _chain_info(W)
    xy = _slots_xy(W)
    comm = {n: 0.0 for n in names}
    nbr: Dict[str, List] = {n: [] for n in names}
    for prev, cur in zip(names, names[1:]):
        comm[cur] += words[cur]
        comm[prev] += words[cur]
        nbr[prev].append((cur, words[cur]))
        nbr[cur].append((prev, words[cur]))
    free = set(_usable(W))
    cx = (max(x for x, _ in xy) / 2, max(y for _, y in xy) / 2)
    seat = {}
    first = max(names, key=lambda n: comm[n])   # ties: first in chain
    picks = sorted(free, key=lambda i: (_manh(xy[i], cx), i))[:inv[first]]
    seat[first] = tuple(picks)
    free.difference_update(picks)
    while len(seat) < len(names):
        n = max((m for m in names if m not in seat),
                key=lambda m: sum(w for q, w in nbr[m] if q in seat))
        anchors = [(w, _centroid(xy, seat[q])) for q, w in nbr[n]
                   if q in seat]

        def cost(i):
            return sum(w * _manh(xy[i], c) for w, c in anchors)

        picks = sorted(free, key=lambda i: (cost(i), i))[:inv[n]]
        seat[n] = tuple(picks)
        free.difference_update(picks)
    return seat


def _nmap_refine_sweep(seat, names, inv, words, xy):
    """NMAP mappingwithsinglepath(), per the original pseudocode: ONE
    systematic O(U^2) pairwise pass -- outer row i,
    inner j > i, each candidate evaluated against the row's standing
    seating, the best improving swap of the row committed at the row's
    end (Bestmapping -> Placed). The original's termination IS this
    fixed sweep; the earlier run-to-convergence loop was a fidelity bug
    and is reverted. Multi-die adaptation, declared: only equal-size
    sets swap."""
    seat = dict(seat)
    for i, a in enumerate(names):
        bestcost = _nmap_cost(seat, names, words, xy)
        best = None
        for b in names[i + 1:]:
            if inv[a] != inv[b]:
                continue
            seat[a], seat[b] = seat[b], seat[a]
            c = _nmap_cost(seat, names, words, xy)
            seat[a], seat[b] = seat[b], seat[a]
            if c < bestcost - 1e-12:
                bestcost, best = c, b
        if best is not None:
            seat[a], seat[best] = seat[best], seat[a]
    return seat


def _gen_nmap_greedy(W, seed):
    """NMAP (DATE 2004), original three-phase structure: dynamic
    constructive seating (_nmap_construct) + a single fixed pairwise
    sweep (_nmap_refine_sweep) on NMAP's own comm x centroid-distance
    cost. The cost caliber is an adaptation; the SELECTION and TERMINATION
    structure is the original's (Murali and De Micheli, DATE 2004)."""
    names, inv, words, _ = _chain_info(W)
    xy = _slots_xy(W)
    seat = _nmap_refine_sweep(_nmap_construct(W), names, inv, words, xy)
    L = (max(int(n.rsplit("@L", 1)[1]) for n in seat) + 1
         if "@L" in names[0] else len(names))
    return ss.Pi(n_blocks=L, cuts=tuple(range(1, L + 1)), seat=seat)


def _gen_heaviest_first(W, seed):
    """Graham/LPT: boundaries in descending volume; each endpoint set not
    yet placed goes to the free slots stretching THIS boundary least."""
    names, inv, words, _ = _chain_info(W)
    xy = _slots_xy(W)
    bounds = sorted(zip(names[:-1], names[1:]),
                    key=lambda pc: -words[pc[1]])
    free = set(_usable(W))
    seat = {}

    def place(n, anchor):
        picks = sorted(free, key=lambda i: (_manh(xy[i], anchor), i))[:inv[n]]
        seat[n] = tuple(picks)
        free.difference_update(picks)

    cx = (max(x for x, _ in xy) / 2, max(y for _, y in xy) / 2)
    for prev, cur in bounds:
        if prev not in seat and cur not in seat:
            place(prev, cx)
            place(cur, _centroid(xy, seat[prev]))
        elif prev in seat and cur not in seat:
            place(cur, _centroid(xy, seat[prev]))
        elif cur in seat and prev not in seat:
            place(prev, _centroid(xy, seat[cur]))
    for n in names:                              # any isolated leftovers
        if n not in seat:
            place(n, cx)
    L = (max(int(n.rsplit("@L", 1)[1]) for n in seat) + 1
         if "@L" in names[0] else len(names))
    return ss.Pi(n_blocks=L, cuts=tuple(range(1, L + 1)), seat=seat)


REGISTRY = {"random": _gen_random, "sequential": _gen_sequential,
            "snake": _gen_snake, "least_manhattan": _gen_least_manhattan,
            "clustered": _gen_clustered, "nmap_greedy": _gen_nmap_greedy,
            "heaviest_first": _gen_heaviest_first}
assert tuple(REGISTRY) == NAMES


def generate(name: str, W, seed=None) -> ss.Pi:
    if name not in REGISTRY:
        raise ValueError(f"unknown baseline '{name}'; the registry is "
                         f"closed at {NAMES}")
    pi = REGISTRY[name](W, seed)
    ok, why = ss.legal(pi, W.fab, W.inventory())
    if not ok:
        raise AssertionError(f"baseline {name} produced an illegal Pi: {why}")
    return pi
