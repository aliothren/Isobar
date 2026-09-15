"""S4 day 9 (C64-e): the exact interval DP -- spec section 8 level 1.

State F(k, j, d) = first j blocks in k segments using d dies
([AMENDED 1]: states unchanged, the ORACLE's group-size axis is the
tiler-feasible size set, possibly sparse). Oracle, closed form on the
frozen accounts (zero mapper):

    t(segment [i, j), g) = (j - i) * tau(g) + entry_fee(i)

V1 is DECLARED FLAT in g (tau(g) = the production-point
layer_serial_s for every feasible g; the replication/heterogeneity
speed model is out of v1 scope -- heterogeneity enters day 10+
through the fees). Fees per [AMENDED 2]: the entry boundary priced at
ADJACENT-SEATING REFERENCE HOPS = 1 -- systematically optimistic,
direction declared, magnitude backfill due day 10.

Calibers: "pipe" is the primary deployment question and the DP is
MINIMAX (min over cuts of the max stage time; stage = m * tau +
entry fee; wrap excluded); "single" is the sum form (cuts only add
fees there, so k = 1 is expected optimal -- pinned).

The DP is EXACT: the sparse cuts/size axis hosts no Markov chain
(the ergodicity page's template slot (b) is resolved by exact
enumeration; only the linkage's SA-seating legs run chains, and
those walk the full space -- option (a)).

    python3 scripts/search_dp.py     -> the standing-payload readings
"""
import os
import sys
from dataclasses import dataclass
from itertools import combinations, product
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import llm_workload as lw
from scripts import search_eval as se
from scripts import search_space as ss

GRS_GBPS = 12.5
PER_OP_CAP_EXTRA = 3          # per-op feasible sets scanned to standing+3
INF = float("inf")


# ------------------------------------------------------- the layer G set
def layer_feasible_sizes(cfg=None, S=512, max_dies=576) -> List[int]:
    """The LAYER-level tiler-feasible size set: all sums of per-op
    feasible counts (per-op cap = standing + PER_OP_CAP_EXTRA). Sparse:
    16 is absent (it would need ffn1 = 4, the O10 counterexample)."""
    cfg = cfg or lw.GptConfig(d_model=2560, n_heads=32, d_ff=10240,
                              n_layers=32, name="gpt-2.7b")
    ops = {o.name: o for o in lw.block_ops(cfg, S=S, phase="prefill")}
    standing = dict(ss.chain_inventory(cfg, S, max_dies=max_dies))
    per_op = []
    for name, n0 in standing.items():
        if name not in ops:
            # the fixed-function attention die: not a weight matmul, not
            # tiler-planned -- its feasible set is the singleton {n0}
            per_op.append([n0])
            continue
        cand = ss.feasible_die_counts(ops[name],
                                      max_dies=n0 + PER_OP_CAP_EXTRA)
        per_op.append(sorted(x for x in cand if x >= n0 - 1))
    sums = {sum(pick) for pick in product(*per_op)}
    return sorted(sums)


# ------------------------------------------------------------ the oracle
@dataclass(frozen=True)
class Instance:
    """One DP instance: per-block times tau[b][gi] (block b at G[gi]),
    entry fees fee[b] (the hand-off fee paid by a segment STARTING at
    block b; fee[0] = 0 -- no wrap), the sparse size set G, die budget."""
    taus: Tuple[Tuple[float, ...], ...]     # [L][|G|]
    fees: Tuple[float, ...]                 # [L]
    G: Tuple[int, ...]
    budget: int


def standing_instance() -> Tuple[Instance, Dict]:
    """The A4/standing 2.7B payload at GRS, v1 flat-in-g oracle."""
    W = se.Workload2p7B()
    L = W.cfg.n_layers
    layer_s = W.layer_serial_s("prefill")
    # inter-layer boundary words, the evaluator's own convention (read
    # once from the standing sequential payload; identical per layer)
    from scripts import search_baselines as sb
    pi = sb.generate("sequential", W)
    bs = W.boundaries(pi, "prefill")
    inter = [b for b in bs if b["inter_layer"]]
    words = inter[0]["words"]
    assert all(abs(b["words"] - words) < 1e-6 for b in inter)
    fee_s = words / (GRS_GBPS * 1e9)         # reference hops = 1 ([AM 2])
    G = tuple(layer_feasible_sizes(W.cfg, W.S, 576))
    taus = tuple(tuple(layer_s for _ in G) for _ in range(L))
    fees = tuple(0.0 if b == 0 else fee_s for b in range(L))
    return (Instance(taus=taus, fees=fees, G=G, budget=576),
            {"layer_s": layer_s, "fee_s": fee_s, "words": words, "L": L})


# ---------------------------------------------------------------- the DP
def _seg_cost(inst: Instance, i: int, j: int, gi: int) -> float:
    return sum(inst.taus[b][gi] for b in range(i, j)) + inst.fees[i]


