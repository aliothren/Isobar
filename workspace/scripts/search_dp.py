"""S4 day 9 (C64-e): the exact interval DP -- spec section 8 level 1.

State F(k, j, d) = first j blocks in k segments using d dies
([AMENDED 1]: states unchanged, the ORACLE's group-size axis is the
tiler-feasible size set, possibly sparse). Oracle, closed form on the
frozen accounts (zero mapper):

    t(segment [i, j), g) = (j - i) * tau(g) + entry_fee(i)

Flat in g (the replication speed model stays out of scope). COST TABLE
per the D.2 ruling of the hand-off accounting review: tau[layer] = the
evaluator's layer time under the given seating -- compute + write +
elementwise PLUS the layer's intra-layer hand-offs at the busiest-link
term -- and fee[layer] = the layer boundary's busiest-link hand-off at
the same seating; both per layer, both seat-dependent (the former
oracle's reference-hop fee on total words and its omission of the
intra-layer term are superseded).

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


def standing_instance(pi=None, phase: str = "prefill",
                      d2d_gbps: float = GRS_GBPS) -> Tuple[Instance, Dict]:
    """The A4/standing 2.7B payload at GRS. D.2 RULING (the hand-off
    accounting review): the per-layer time is the EVALUATOR'S layer time
    under the given seating (default: the A4 payload seating) --
    compute + write + elementwise PLUS that layer's four INTRA-layer
    hand-offs at the busiest-link accounting -- and the entry fee is the
    layer boundary's busiest-link hand-off at the same seating. Both are
    seat-dependent and per layer. The former oracle omitted the
    intra-layer term (88% of the D2D words) and priced the fee on total
    words; it is superseded, its numbers kept in FIXLIST as SUPERSEDED.
    Still flat in g (the replication speed model stays out of scope)."""
    W = se.Workload2p7B()
    pi = pi or ss.pi_from_a4_payload()
    L = W.cfg.n_layers
    layer_s = W.layer_serial_s(phase)
    bs = W.boundaries(pi, phase)
    wps = d2d_gbps * 1e9
    intra = [0.0] * L
    inter = [0.0] * L                            # no boundary into layer 0
    for b in bs:
        li = int(b["into"].rsplit("@L", 1)[1])
        t = b["busiest_words"] / wps
        if b["inter_layer"]:
            inter[li] += t
        else:
            intra[li] += t
    # EVALUATOR-IDENTICAL (the third mismatch surfaced by the D.2 table):
    # the evaluator charges every boundary -- intra-layer AND the layer's
    # ENTRY inter-layer hand-off -- to the receiving layer's stage whether
    # or not a cut sits there; in the frozen model cutting itself costs
    # nothing (one mesh, no priced package seam). So the entry hand-off
    # is folded into the layer's time and the cut-dependent fee is ZERO.
    # The former "fee at cut points only" table had no evaluator
    # counterpart (it dropped within-segment inter-layer hand-offs and
    # made the single caliber falsely cut-dependent).
    G = tuple(layer_feasible_sizes(W.cfg, W.S, 576))
    taus = tuple(tuple(layer_s + intra[li] + inter[li] for _ in G)
                 for li in range(L))
    return (Instance(taus=taus, fees=tuple(0.0 for _ in range(L)), G=G,
                     budget=576),
            {"layer_s": layer_s, "intra_s": intra, "inter_s": inter,
             "fee_s": [0.0] * L, "L": L, "phase": phase,
             "d2d_gbps": d2d_gbps,
             "d2d_total_s": sum(intra) + sum(inter),
             "inter_total_s": sum(inter),
             "cut_fee_total_s": 0.0})


def uniform_reference_instance() -> Tuple[Instance, Dict]:
    """The uniform-layer REFERENCE: every layer at the standing seating's
    MEAN layer time and mean fee -- the instance on which the
    balanced-cut degeneracy is the structural claim (gate D3)."""
    inst, meta = standing_instance()
    L = meta["L"]
    tau = sum(t[0] for t in inst.taus) / L
    fee = 0.0                                     # cutting is free (above)
    taus = tuple(tuple(tau for _ in inst.G) for _ in range(L))
    fees = tuple(0.0 for _ in range(L))
    return (Instance(taus=taus, fees=fees, G=inst.G, budget=inst.budget),
            {"tau": tau, "fee": fee, "L": L})


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
    intra, inter = meta["intra_s"], meta["inter_s"]
    print(f"layer_s {meta['layer_s']*1e3:.4f} ms | intra-layer hand-offs "
          f"per layer {min(intra)*1e3:.3f}..{max(intra)*1e3:.3f} ms | "
          f"entry (inter-layer) hand-off per layer "
          f"{min(inter[1:])*1e3:.4f}..{max(inter[1:])*1e3:.4f} ms "
          f"(busiest-link, A4 seating, GRS)")
    v1, p1 = solve(inst, 1, "single")
    v2, _ = solve(inst, 2, "single")
    print(f"single caliber: k=1 -> {v1*1e3:.3f} ms; k=2 -> {v2*1e3:.3f} ms "
          f"(identical: cutting is free in the frozen model)")
    # the D.2 reporting rule: shares with their denominators named
    print(f"D2D TOTAL share (all 159 hand-offs / whole serial latency) = "
          f"{meta['d2d_total_s']/v1:.2%}; INTER-LAYER hand-off share (the "
          f"31 layer-boundary hand-offs, paid at every boundary cut or "
          f"not / whole serial latency) = {meta['inter_total_s']/v1:.2%}; "
          f"CUT-DEPENDENT fee = 0 (no priced package seam in the model)")
    print(f"{'k':>3} {'interval(ms)':>13} {'seg sizes':>24} "
          f"{'g':>4} {'dies':>5} {'fee/stage':>10}")
    rows = {}
    for k in (1, 2, 4, 8, 16, 32):
        v, plan = solve(inst, k, "pipe")
        sizes = [j - i for i, j, _ in plan]
        gs = sorted(set(g for _, _, g in plan))
        dies = sum((j - i) * g for i, j, g in plan)
        stages = [(sum(inst.taus[b][inst.G.index(g)] for b in range(i, j))
                   + inst.fees[i], inst.fees[i]) for i, j, g in plan]
        st, f = max(stages)
        rows[k] = {"interval_s": v, "sizes": sizes, "dies": dies}
        print(f"{k:3d} {v*1e3:13.4f} {str(sizes):>24} {str(gs):>4} "
              f"{dies:5d} {f/st:10.4%}")
    ks = sorted(rows, key=lambda k: rows[k]["interval_s"])
    print(f"pipe-caliber optimum on the standing payload: k = {ks[0]} "
          f"(interval {rows[ks[0]]['interval_s']*1e3:.4f} ms)")
    u, um = uniform_reference_instance()
    vu, pu = solve(u, 8, "pipe")
    print(f"uniform-layer reference (mean layer {um['tau']*1e3:.4f} ms, cut "
          f"fee 0): k=8 sizes {[j - i for i, j, _ in pu]} interval "
          f"{vu*1e3:.4f} ms")


if __name__ == "__main__":
    main()
