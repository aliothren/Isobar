"""S3 day 7 (C64-d): the ORDERING INSTANCE -- die-level ordering under
the DECLARED cross-traffic class load (spec [AMENDED 10/12]; the
condition was confirmed SET at the day-7 release).

Omega = the standard frozen 2.7B Pi space (per-op sets; legal()
unchanged). Ergodicity usage template filled with option (a): this
instance walks the full structurally-legal space -- no feasibility
predicate. J = the wire-time caliber on the declared load: stages =
the 32 layers (per-op sets unioned per layer, check-C's granularity),
pairs (s, s+k), k in {2,4,8}, s+k < 32 (82 pairs), V = 1e6 words per
pair, flows by the frozen R-split boundary convention verbatim
(every producer die ships its V/17 piece to every consumer die),
routed on the nominal 1 word/cycle die mesh. J is REPORTED as
busiest-wire volume in words; wire time = volume x cycle at the
nominal bandwidth (monotone identity, declared) -- the numbers stay
comparable to the filed 18.29M-30.00M check-C ladder, which the
objective must reproduce as an identity anchor (pinned).

THE INCREMENTAL LINE-LOAD STRUCTURE (spec section 8(a), delivered
here where it is consumed): per-PAIR wire-contribution cache as
integer FLOW COUNTS (all stages hold exactly 17 dies, so the R-split
piece V/17 is one global constant and count arithmetic is EXACT --
no float drift over long walks); a move recomputes only the pairs
touching the moved sets' stages, subtracts their old counts, adds the
new, then re-takes the max. incremental == full (link_occupancy) is
pinned, not assumed. The callable diffs any requested Pi against its
committed state, so the engine's reject-then-move-on sequence needs
no explicit rollback.

Official run: python3 scripts/search_ordering.py  (budget as
pre-registered in FIXLIST: 7 named seeds, base seed 0, all families,
Schedule(t0=1e6, alpha=0.996, steps=2000), both legs).
"""
import json
import os
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.crossbar_comm as cc
from scripts import check_c_crosstraffic as cx
from scripts import interconnect as ic
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_sa as sa

V = 1e6
N_STAGES = 32
STAGE_DIES = 17                       # fixed: every layer's sets sum to 17
PIECE = V / STAGE_DIES                # the one global R-split piece
FANOUT = (2, 4, 8)
OUT_JSON = os.path.join(se.A, "search_ordering.json")
OUT_PNG = os.path.join(se.A, "search_ordering.png")

host = cx.host                        # the 2.7B host at nominal 1 w/cyc


def pairs_fanout():
    return [(s, s + k) for s in range(N_STAGES) for k in FANOUT
            if s + k < N_STAGES]


def pairs_chain():
    return [(s, s + 1) for s in range(N_STAGES - 1)]


class CrossTrafficJ:
    """J(pi) with the ordered line-load incremental structure."""

    def __init__(self, W, pairs: List[Tuple[int, int]]):
        self.W, self.pairs = W, list(pairs)
        self.icl = ic.build(W.fab, "die", W.pl)
        self.duplex = self.icl.duplex
        self.layer_of = {n: int(n.rsplit("@L", 1)[1])
                         for n in W.inventory()}
        self.pairs_of_stage: Dict[int, List[int]] = {}
        for i, (s, t) in enumerate(self.pairs):
            self.pairs_of_stage.setdefault(s, []).append(i)
            self.pairs_of_stage.setdefault(t, []).append(i)
        self._kid: Dict[Tuple[str, str], int] = {}   # wire key -> int id
        self._paths: Dict[Tuple[int, int], Tuple[int, ...]] = {}
        self.seat = None
        self.load: Dict[int, int] = {}               # wire id -> flow count
        self.contrib: List[Dict[int, int]] = [dict() for _ in self.pairs]
        self.stage_sets: Dict[int, Tuple[int, ...]] = {}
        self.evals = 0

    def _path(self, a: int, b: int) -> Tuple[int, ...]:
        key = (a, b)
        got = self._paths.get(key)
        if got is None:
            if len(self._paths) > 60000:      # memory guard (long ring
                self._paths.clear()           # paths); determinism kept
            ids = []
            for r, tag in self.icl.path_directed(a, b):
                k = (r, tag if (self.duplex and tag) else "")
                kid = self._kid.setdefault(k, len(self._kid))
                ids.append(kid)
            got = self._paths[key] = tuple(ids)
        return got

    def _pair_counts(self, i: int) -> Dict[int, int]:
        s, t = self.pairs[i]
        d: Dict[int, int] = {}
        for a in self.stage_sets[s]:
            for b in self.stage_sets[t]:
                if a == b:
                    continue
                for kid in self._path(a, b):
                    d[kid] = d.get(kid, 0) + 1
        return d

    def __call__(self, pi) -> float:
        seat = {n: tuple(sorted(v)) for n, v in pi.seat.items()}
        if self.seat is None:
            changed_stages = set(range(N_STAGES))
        else:
            changed_stages = {self.layer_of[n] for n in seat
                              if seat[n] != self.seat[n]}
        if changed_stages:
            for li in changed_stages:
                self.stage_sets[li] = tuple(sorted(
                    x for n, v in seat.items()
                    if self.layer_of[n] == li for x in v))
            affected = sorted({i for li in changed_stages
                               for i in self.pairs_of_stage.get(li, [])})
            for i in affected:
                for kid, c in self.contrib[i].items():
                    self.load[kid] -= c
                self.contrib[i] = self._pair_counts(i)
                for kid, c in self.contrib[i].items():
                    self.load[kid] = self.load.get(kid, 0) + c
            self.seat = seat
        self.evals += 1
        return PIECE * max(self.load.values(), default=0)

    # ------------------------------------------------- the full evaluator
    def full_check(self, pi) -> float:
        """The independent full evaluation: the same flows handed to
        link_occupancy (check-C's exact machinery); busiest volume."""
        sets = cx.stage_sets(pi)
        flows = []
        for s, t in self.pairs:
            prev_e = {"name": f"stage{s}", "out_words": V, "split": "R"}
            e = {"name": f"stage{t}", "in_words": V}
            flows += se._one_boundary_flows(prev_e, e, sets[s], sets[t],
                                            self.W.fab)
        occ = cc.link_occupancy(flows, self.W.fab,
                                self.W.fab.device.cycle_seconds, self.W.pl)
        return occ["bottleneck"]["volume"] if occ["bottleneck"] else 0.0


