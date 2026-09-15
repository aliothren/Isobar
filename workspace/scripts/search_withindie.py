"""S3 day 8 (C64-d): the WITHIN-DIE INSTANCE -- SA on the A3
co-residency space, exactly as C49-b declared it (the realizable
reopened space; offload config, d = 1024, blocks tile integrally).

Space per die (8 macro slots, production 2x4 mesh, glb centre):
  attn: qkv_proj on 3 slots + out_proj on 1 (280 joint seatings;
        4 FREE slots -- the migrate family runs its plain form)
  ffn:  ffn1 on 4 + ffn2 on 4 (70 seatings; SATURATED -- two-step)
Within-op seat order is irrelevant by uniformity (sets, not tuples).
Ergodicity template: option (a) -- full structurally-legal space, no
feasibility predicate (legality = sizes + disjointness, engine-side
by construction; the die-level tiler clause does not apply here).

J = the per-die JOINT STACK COST at an anchor g, the C49-b
composition verbatim: sum over the die's ops of
    write + prop + max(compute, a3_ser(seats) * scale),
a3_ser = the stored-lever (D, U) x 8/k flows on the op's own seats
through link_occupancy at REF_WC; scale = REF_WC / wc(g). Levers are
READ from the stored soft_lever.json -- no refit. Active cell
g = 0.4 (below the knee); g = 2.0 is the realized SAFE-CELL control
(stored ratio 1.0: the objective is flat there).

Reference ladder: the space is exhaustively enumerable -- ground
truth = the exhaustive optimum; rungs = shipped-contiguous seating,
exhaustive best, exhaustive worst. The identity anchor (pinned)
reproduces the STORED a3_cells rows before any SA runs.

Official run: python3 scripts/search_withindie.py
"""
import json
import os
import sys
from itertools import combinations
from typing import Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.crossbar_comm as cc
from scripts import anchors as an
from scripts import analyze_soft_lever as asl
from scripts import fabric as fabric_mod
from scripts import placement as pm
from scripts import search_sa as sa
from scripts import search_space as ss

WS = asl.WS
A = os.path.join(WS, "analysis")
DIES = {"attn": (("qkv_proj", 3), ("out_proj", 1)),
        "ffn": (("ffn1", 4), ("ffn2", 4))}
SHIPPED = {"attn": {"qkv_proj": (0, 1, 2), "out_proj": (3,)},
           "ffn": {"ffn1": (0, 1, 2, 3), "ffn2": (4, 5, 6, 7)}}
G_ACTIVE, G_SAFE = 0.4, 2.0
OUT_JSON = os.path.join(A, "search_withindie.json")


def _prod_fab():
    base = fabric_mod.default()
    topo, params, _ = next(s for s in asl.SCHEMES if s[2] == asl.PROD)
    return asl.variant(base, topo, params), base.level("macro").link.name


class WithinDieJ:
    """The C49-b joint stack cost of one die at one anchor."""

    def __init__(self, die: str, phase: str, g_gbps: float):
        self.die, self.phase, self.g = die, phase, g_gbps
        src = json.load(open(asl.SRC))
        lev = json.load(open(os.path.join(A, "soft_lever.json")))
        self.levers = lev["phases"][phase]["levers"]
        self.recs = {r["name"]: r
                     for r in src["phases"][phase]["per_op"][asl.PROD]}
        self.fab, self.link = _prod_fab()
        self.pl = pm.sequential_fill(self.fab)
        self.scale = asl.REF_WC / an.words_per_cycle(g_gbps)
        self.ops = DIES[die]

    def a3_ser(self, name: str, seats) -> float:
        lv = self.levers[name]
        k = len(seats)
        D, U = lv["D"] * 8.0 / k, lv["U"] * 8.0 / k
        fl = [{"level": self.link, "node": s, "volume": D + U,
               "down": D, "up": U, "src": "glb", "dst": f"{name}{j}"}
              for j, s in enumerate(seats)]
        return cc.link_occupancy(fl, self.fab, an.CYCLE_S,
                                 self.pl)["serialization_s"]

    def cost_of(self, seat: Dict[str, Tuple[int, ...]]) -> float:
        c = 0.0
        for name, _k in self.ops:
            rec = self.recs[name]
            prop = rec["latency_s"] - rec["write_s"] \
                - max(rec["compute_s"], rec["serial_s"])
            c += rec["write_s"] + prop + max(
                rec["compute_s"], self.a3_ser(name, seat[name]) * self.scale)
        return c

    def __call__(self, pi: ss.Pi) -> float:
        return self.cost_of(pi.seat)

    def mech_of(self, seat) -> float:
        return max(self.a3_ser(name, seat[name]) for name, _ in self.ops)

    # --------------------------------------------------- the ground truth
    def exhaustive(self):
        (n1, k1), (n2, k2) = self.ops
        rows = []
        for s1 in combinations(range(8), k1):
            rest = [x for x in range(8) if x not in s1]
            for s2 in combinations(rest, k2):
                seat = {n1: s1, n2: s2}
                rows.append((self.cost_of(seat), self.mech_of(seat), seat))
        rows.sort(key=lambda r: r[0])
        return rows


def mk_pi(seat) -> ss.Pi:
    return ss.Pi(n_blocks=2, cuts=(2,),
                 seat={n: tuple(sorted(v)) for n, v in seat.items()})


