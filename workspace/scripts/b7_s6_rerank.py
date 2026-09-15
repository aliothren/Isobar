"""B7, the second half: the S6 VERDICT ORDER under an external judge.

What this adjudicates (and what it does not): S6's main proof is that
defective objectives pick placements the truth punishes -- E1 (the
distance proxy) worst, E0 (the truth) best. That verdict rests on OUR
busiest-resource caliber. This probe re-ranks the SAME KIND of
placement set under a packet-level router network, so the order has an
outside witness. It is NOT about the single-flow degeneration (that is
pinned elsewhere); it is about 82 competing hand-offs sharing links.

The full instance is not BookSim-tractable (~1e7 packets), so the
structure is SHRUNK exactly as half A was: the same cross-traffic
family (stage s feeds s+2 and s+4) on the bridge's 6x6 = 36-die
package, 6 stages of 4 dies, V small enough to simulate. The arms
search THIS instance with the same objectives S6 used (truth = the
two-pattern mix; the distance proxy; the two one-hot arms; the
wrong-weave arm), and their winners are then scored by (a) our own
truth and (b) BookSim. The question is whether the ORDER survives.

    python3 scripts/b7_s6_rerank.py -> analysis/b7_s6_rerank.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import b7_handoff_probe as pr
from scripts import booksim_bridge as bb
from scripts import search_eval as se
from scripts import search_sa as sa
from scripts import search_space as ss

K = pr.K                       # 6x6 package
N_STAGES, PER_STAGE = 6, 4
V = 1536.0                     # words per hand-off (tractable packet count)
FANOUT = (2, 4)                # the shrunk cross-traffic family
CHAIN = (1,)
OUT = os.path.join(se.A, "b7_s6_rerank.json")


def pairs(kinds):
    return [(s, s + k) for s in range(N_STAGES) for k in kinds
            if s + k < N_STAGES]


def seat_of(pi):
    return [sorted(pi.seat[f"stage{s}"]) for s in range(N_STAGES)]


def flows_for(stages, kinds):
    fl = []
    for a, b in pairs(kinds):
        fl += pr.handoff_flows(stages[a], stages[b], V)
    return fl


# ---------------------------------------------------------- the judges
def ours(stages, kinds=FANOUT, mix=None):
    """Our caliber: busiest resource over links AND node ports (the
    post-F-B7 term), on the declared pattern or mix."""
    if mix:
        return sum(w * pr.our_busiest_words_ports(flows_for(stages, k))
                   for k, w in mix)
    return pr.our_busiest_words_ports(flows_for(stages, kinds))


def distance_proxy(stages, kinds=FANOUT):
    """E1: sum of volume x Manhattan distance, no contention term."""
    tot = 0.0
    for a, b in pairs(kinds):
        piece = V / len(stages[a])
        for p in stages[a]:
            for c in stages[b]:
                tot += piece * (abs(p % K - c % K) + abs(p // K - c // K))
    return tot


def booksim(stages, kinds=FANOUT):
    pk = pr.to_packets(flows_for(stages, kinds))
    return bb.run_batch(pk, k=K)["cycles"]


MIX = ((FANOUT, 0.5), (CHAIN, 0.5))


def arms():
    return {
        "E0": lambda st: ours(st, mix=MIX),          # the truth
        "E1": lambda st: distance_proxy(st),         # distance proxy
        "E2": lambda st: ours(st, CHAIN),            # chain one-hot
        "E2b": lambda st: ours(st, FANOUT),          # fan-out one-hot
    }


def mk_pi(stages):
    return ss.Pi(n_blocks=N_STAGES, cuts=tuple(range(1, N_STAGES + 1)),
                 seat={f"stage{s}": tuple(sorted(v))
                       for s, v in enumerate(stages)})


def seed_stages():
    """Four declared starts spanning the geometry families."""
    seq = [[s * PER_STAGE + i for i in range(PER_STAGE)]
           for s in range(N_STAGES)]
    clus = [[pr.node(2 * (s % 3) + dx, 2 * (s // 3) + dy)
             for dy in range(2) for dx in range(2)] for s in range(N_STAGES)]
    disp = [[pr.node((s + 2 * i) % K, (3 * i + s) % K) for i in range(4)]
            for s in range(N_STAGES)]
    snake = [[pr.node(x if s % 2 == 0 else K - 1 - x, s)
              for x in range(PER_STAGE)] for s in range(N_STAGES)]
    return {"sequential": seq, "clustered": clus, "dispersed": disp,
            "snake": snake}


def main():
    if not bb.available():
        raise SystemExit("booksim binary missing")
    seeds = {k: mk_pi(v) for k, v in seed_stages().items()}
    out = {"grid": f"{K}x{K}", "stages": N_STAGES, "per_stage": PER_STAGE,
           "v_words": V, "quantifier": "observed",
           "evaluation_set": "4 declared seeds x 4 arms on a shrunk "
                             "cross-traffic instance",
           "note": "the S6 VERDICT ORDER under an external judge; the "
                   "full instance is not BookSim-tractable, so the "
                   "structure is shrunk (declared, not extrapolated)"}
    winners, arm_info = {}, {}
    for name, J in arms().items():
        obj = lambda pi, J=J: J(seat_of(pi))
        rungs = {k: obj(p) for k, p in seeds.items()}
        t0 = (max(rungs.values()) - min(rungs.values())) / 20.0
        best_name, res = sa.multistart(
            obj, seeds, K * K, sa.Schedule(t0=t0, alpha=0.99, steps=400),
            seed=0)
        winners[name] = res[best_name].best_pi
        arm_info[name] = {"self_best": res[best_name].best_j,
                          "best_start": best_name,
                          "rungs": rungs}
        print(f"  [{name}] self-best {res[best_name].best_j:.6g} "
              f"(start {best_name})")
    print("\n  arm winner scored by OUR truth and by BookSim:")
    rows = {}
    for name, pi in winners.items():
        st = seat_of(pi)
        rows[name] = {"our_truth": ours(st, mix=MIX),
                      "our_fanout": ours(st, FANOUT),
                      "booksim_fanout_cycles": booksim(st, FANOUT),
                      "booksim_chain_cycles": booksim(st, CHAIN),
                      "seating": st}
        rows[name]["booksim_mix"] = 0.5 * rows[name]["booksim_fanout_cycles"] \
            + 0.5 * rows[name]["booksim_chain_cycles"]
    o_opt = min(r["our_truth"] for r in rows.values())
    b_opt = min(r["booksim_mix"] for r in rows.values())
    for name, r in rows.items():
        r["our_regret"] = r["our_truth"] / o_opt
        r["booksim_regret"] = r["booksim_mix"] / b_opt
        print(f"    {name:4} our truth {r['our_truth']:10.0f} (regret "
              f"{r['our_regret']:.4f}) | BookSim mix {r['booksim_mix']:9.1f} "
              f"cycles (regret {r['booksim_regret']:.4f})")
    our_order = sorted(rows, key=lambda n: rows[n]["our_regret"])
    book_order = sorted(rows, key=lambda n: rows[n]["booksim_regret"])
    out["arms"] = arm_info
    out["rows"] = rows
    out["our_order"] = our_order
    out["booksim_order"] = book_order
    out["order_preserved"] = our_order == book_order
    out["e0_best_under_booksim"] = book_order[0] == "E0"
    out["e1_worst_under_booksim"] = book_order[-1] == "E1"
    out["spearman_rho"] = pr.spearman(
        {n: rows[n]["our_regret"] for n in rows},
        {n: rows[n]["booksim_regret"] for n in rows})
    print(f"\n  our order    {our_order}")
    print(f"  BookSim order {book_order}")
    print(f"  order preserved {out['order_preserved']}; E0 best under "
          f"BookSim {out['e0_best_under_booksim']}; E1 worst under BookSim "
          f"{out['e1_worst_under_booksim']}; rho {out['spearman_rho']:.3f}")
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
