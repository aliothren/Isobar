"""S7 / instance B, full instance: the fan-out search with independent
seeds, and the readings the writer asked for.

Objective: S6's E2b (fan-out busiest-wire load, CrossTrafficJ on the
+2/+4/+8 pairs), 2000 steps, alpha 0.996, t0 = span/20 over the seven
named rungs; THREE independent SA seeds from the random start (the
strongest rule) and one run from the clustered start for contrast.
Per candidate: A (links AND ports, words), link-only A, the port floor,
A/floor, and whether the busiest resource is a link or a port.

    python3 scripts/b_fanout_search.py -> analysis/b_fanout_search.json + .png
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import check_c_crosstraffic as cx
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_ordering as so
from scripts import search_sa as sa

OUT = os.path.join(se.A, "b_fanout_search.json")
PNG = os.path.join(se.A, "b_fanout_search.png")
SEEDS = (0, 1, 2)
STEPS, ALPHA = 2000, 0.996
CURVE_EVERY = 100


class Traced:
    def __init__(self, J):
        self.J, self.calls, self.best, self.curve = J, 0, float("inf"), []

    def __call__(self, pi):
        v = self.J(pi)
        self.calls += 1
        self.best = min(self.best, v)
        if self.calls % CURVE_EVERY == 0:
            self.curve.append((self.calls, self.best))
        return v


def readings(W, pi, pairs):
    sets = cx.stage_sets(pi)
    flows = []
    for s, t in pairs:
        flows += se._one_boundary_flows(
            {"name": f"stage{s}", "out_words": cx.V, "split": "R"},
            {"name": f"stage{t}", "in_words": cx.V}, sets[s], sets[t], W.fab)
    a_link = se.busiest_link_words(flows, W.die_ic, ports=False)
    a_all = se.busiest_link_words(flows, W.die_ic, ports=True)
    inj, ej = {}, {}
    for f in flows:
        w = f["volume"] * f["width"]
        inj[f["nodes"][0]] = inj.get(f["nodes"][0], 0.0) + w
        ej[f["nodes"][1]] = ej.get(f["nodes"][1], 0.0) + w
    port = max(max(inj.values()), max(ej.values()))
    return {"A_words": a_all, "A_link_only_words": a_link, "port_max_words": port,
            "floor_words": port, "A_over_floor": a_all / port,
            "busiest_is": "port" if port >= a_link else "link"}


def main():
    W = cx.host()
    pairs = so.pairs_fanout()
    n_slots = W.fab.level("die").per_parent
    cands = {n: sb.generate(n, W, seed=0) for n in cx.SEATINGS}
    for s in (1, 2, 3, 4):
        cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
    J0 = so.CrossTrafficJ(W, pairs)
    rungs = {n: J0(cands[n]) for n in cx.SEATINGS}
    t0 = (max(rungs.values()) - min(rungs.values())) / 20.0
    sched = sa.Schedule(t0=t0, alpha=ALPHA, steps=STEPS)
    runs = {}
    for start, seeds in (("random", SEEDS), ("clustered", (0,))):
        for s in seeds:
            J = Traced(so.CrossTrafficJ(W, pairs))
            t = time.perf_counter()
            r = sa.anneal(J, cands[start], n_slots, sched, seed=7919 * s + 11)
            key = f"sa_from_{start}_s{s}"
            runs[key] = {"start": start, "sa_seed": s, "t0_words": t0,
                         "start_j_words": r.start_j, "best_j_words": r.best_j,
                         "accepted": r.accepted, "wall_s": time.perf_counter() - t,
                         "curve": J.curve, "best_pi": r.best_pi.to_json()}
            cands[key] = r.best_pi
            print(f"  {key:22} start {r.start_j/1e6:.2f}M -> best {r.best_j/1e6:.2f}M words "
                  f"(accepted {r.accepted}, {runs[key]['wall_s']:.0f} s)")
    rows = {n: readings(W, pi, pairs) for n, pi in cands.items()}
    rnd = [n for n in cands if n == "random" or n.startswith("random_s")]
    strongest = min(rnd, key=lambda n: rows[n]["A_words"])
    ends = [n for n in cands if n.startswith("sa_from_random")]
    for n in cands:
        rows[n]["eta_vs_random_seed0"] = 1 - rows[n]["A_words"] / rows["random"]["A_words"]
        rows[n]["eta_vs_strongest_random"] = 1 - rows[n]["A_words"] / rows[strongest]["A_words"]
    end_A = [rows[n]["A_words"] for n in ends]
    out = {"note": __doc__.strip(), "V_words": cx.V, "n_pairs": len(pairs),
           "schedule": {"t0_words": t0, "alpha": ALPHA, "steps": STEPS},
           "runs": runs, "rows": rows, "strongest_random": strongest,
           "endpoints_random_start": {"A_min": min(end_A), "A_median": statistics.median(end_A),
                                      "A_max": max(end_A),
                                      "spread_pct": (max(end_A) / min(end_A) - 1) * 100}}
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"{'candidate':22} {'A (M)':>7} {'link-only':>9} {'floor':>6} {'A/floor':>7} "
          f"{'busiest':>7} {'eta vs s0':>9} {'eta vs best rnd':>15}")
    for n in cands:
        r = rows[n]
        print(f"{n:22} {r['A_words']/1e6:7.2f} {r['A_link_only_words']/1e6:9.2f} "
              f"{r['floor_words']/1e6:6.2f} {r['A_over_floor']:7.2f} {r['busiest_is']:>7} "
              f"{r['eta_vs_random_seed0']*100:8.2f}% {r['eta_vs_strongest_random']*100:14.2f}%")
    e = out["endpoints_random_start"]
    print(f"endpoints (random start, 3 seeds): A {e['A_min']/1e6:.2f} / {e['A_median']/1e6:.2f} / "
          f"{e['A_max']/1e6:.2f} M, spread {e['spread_pct']:.2f}%; strongest random = {strongest}")

    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for k, v in runs.items():
        ax.plot([x for x, _ in v["curve"]], [y / 1e6 for _, y in v["curve"]],
                lw=0.9, label=k)
    lo = min(rows[n]["A_words"] for n in rnd) / 1e6
    hi = max(rows[n]["A_words"] for n in rnd) / 1e6
    ax.axhspan(lo, hi, color="#2a7d4f", alpha=0.12, lw=0, label="random draws, seeds 0-4")
    ax.axhline(rows["random"]["floor_words"] / 1e6, color="0.4", ls=":", lw=0.9,
               label="port floor")
    ax.set_xlabel("objective evaluations")
    ax.set_ylabel("busiest-resource load (M words)")
    ax.set_title("Instance B: fan-out search, best-so-far", fontsize=9)
    ax.grid(alpha=0.2)
    ax.legend(fontsize=6.5)
    fig.tight_layout()
    fig.savefig(PNG, dpi=150)
    print(f"-> {OUT}\n-> {PNG}")


if __name__ == "__main__":
    main()