def fold_anchor_check():
    """Reproduce the STORED a3_cells rows (both dies + the fixed rest of
    the stack, every anchor, both phases) -- the identity anchor."""
    out = {}
    for phase in ("prefill", "decode"):
        src = json.load(open(asl.SRC))
        recs = {r["name"]: r
                for r in src["phases"][phase]["per_op"][asl.PROD]}
        Js = {die: WithinDieJ(die, phase, G_ACTIVE) for die in DIES}
        ex = {die: Js[die].exhaustive() for die in DIES}
        rows = []
        for g in asl.ANCHOR_GBPS:
            scale = asl.REF_WC / an.words_per_cycle(g)
            tot_best = tot_worst = 0.0
            mechs = {}
            for die in DIES:
                costs = []
                for _c, _m, seat in ex[die]:
                    c = 0.0
                    for name, _k in DIES[die]:
                        rec = recs[name]
                        prop = rec["latency_s"] - rec["write_s"] \
                            - max(rec["compute_s"], rec["serial_s"])
                        c += rec["write_s"] + prop + max(
                            rec["compute_s"],
                            Js[die].a3_ser(name, seat[name]) * scale)
                    costs.append(c)
                tot_best += min(costs)
                tot_worst += max(costs)
                sers = [m for _c, m, _s in ex[die]]
                mechs[die] = max(sers) / min(sers)
            fixed = 0.0
            moved_ops = {n for die in DIES for n, _ in DIES[die]}
            for name, rec in recs.items():
                if name in moved_ops:
                    continue
                ser = rec["serial_s"] * scale if rec["serial_s"] else 0.0
                prop = rec["latency_s"] - rec["write_s"] \
                    - max(rec["compute_s"], rec["serial_s"])
                fixed += rec["write_s"] + prop + max(rec["compute_s"], ser)
            rows.append({"g_gbps": g,
                         "a3_stack_ratio": (fixed + tot_worst)
                                           / (fixed + tot_best),
                         "a3_mech_ratio_attn": mechs["attn"],
                         "a3_mech_ratio_ffn": mechs["ffn"]})
        out[phase] = rows
    return out


def main():
    # identity anchor first: recomputed fold == stored rows
    stored = json.load(open(os.path.join(A, "soft_lever.json")))
    fold = fold_anchor_check()
    for phase, rows in fold.items():
        for mine, theirs in zip(rows, stored["phases"][phase]["a3_cells"]):
            for k in ("g_gbps", "a3_stack_ratio", "a3_mech_ratio_attn",
                      "a3_mech_ratio_ffn"):
                assert abs(mine[k] - theirs[k]) <= 1e-9 * max(theirs[k], 1.0)
    print("identity anchor: recomputed A3 fold == stored a3_cells "
          "(both phases, all anchors)")

    out = {"anchor_g": G_ACTIVE, "safe_g": G_SAFE, "runs": {},
           "quantifier": "certified",
           "evaluation_set": "exhaustive: 280 attn / 70 ffn joint seatings"}
    for die in DIES:
        for phase in ("prefill", "decode"):
            J = WithinDieJ(die, phase, G_ACTIVE)
            ex = J.exhaustive()
            best_j, worst_j = ex[0][0], ex[-1][0]
            shipped = SHIPPED[die]
            j_ship = J.cost_of(shipped)
            import random as _random
            rng = _random.Random(0)                # the declared random seed
            (n1, k1), (n2, k2) = DIES[die]
            s1 = tuple(rng.sample(range(8), k1))
            s2 = tuple(rng.sample([x for x in range(8) if x not in s1], k2))
            seeds = {"shipped": mk_pi(shipped),
                     "random0": mk_pi({n1: s1, n2: s2}),
                     "reversed": mk_pi({n: tuple(7 - s for s in v)
                                        for n, v in shipped.items()})}
            sched = sa.Schedule(t0=0.02 * j_ship, alpha=0.98, steps=400)
            bname, res = sa.multistart(J, seeds, 8, sched, seed=0)
            r = res[bname]
            key = f"{die}/{phase}"
            out["runs"][key] = {
                "exhaustive_best": best_j, "exhaustive_worst": worst_j,
                "shipped": j_ship,
                "shipped_is_optimal": abs(j_ship - best_j) <= 1e-15,
                "sa_best": r.best_j, "sa_start": bname,
                "sa_regret_vs_exhaustive": r.best_j / best_j,
                "band_ratio": worst_j / best_j,
                "best_seat": {n: sorted(v)
                              for n, v in ex[0][2].items()}}
            print(f"[{key}] exhaustive best {best_j*1e3:.4f} ms / worst "
                  f"{worst_j*1e3:.4f} ms (band {worst_j/best_j:.4f}) | "
                  f"shipped {j_ship*1e3:.4f} ms "
                  f"({'OPTIMAL' if out['runs'][key]['shipped_is_optimal'] else f'+{(j_ship/best_j-1)*100:.2f}%'}) | "
                  f"SA {r.best_j*1e3:.4f} ms regret "
                  f"{r.best_j/best_j:.6f} (start {bname})")
    # safe-cell control: g = 2.0 all-ties
    for die in DIES:
        J = WithinDieJ(die, "prefill", G_SAFE)
        ex = J.exhaustive()
        tie = abs(ex[-1][0] - ex[0][0]) <= 1e-15 * ex[0][0]
        pi0 = mk_pi(SHIPPED[die])
        r = sa.anneal(J, pi0, 8, sa.Schedule(t0=0.0, steps=200), seed=1)
        out["runs"][f"{die}/safe_cell_g2"] = {
            "all_tie": tie, "sa_best_equals_start":
                abs(r.best_j - r.start_j) <= 1e-15 * r.start_j}
        print(f"[{die}/safe g=2.0] all-ties: {tie}; SA best == start: "
              f"{out['runs'][f'{die}/safe_cell_g2']['sa_best_equals_start']}")
    json.dump(out, open(OUT_JSON, "w"), indent=1)
    print(f"results -> {OUT_JSON}")


if __name__ == "__main__":
    main()