# ----------------------------------------------------------- official run
SCHED = sa.Schedule(t0=1.0e6, alpha=0.996, steps=2000)
BASE_SEED = 0

# the filed check-C ladder (the named rungs of THIS instance)
FILED_FANOUT_M = {"sequential": 22.24, "snake": 28.00, "clustered": 30.00,
                  "least_manhattan": 29.12, "nmap_greedy": 26.76,
                  "heaviest_first": 19.29, "random": 18.29}
FILED_CHAIN_M = {"sequential": 8.47, "snake": 15.06, "clustered": 6.18,
                 "least_manhattan": 7.24, "nmap_greedy": 8.06,
                 "heaviest_first": 8.76, "random": 7.00}


def run_leg(W, pairs, seeds, label):
    J = CrossTrafficJ(W, pairs)
    rungs = {n: J(pi) for n, pi in seeds.items()}
    best_name, results = sa.multistart(J, seeds, 576, SCHED,
                                       seed=BASE_SEED)
    best = results[best_name]
    assert abs(J.full_check(best.best_pi) - best.best_j) \
        <= 1e-9 * max(best.best_j, 1.0), "incremental drifted from full"
    return {"label": label,
            "rungs_words": rungs,
            "per_start": {n: {"best_j": r.best_j, "start_j": r.start_j,
                              "accepted": r.accepted,
                              "proposed": r.proposed}
                          for n, r in results.items()},
            "best_start": best_name,
            "best_j_words": best.best_j,
            "best_pi": best.best_pi.to_json(),
            "regret_vs_best_named": best.best_j / min(rungs.values()),
            "regret_vs_rung": {n: best.best_j / v
                               for n, v in rungs.items()}}


def main():
    W = host()
    seeds = {n: sb.generate(n, W, seed=0) for n in sb.NAMES}
    out = {"V_words": V, "fanout": FANOUT,
           "quantifier": "observed",
           "evaluation_set": "7 named seeds x multi-start SA",
           "schedule": {
               "t0": SCHED.t0, "alpha": SCHED.alpha, "steps": SCHED.steps,
               "base_seed": BASE_SEED},
           "delta_column": "1.00 by construction (packet-free mesh)"}
    for key, pairs, filed in (("active_fanout", pairs_fanout(),
                               FILED_FANOUT_M),
                              ("control_chain", pairs_chain(),
                               FILED_CHAIN_M)):
        leg = run_leg(W, pairs, seeds, key)
        for n, v in leg["rungs_words"].items():   # anchor vs filed ladder
            assert abs(v / 1e6 - filed[n]) < 0.005, (key, n, v)
        out[key] = leg
        best_named = min(leg["rungs_words"], key=leg["rungs_words"].get)
        print(f"[{key}] named rungs (M words): " + ", ".join(
            f"{n}={v/1e6:.2f}" for n, v in sorted(
                leg["rungs_words"].items(), key=lambda kv: kv[1])))
        print(f"[{key}] search best {leg['best_j_words']/1e6:.3f}M "
              f"(start: {leg['best_start']}) vs best named "
              f"{best_named} {leg['rungs_words'][best_named]/1e6:.2f}M "
              f"-> regret {leg['regret_vs_best_named']:.4f} "
              f"({(1-leg['regret_vs_best_named'])*100:.1f}% below)")
    json.dump(out, open(OUT_JSON, "w"), indent=1)
    print(f"results -> {OUT_JSON}")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, key, title in ((axes[0], "active_fanout",
                            "active leg: fan-out (+2,+4,+8)"),
                           (axes[1], "control_chain",
                            "control leg: uniform chain")):
        leg = out[key]
        names = sorted(leg["rungs_words"], key=leg["rungs_words"].get,
                       reverse=True)
        vals = [leg["rungs_words"][n] / 1e6 for n in names]
        ax.bar(range(len(names)), vals, color="#888")
        ax.bar([len(names)], [leg["best_j_words"] / 1e6], color="#c44")
        ax.set_xticks(range(len(names) + 1))
        ax.set_xticklabels(names + ["SA search"], rotation=35,
                           ha="right", fontsize=8)
        ax.set_ylabel("busiest wire (M words)")
        ax.set_title(title, fontsize=9)
        for i, v in enumerate(vals + [leg["best_j_words"] / 1e6]):
            ax.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=7)
    fig.suptitle("ordering instance (S3 day 7): named rungs vs SA, "
                 "busiest-wire caliber, declared cross-traffic load",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    print(f"figure -> {OUT_PNG}")


if __name__ == "__main__":
    main()
