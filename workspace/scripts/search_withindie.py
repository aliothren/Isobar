"""The within-die assignment beta: the intra-die instance of Fig. 1(a) after
attention offload, searched exhaustively and by the annealer.

Space per die (8 macro slots on the 2x4 macro mesh, global buffer at the
centre):
  attention die: qkv_proj on 3 slots + out_proj on 1 (4 slots free;
                 280 joint seatings)
  FFN die:       ffn1 on 4 + ffn2 on 4 (70 seatings; every slot used)
Within an operator the seat order is irrelevant (uniform bundles: sets, not
tuples); legality is sizes + disjointness, by construction.

J = the per-die stack cost at an anchor bandwidth g: the sum over the die's
operators of write + propagation + max(compute, serialization * scale),
where the serialization comes from the stored per-macro levers (D, U)
(results/reference/intradie_levers.json, no refit) spread x8/k over the
operator's own k seats, priced through link_occupancy at the reference
words-per-cycle, and scale = REF_WC / wc(g). Active cell g = 0.4 GB/s;
g = 2.0 GB/s is the control where every seating ties.

The space is small, so the exhaustive optimum is the ground truth; the
default seating, the exhaustive best and worst and the annealer's result
are reported. Before any search, the recomputed fold must reproduce the
stored lever table (identity check).

    python3 scripts/search_withindie.py -> results/reference/intradie_search.json
"""
import json
import os
import sys
from itertools import combinations
from typing import Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.crossbar_comm as cc
from scripts import reference_hardware as an
from scripts import intradie_levers as asl
from scripts import fabric as fabric_mod
from scripts import paths
from scripts import placement as pm
from scripts import search_sa as sa
from scripts import search_space as ss

WS = asl.WS
DIES = {"attn": (("qkv_proj", 3), ("out_proj", 1)),
        "ffn": (("ffn1", 4), ("ffn2", 4))}
SHIPPED = {"attn": {"qkv_proj": (0, 1, 2), "out_proj": (3,)},
           "ffn": {"ffn1": (0, 1, 2, 3), "ffn2": (4, 5, 6, 7)}}
G_ACTIVE, G_SAFE = 0.4, 2.0
OUT_JSON = os.path.join(paths.REFERENCE, "intradie_search.json")


def _prod_fab():
    base = fabric_mod.default()
    topo, params, _ = next(s for s in asl.SCHEMES if s[2] == asl.PROD)
    return asl.variant(base, topo, params), base.level("macro").link.name


class WithinDieJ:
    """The joint stack cost of one die at one anchor bandwidth."""

    def __init__(self, die: str, phase: str, g_gbps: float):
        self.die, self.phase, self.g = die, phase, g_gbps
        src = json.load(open(asl.SRC))
        lev = json.load(open(paths.INTRADIE_LEVERS))
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
    stored = json.load(open(paths.INTRADIE_LEVERS))
    fold = fold_anchor_check()
    for phase, rows in fold.items():
        for mine, theirs in zip(rows, stored["phases"][phase]["a3_cells"]):
            for k in ("g_gbps", "a3_stack_ratio", "a3_mech_ratio_attn",
                      "a3_mech_ratio_ffn"):
                assert abs(mine[k] - theirs[k]) <= 1e-9 * max(theirs[k], 1.0)
    print("identity check: recomputed co-resident fold == stored a3_cells "
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
