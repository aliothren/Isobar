"""Item 4: the 544-die seating search's final statistics.

Distinguished explicitly: THREE START FAMILIES (clustered / snake /
random) x THREE INDEPENDENT SA SEEDS per cell, the standing schedule;
plus the RANDOM BASELINE'S OWN DISTRIBUTION (seeds 0-4) at both
cells. SA seed s = 0 with the per-start index i reproduces the standing
runs bit-for-bit (seed = 1000003*s + i, i over the SORTED start names,
as seating_leg enumerates them); s = 1, 2 are new.

Reported per cell: every (start, seed) endpoint; endpoint spread;
random baseline min / median / max; the gain against the STRONGEST
baseline (min over the seven named rules at seed 0 and the five random
seeds); a budget-quality curve per run (best-so-far every 100 J calls).

    python3 scripts/rerun_seating_seeds.py -> analysis/seating_seeds.json + .png
"""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_linkage as sl
from scripts import search_sa as sa

OUT = os.path.join(se.A, "seating_seeds.json")
PNG = os.path.join(se.A, "seating_seeds.png")
CELLS = {"grs": sl.GRS, "weak": sl.WEAK}
SA_SEEDS = (0, 1, 2)
RANDOM_SEEDS = (0, 1, 2, 3, 4)
CURVE_EVERY = 100


class Traced:
    """Wraps a session objective to record best-so-far per J call."""

    def __init__(self, J):
        self.J, self.calls, self.best, self.curve = J, 0, float("inf"), []

    def __call__(self, pi):
        v = self.J(pi)
        self.calls += 1
        self.best = min(self.best, v)
        if self.calls % CURVE_EVERY == 0:
            self.curve.append((self.calls, self.best))
        return v


def main():
    W = se.Workload2p7B()
    n_slots = W.fab.level("die").per_parent
    lad = json.load(open(os.path.join(se.A, "ladder_v0.json")))["table_2p7b"]
    starts = {n: sb.generate(n, W, seed=0) for n in sl.SEATING_SEEDS}
    randoms = {s: sb.generate("random", W, seed=s) for s in RANDOM_SEEDS}
    out = {"note": __doc__.split("\n\n")[1], "sa_seeds": SA_SEEDS,
           "random_seeds": RANDOM_SEEDS, "cells": {}}
    key = {"grs": "t_single_safe_s", "weak": "t_single_weak_d2d_s"}
    for cell, bw in CELLS.items():
        sched = sl.SEATING_SCHED[bw]
        runs, curves = {}, {}
        for i, name in enumerate(sorted(sl.SEATING_SEEDS)):   # seating_leg's order
            for s in SA_SEEDS:
                J = Traced(sl.SessionJ(W, starts[name], "t", bw))
                r = sa.anneal(J, starts[name], n_slots, sched,
                              seed=1000003 * s + i)
                runs[f"{name}/s{s}"] = {"start": name, "sa_seed": s,
                                        "start_j": r.start_j, "best_j": r.best_j,
                                        "accepted": r.accepted,
                                        "best_pi": r.best_pi.to_json()}
                curves[f"{name}/s{s}"] = J.curve
        rnd = {s: se.score(randoms[s], W, caliber="single", d2d_gbps=bw).t_opt_s
               for s in RANDOM_SEEDS}
        named = {n: lad[n][key[cell]] for n in lad}
        strongest_named = min(named, key=named.get)
        strongest = min(min(named.values()), min(rnd.values()))
        ends = [v["best_j"] for v in runs.values()]
        best_run = min(runs, key=lambda k: runs[k]["best_j"])
        out["cells"][cell] = {
            "d2d_gbps": bw, "schedule": {"t0": sched.t0, "alpha": sched.alpha,
                                         "steps": sched.steps},
            "runs": runs, "curves": curves,
            "endpoints": {"min_s": min(ends), "median_s": statistics.median(ends),
                          "max_s": max(ends),
                          "spread_pct": (max(ends) / min(ends) - 1) * 100,
                          "best_run": best_run},
            "random_baseline": {"per_seed_s": rnd, "min_s": min(rnd.values()),
                                "median_s": statistics.median(rnd.values()),
                                "max_s": max(rnd.values()),
                                "spread_pct": (max(rnd.values()) / min(rnd.values()) - 1) * 100},
            "strongest_baseline": {"named_rule_seed0": strongest_named,
                                   "named_s": named[strongest_named],
                                   "overall_s": strongest,
                                   "is_a_random_seed": strongest < min(named.values())},
            "gain_vs_strongest_pct": (1 - min(ends) / strongest) * 100,
            "gain_vs_random_seed0_pct_record": (1 - min(ends) / rnd[0]) * 100,
            "gain_seed0_runs_only_pct_record": (
                1 - min(v["best_j"] for v in runs.values() if v["sa_seed"] == 0)
                / rnd[0]) * 100}
        c = out["cells"][cell]
        print(f"[{cell} {bw} GB/s]")
        for k, v in runs.items():
            print(f"   {k:14} start {v['start_j']*1e3:9.2f} -> best "
                  f"{v['best_j']*1e3:9.2f} ms  (accepted {v['accepted']})")
        e = c["endpoints"]
        print(f"   endpoints min/median/max {e['min_s']*1e3:.2f} / "
              f"{e['median_s']*1e3:.2f} / {e['max_s']*1e3:.2f} ms, spread "
              f"{e['spread_pct']:.3f}% (best {e['best_run']})")
        rb = c["random_baseline"]
        print(f"   random baseline seeds 0-4: min/median/max {rb['min_s']*1e3:.2f} / "
              f"{rb['median_s']*1e3:.2f} / {rb['max_s']*1e3:.2f} ms, spread "
              f"{rb['spread_pct']:.3f}%")
        sbx = c["strongest_baseline"]
        print(f"   strongest baseline {sbx['overall_s']*1e3:.2f} ms "
              f"({'a random seed' if sbx['is_a_random_seed'] else sbx['named_rule_seed0']})")
        print(f"   gain vs strongest {c['gain_vs_strongest_pct']:.3f}% | vs random "
              f"seed 0 {c['gain_vs_random_seed0_pct_record']:.3f}% | seed-0 runs "
              f"only (the record) {c['gain_seed0_runs_only_pct_record']:.3f}%")
    json.dump(out, open(OUT, "w"), indent=1)

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    for ax, (cell, c) in zip(axes, out["cells"].items()):
        col = {"clustered": "#2e4a66", "snake": "#7a5c00", "random": "#2a7d4f"}
        for k, cv in c["curves"].items():
            name = k.split("/")[0]
            ax.plot([x for x, _ in cv], [y * 1e3 for _, y in cv], color=col[name],
                    lw=0.9, alpha=0.8, label=name if k.endswith("/s0") else None)
        rb = c["random_baseline"]
        ax.axhspan(rb["min_s"] * 1e3, rb["max_s"] * 1e3, color="#2a7d4f",
                   alpha=0.12, lw=0, label="random baseline, seeds 0-4")
        ax.set_title(f"{cell}: {c['d2d_gbps']} GB/s -- 3 starts x 3 SA seeds",
                     fontsize=9)
        ax.set_xlabel("objective evaluations")
        ax.set_ylabel("best-so-far latency (ms)")
        ax.grid(alpha=0.2)
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(PNG, dpi=150)
    print(f"-> {OUT}\n-> {PNG}")


if __name__ == "__main__":
    main()
