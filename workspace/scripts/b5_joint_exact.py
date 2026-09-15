"""B5: how much does the DP -> SA split cost, measured against a
CERTIFIED joint optimum on a shrunk instance.

The shipped method solves the deployment problem in two stages: the
interval DP picks the cuts, then SA seats the blocks at those cuts.
That split is a modelling convenience, and its cost has never been
measured. Here it is, on an instance small enough to enumerate
exhaustively: 4 blocks x 2 dies on a 3x3 mesh (8 seats used, one
spare), same hand-off term as the big instance (busiest over links
AND ports), same evaluator-identical cost rule (each block's time =
compute + its ENTRY hand-off; cutting is free), same pipe caliber
(interval = max stage). 22,680 seatings x 8 cut sets = 181,440 joint
states -> the joint optimum is CERTIFIED.

Compared against it: (1) the sequential solve (DP cuts on a reference
seating, then SA on seating), (2) DP top-K partitions each with its
own SA, (3) one and two rounds of gamma <-> (alpha, beta) alternation.
Reported per cell: gap mean and worst over 5 RNG seeds, plus a
budget-quality curve for every SA run.

    python3 scripts/b5_joint_exact.py -> analysis/b5_joint_exact.json
"""
import itertools
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import search_eval as se

GX, GY = 3, 3
N_BLOCKS, PER_BLOCK = 4, 2
COMPUTE_S = 1.0e-3                 # uniform, as the homogeneous stack is
V_WORDS = 1.0e6                    # per hand-off
CELLS = {"standard": 12.5e9, "weak_d2d": 0.4e9}    # words/s
SEEDS = (0, 1, 2, 3, 4)
STEPS = 300
OUT = os.path.join(se.A, "b5_joint_exact.json")
SLOTS = [(x, y) for y in range(GY) for x in range(GX)]


def handoff_words(prod, cons):
    """The settled term on this grid: busiest over links AND node
    ports, XY routing, R-split (each producer ships V/P to every
    consumer)."""
    piece = V_WORDS / len(prod)
    load = {}
    for a in prod:
        for b in cons:
            if a == b:
                continue
            ax, ay = SLOTS[a]
            bx, by = SLOTS[b]
            x, y = ax, ay
            while x != bx:
                st = 1 if bx > x else -1
                k = ("h", min(x, x + st), y, st)
                load[k] = load.get(k, 0.0) + piece
                x += st
            while y != by:
                st = 1 if by > y else -1
                k = ("v", x, min(y, y + st), st)
                load[k] = load.get(k, 0.0) + piece
                y += st
            load[("inj", a)] = load.get(("inj", a), 0.0) + piece
            load[("ej", b)] = load.get(("ej", b), 0.0) + piece
    return max(load.values(), default=0.0)


def block_times(seating, wps):
    """Per-block time: compute + the block's ENTRY hand-off (block 0 has
    none -- no wrap), exactly the evaluator-identical rule."""
    out = [COMPUTE_S]
    for i in range(1, N_BLOCKS):
        out.append(COMPUTE_S
                   + handoff_words(seating[i - 1], seating[i]) / wps)
    return out


def interval(times, cuts, fee=0.0):
    """Pipe caliber: max stage sum over the segmentation given by cuts
    (a tuple of interior cut positions). `fee` is the PER-CUT seam
    price -- zero in the frozen model (where the pipe optimum is
    therefore always maximum depth), swept in the addendum to reach the
    regime where the partition actually groups blocks."""
    bounds = [0] + list(cuts) + [N_BLOCKS]
    return max(sum(times[i:j]) for i, j in zip(bounds[:-1], bounds[1:])) \
        + fee * len(cuts)


def all_cutsets():
    out = []
    for r in range(N_BLOCKS):
        out += [tuple(c) for c in itertools.combinations(range(1, N_BLOCKS), r)]
    return out


CUTSETS = all_cutsets()


def best_cuts(times, fee=0.0):
    """The DP's job on this instance: exact by enumeration (8 cut sets)."""
    return min(CUTSETS, key=lambda c: interval(times, c, fee))


def all_seatings():
    """Every assignment of 4 disjoint unordered die-pairs to the 4
    ordered blocks, from the 9 slots."""
    idx = list(range(GX * GY))
    out = []

    def walk(rem, acc):
        if len(acc) == N_BLOCKS:
            out.append(tuple(acc))
            return
        for pair in itertools.combinations(sorted(rem), PER_BLOCK):
            walk(rem - set(pair), acc + [pair])

    walk(set(idx), [])
    return out