def solve(inst: Instance, k: int, caliber: str = "pipe"):
    """Exact DP: min over all k-segmentations and per-segment g of the
    pipe interval (max stage) or the single sum. Returns (value, plan)
    with plan = [(i, j, g)] re-pricing exactly to the value, minimal
    total dies among optima (deterministic tie-break)."""
    if caliber not in ("pipe", "single"):
        raise ValueError(caliber)
    L = len(inst.taus)
    nG = len(inst.G)
    comb = max if caliber == "pipe" else (lambda a, b: a + b)
    # best[(kk, j)] = dict d -> (value, back) ; prune dominated d
    best: Dict[Tuple[int, int], Dict[int, Tuple[float, tuple]]] = {
        (0, 0): {0: (0.0, None)}}
    for kk in range(1, k + 1):
        for j in range(kk, L + 1):
            cell: Dict[int, Tuple[float, tuple]] = {}
            for i in range(kk - 1, j):
                prev = best.get((kk - 1, i))
                if not prev:
                    continue
                for gi in range(nG):
                    dd = (j - i) * inst.G[gi]
                    c = _seg_cost(inst, i, j, gi)
                    for d0, (v0, _) in prev.items():
                        d = d0 + dd
                        if d > inst.budget:
                            continue
                        v = comb(v0, c)
                        old = cell.get(d)
                        if old is None or v < old[0] - 1e-18:
                            cell[d] = (v, (i, gi, d0))
            # prune: keep only Pareto (increasing d must strictly help)
            pruned, bestv = {}, INF
            for d in sorted(cell):
                v, back = cell[d]
                if v < bestv - 1e-18:
                    pruned[d] = (v, back)
                    bestv = v
            best[(kk, j)] = pruned
    cell = best.get((k, L), {})
    if not cell:
        return INF, []
    d_opt = min(cell, key=lambda d: (cell[d][0], d))
    plan, j, kk, d = [], L, k, d_opt
    while kk > 0:
        v, back = best[(kk, j)][d]
        i, gi, d0 = back
        plan.append((i, j, inst.G[gi]))
        j, kk, d = i, kk - 1, d0
    plan.reverse()
    # re-price check: the plan must reproduce the DP value exactly
    vals = [sum(inst.taus[b][inst.G.index(g)] for b in range(i, j))
            + inst.fees[i] for i, j, g in plan]
    v = max(vals) if caliber == "pipe" else sum(vals)
    assert abs(v - cell[d_opt][0]) < 1e-15, "reconstruction mismatch"
    return cell[d_opt][0], plan


# --------------------------------------------- the brute-force gate (D1)
def brute(inst: Instance, k: int, caliber: str = "pipe"):
    """Exhaustive over all cut sets x per-segment g (L <= 8)."""
    L = len(inst.taus)
    combf = max if caliber == "pipe" else (lambda a, b: a + b)
    best_v = INF
    for cuts in combinations(range(1, L), k - 1):
        bounds = [0] + list(cuts) + [L]
        segs = list(zip(bounds[:-1], bounds[1:]))
        for gis in product(range(len(inst.G)), repeat=k):
            d = sum((j - i) * inst.G[gi] for (i, j), gi in zip(segs, gis))
            if d > inst.budget:
                continue
            v = None
            for (i, j), gi in zip(segs, gis):
                c = _seg_cost(inst, i, j, gi)
                v = c if v is None else combf(v, c)
            if v < best_v:
                best_v = v
    return best_v


# ------------------------------------------------------------ the report
def main():
    inst, meta = standing_instance()
    print(f"layer feasible size set G = {inst.G}")
    print(f"(16 absent = the O10 echo; 17 = the standing minimum)")
    print(f"layer_s {meta['layer_s']*1e3:.4f} ms | boundary "
          f"{meta['words']/1e6:.2f}M words -> fee {meta['fee_s']*1e3:.4f} ms"
          f" at reference 1 hop, GRS {GRS_GBPS} GB/s")
    v1, p1 = solve(inst, 1, "single")
    print(f"single caliber: k=1 -> {v1*1e3:.3f} ms (cuts only add fees; "
          f"k=2 -> {solve(inst, 2, 'single')[0]*1e3:.3f} ms)")
    print(f"{'k':>3} {'interval(ms)':>13} {'seg sizes':>24} "
          f"{'g':>4} {'dies':>5} {'fee share':>10}")
    rows = {}
    for k in (1, 2, 4, 8, 16, 32):
        v, plan = solve(inst, k, "pipe")
        sizes = [j - i for i, j, _ in plan]
        gs = sorted(set(g for _, _, g in plan))
        dies = sum((j - i) * g for i, j, g in plan)
        stage = max(sum(inst.taus[b][inst.G.index(g)] for b in range(i, j))
                    + inst.fees[i] for i, j, g in plan)
        fee_share = meta["fee_s"] / stage if k > 1 else 0.0
        rows[k] = {"interval_s": v, "sizes": sizes, "dies": dies}
        print(f"{k:3d} {v*1e3:13.4f} {str(sizes):>24} {str(gs):>4} "
              f"{dies:5d} {fee_share:10.4%}")
    ks = sorted(rows, key=lambda k: rows[k]["interval_s"])
    print(f"pipe-caliber optimum on the standing payload: k = {ks[0]} "
          f"(interval {rows[ks[0]]['interval_s']*1e3:.4f} ms)")


if __name__ == "__main__":
    main()