def joint_optimum(seatings, wps, fee=0.0):
    """The CERTIFIED optimum: every seating x every cut set."""
    best = None
    for st in seatings:
        t = block_times(st, wps)
        c = best_cuts(t, fee)
        v = interval(t, c, fee)
        if best is None or v < best[0]:
            best = (v, st, c)
    return best


# ------------------------------------------------------------- the SA
def neighbours(st, rng, free):
    """One move: swap two dies between blocks, or move one die to the
    spare slot (the engine's exchange / migrate families, in miniature)."""
    st = [list(p) for p in st]
    if free and rng.random() < 0.4:
        b = rng.randrange(N_BLOCKS)
        i = rng.randrange(PER_BLOCK)
        f = rng.choice(sorted(free))
        st[b][i] = f
    else:
        a, b = rng.sample(range(N_BLOCKS), 2)
        i, j = rng.randrange(PER_BLOCK), rng.randrange(PER_BLOCK)
        st[a][i], st[b][j] = st[b][j], st[a][i]
    return tuple(tuple(sorted(p)) for p in st)


def sa_seating(cuts, wps, seed, start, steps=STEPS, t0=None, fee=0.0):
    """SA on the seating at FIXED cuts -- the shipped method's second
    stage. Returns (best value, best seating, budget-quality curve)."""
    rng = random.Random(seed)
    cur = start
    used = set(d for p in cur for d in p)
    free = set(range(GX * GY)) - used
    jc = interval(block_times(cur, wps), cuts, fee)
    best, best_st = jc, cur
    t0 = t0 if t0 is not None else 0.05 * jc
    curve = []
    for k in range(steps):
        t = t0 * (0.99 ** k)
        used = set(d for p in cur for d in p)
        cand = neighbours(cur, rng, set(range(GX * GY)) - used)
        if len(set(d for p in cand for d in p)) != N_BLOCKS * PER_BLOCK:
            continue
        v = interval(block_times(cand, wps), cuts, fee)
        if v < jc or (t > 0 and rng.random() < pow(2.718281828,
                                                   -(v - jc) / t)):
            cur, jc = cand, v
            if v < best:
                best, best_st = v, cand
        curve.append(best)
    return best, best_st, curve


def reference_seating():
    """The default fill: blocks take consecutive slots (the A4-analogue
    reference the DP's first pass uses)."""
    return tuple(tuple(range(2 * b, 2 * b + 2)) for b in range(N_BLOCKS))


def top_k_cuts(times, k=3, fee=0.0):
    return sorted(CUTSETS, key=lambda c: interval(times, c, fee))[:k]


def run_cell(name, wps, seatings, out, fee=0.0):
    opt_v, opt_st, opt_c = joint_optimum(seatings, wps, fee)
    ref = reference_seating()
    ref_t = block_times(ref, wps)
    dp_cuts = best_cuts(ref_t, fee)
    rows = {"joint_optimum_s": opt_v, "joint_cuts": list(opt_c),
            "joint_seating": [list(p) for p in opt_st],
            "dp_cuts_on_reference": list(dp_cuts),
            "n_seatings": len(seatings), "n_joint_states":
            len(seatings) * len(CUTSETS)}
    if fee == 0.0:
        print(f"[{name}] joint optimum {opt_v*1e3:.4f} ms (cuts {opt_c}); "
              f"DP cuts on the reference seating {dp_cuts}; "
              f"{rows['n_joint_states']} states enumerated")

    seq, curves = {}, {}
    for seed in SEEDS:
        v, st, curve = sa_seating(dp_cuts, wps, seed, ref, fee=fee)
        seq[seed] = v
        curves[f"sequential/{seed}"] = curve[::20]
    rows["sequential"] = {"per_seed_s": seq,
                          "gap_mean": sum(seq.values()) / len(seq) / opt_v,
                          "gap_worst": max(seq.values()) / opt_v,
                          "gap_best": min(seq.values()) / opt_v}
    _ = fee == 0.0 and print(f"  sequential (DP cuts -> SA seating): gap mean "
          f"{rows['sequential']['gap_mean']:.4f}, worst "
          f"{rows['sequential']['gap_worst']:.4f}, best "
          f"{rows['sequential']['gap_best']:.4f}")

    topk = top_k_cuts(ref_t, 3, fee)
    tk = {}
    for seed in SEEDS:
        best = None
        for c in topk:
            v, st, curve = sa_seating(c, wps, seed, ref, fee=fee)
            # re-price the found seating under ITS OWN best cuts
            tt = block_times(st, wps)
            v_re = interval(tt, best_cuts(tt, fee), fee)
            best = v_re if best is None else min(best, v_re)
        tk[seed] = best
    rows["top_k"] = {"k": 3, "cuts": [list(c) for c in topk],
                     "per_seed_s": tk,
                     "gap_mean": sum(tk.values()) / len(tk) / opt_v,
                     "gap_worst": max(tk.values()) / opt_v}
    _ = fee == 0.0 and print(f"  DP top-3 partitions, each with its own SA: gap mean "
          f"{rows['top_k']['gap_mean']:.4f}, worst "
          f"{rows['top_k']['gap_worst']:.4f}")

    alt = {}
    for seed in SEEDS:
        cuts, st = dp_cuts, ref
        hist = []
        for _round in range(2):
            v, st, curve = sa_seating(cuts, wps, seed, st, fee=fee)
            tt = block_times(st, wps)
            cuts = best_cuts(tt, fee)
            hist.append(interval(tt, cuts, fee))
        alt[seed] = hist
    a1 = [h[0] for h in alt.values()]
    a2 = [h[1] for h in alt.values()]
    rows["alternation"] = {
        "per_seed_s": {k: v for k, v in alt.items()},
        "round1_gap_mean": sum(a1) / len(a1) / opt_v,
        "round2_gap_mean": sum(a2) / len(a2) / opt_v,
        "round2_gap_worst": max(a2) / opt_v}
    _ = fee == 0.0 and print(f"  alternation gamma <-> (alpha,beta): round-1 gap mean "
          f"{rows['alternation']['round1_gap_mean']:.4f}, round-2 mean "
          f"{rows['alternation']['round2_gap_mean']:.4f}, round-2 worst "
          f"{rows['alternation']['round2_gap_worst']:.4f}")
    rows["budget_quality_curves"] = curves
    out[name] = rows
    return rows


def main():
    seatings = all_seatings()
    out = {"instance": f"{N_BLOCKS} blocks x {PER_BLOCK} dies on "
                       f"{GX}x{GY}", "quantifier": "certified (the joint "
           "optimum is exhaustive); the solver rows are observed",
           "evaluation_set": "every seating x every cut set; 5 RNG seeds "
                             "per SA", "cells": {}}
    for name, wps in CELLS.items():
        run_cell(name, wps, seatings, out["cells"])
    # the addendum: the seam-fee sweep, where the partition can group
    out["seam_fee_sweep"] = {}
    print("\nSEAM-FEE SWEEP (per-cut price, x the block compute time):")
    for f in (0.0, 0.1, 0.25, 0.5, 1.0):
        sub = {}
        for name, wps in CELLS.items():
            r = run_cell(f"{name}@fee{f}", wps, seatings, sub, f * COMPUTE_S)
            print(f"    fee {f:4} {name:9}: optimal depth "
                  f"{len(r['joint_cuts']) + 1}, joint {r['joint_optimum_s']*1e3:.4f}"
                  f" ms, sequential gap mean {r['sequential']['gap_mean']:.4f}"
                  f" worst {r['sequential']['gap_worst']:.4f}")
        out["seam_fee_sweep"][str(f)] = {
            k: {kk: v[kk] for kk in ("joint_optimum_s", "joint_cuts",
                                     "sequential", "top_k", "alternation")}
            for k, v in sub.items()}
    # the verdict against the pre-registered three branches
    noise = 0.018
    headline = 0.035          # the seating instance's weak-cell gain
    worst = max(c["sequential"]["gap_worst"] - 1 for c in out["cells"].values())
    tk_gain = max(c["sequential"]["gap_mean"] - c["top_k"]["gap_mean"]
                  for c in out["cells"].values())
    alt_gain = max(c["sequential"]["gap_mean"]
                   - c["alternation"]["round2_gap_mean"]
                   for c in out["cells"].values())
    spread = max(c["sequential"]["gap_worst"] - c["sequential"]["gap_best"]
                 for c in out["cells"].values())
    out["verdict"] = {
        "worst_sequential_gap": worst, "noise_band": noise,
        "headline_gain": headline,
        "top_k_improvement": tk_gain, "alternation_improvement": alt_gain,
        "seed_spread": spread,
        "branch": ("A (keep the split)" if worst < min(noise, headline)
                   and max(tk_gain, alt_gain) < noise
                   else "B (adopt the refinement)"
                   if max(tk_gain, alt_gain) >= noise
                   else "C (method insufficient)")}
    print(f"\nVERDICT: worst sequential gap {worst:.4f} vs noise band "
          f"{noise}, headline {headline}; top-K gain {tk_gain:.4f}, "
          f"alternation gain {alt_gain:.4f}, seed spread {spread:.4f} -> "
          f"branch {out['verdict']['branch']}")
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
