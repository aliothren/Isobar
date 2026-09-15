"""The band-energy experiment (post-D.3 review question): inside the
LATENCY CONVERGENCE BAND (T <= 1.018 x the cell's T-optimum) find the
energy minimum, and report it against the energy-optimum seating
together with the geometry of the two optima.

Rejection-mode SA (spec section 6: an infeasible proposal is rejected,
never penalised) minimising E with feasibility T <= cap; one
ScoreSession pass per proposal serves both the feasibility test and
the objective. Seed = the cell's T-best seating (search_linkage.json);
three RNG seeds; Schedule(t0 = 0.005 J, alpha 0.996, 1500 steps);
cells GRS and 0.4 GB/s. Geometry read-out per seating: busiest/total
(link stacking), distance surplus energy, mean max hops.

    python3 scripts/band_energy.py -> analysis/band_energy.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_linkage as sl
from scripts import search_sa as sa
from scripts import search_space as ss

BAND = 0.018
BANDS = (0.018, 0.036, 0.072)      # the sweep (reviewer's reinforcement)
SCHED = sa.Schedule(t0=0.005, alpha=0.996, steps=1500)
OUT = os.path.join(se.A, "band_energy.json")


class BandE:
    """E objective + T-band feasibility from ONE evaluation per Pi."""

    def __init__(self, W, pi0, cap_s, d2d_gbps):
        self.sess = se.ScoreSession(pi0, W, d2d_gbps=d2d_gbps)
        self.W, self.cap = W, cap_s
        self._last = (None, None)

    def _eval(self, pi):
        if self._last[0] is pi:
            return self._last[1]
        delta = {n: tuple(v) for n, v in pi.seat.items()
                 if tuple(v) != tuple(self.sess.pi.seat[n])}
        sc = self.sess.update(delta) if delta else \
            se._assemble(self.sess.pi, self.W, self.sess.bs, self.sess.mu,
                         self.sess.caliber, self.sess.d2d_gbps,
                         self.sess.device_scale)
        self._last = (pi, sc)
        return sc

    def feasible(self, pi):
        return self._eval(pi).t_opt_s <= self.cap

    def __call__(self, pi):
        return self._eval(pi).e_J


def geometry(W, pi, bw):
    sc = se.score(pi, W, d2d_gbps=bw)
    bs = W.boundaries(pi, "prefill")
    d = sc.per_phase["prefill"]["decomp"]
    return {"t_s": sc.t_opt_s, "e_J": sc.e_J,
            "busiest_over_total": d["d2d_busiest_words"] / d["d2d_words"],
            "surplus_J": d["d2d_surplus_J"],
            "mean_max_hops": sum(b["max_hops"] for b in bs) / len(bs)}


def band_point(W, bw, t_best_pi, e_best_pi, g_t, g_e, band, prev_pi=None):
    """One (cell, band width) point of the trade-off front. `prev_pi` is
    the NEXT-NARROWER band's minimum: it is feasible here by nesting, so
    seeding with it makes the front monotone BY CONSTRUCTION (the first
    port rerun tripped the monotonicity guard by ~1e-6 -- two SA runs
    from the same seeds at different caps wandering differently, a
    search artifact, not a space property)."""
    cap = g_t["t_s"] * (1.0 + band)
    # seed 2 (addendum): the E-best seating polished INTO the band by
    # greedy T descent, then band-constrained E minimisation from it
    Jt = sl.SessionJ(W, e_best_pi, "t", bw)
    pol = sa.anneal(Jt, e_best_pi, 576, sa.Schedule(t0=0.0, steps=600),
                    seed=0)
    compact_seed = pol.best_pi
    compact_ok = geometry(W, compact_seed, bw)["t_s"] <= cap
    seeds_by_side = {"dispersed": t_best_pi}
    if compact_ok:
        seeds_by_side["compact"] = compact_seed
    # the known feasible point: once the band is wide enough to contain
    # the E-best seating itself, it is a legal start and its energy is an
    # upper bound on the band minimum -- omitting it let the first sweep
    # report +4.32% at bands that already contained the 0% point (a
    # search-quality failure, recorded)
    if g_e["t_s"] <= cap:
        seeds_by_side["e_best"] = e_best_pi
    if prev_pi is not None:
        seeds_by_side["narrower_band"] = prev_pi
    runs, best = {}, None
    for side, seed_pi in seeds_by_side.items():
        for seed in (0, 1, 2):
            J = BandE(W, seed_pi, cap, bw)
            r = sa.anneal(J, seed_pi, 576, SCHED, seed=seed,
                          feasible=J.feasible)
            runs[f"{side}/{seed}"] = {
                "best_e_J": r.best_j, "accepted": r.accepted,
                "rejected_infeasible": r.rejected_infeasible}
            if best is None or r.best_j < best.best_j:
                best = r
    g_b = geometry(W, best.best_pi, bw)
    g_c = geometry(W, compact_seed, bw)
    assert g_b["t_s"] <= cap + 1e-12
    return {"band": band, "d2d_gbps": bw, "cap_s": cap, "runs": runs,
            "compact_seed_reachable": compact_ok, "compact_seed": g_c,
            "t_best": g_t, "e_best": g_e, "band_min": g_b,
            "band_min_pi": best.best_pi.to_json(),
            "band_min_e_over_e_best": g_b["e_J"] / g_e["e_J"],
            "t_best_e_over_e_best": g_t["e_J"] / g_e["e_J"],
            "e_best_in_band": g_e["t_s"] <= cap}


def main():
    W = se.Workload2p7B()
    link = json.load(open(sl.OUT_JSON))
    e_best_pi = sb.generate("clustered", W, seed=0)
    out = {"band": BAND, "bands": BANDS, "cells": {}, "front": {},
           "quantifier": "observed",
           "evaluation_set": "dispersed + compact-polished + (when in band) the E-best seed, 3 RNG seeds each"}
    for tag, bw, leg in (("grs", sl.GRS, "seating_mesh_grs"),
                         ("weak", sl.WEAK, "seating_mesh_weak")):
        t_best_pi = ss.Pi.from_json(link[leg]["best_pi"])
        g_t = geometry(W, t_best_pi, bw)
        g_e = geometry(W, e_best_pi, bw)
        front, prev = [], None
        for band in sorted(BANDS):
            c = band_point(W, bw, t_best_pi, e_best_pi, g_t, g_e, band, prev)
            prev = ss.Pi.from_json(c["band_min_pi"])
            front.append(c)
            if band == BAND:
                out["cells"][tag] = c
            g_b = c["band_min"]
            print(f"[{tag} {bw} GB/s band {band*100:.1f}%] cap "
                  f"{c['cap_s']*1e3:.2f} ms | band min T {g_b['t_s']*1e3:.2f} "
                  f"E {g_b['e_J']:.4f} (+{(c['band_min_e_over_e_best']-1)*100:.2f}%"
                  f" vs E-best) b/t {g_b['busiest_over_total']:.3f} hops "
                  f"{g_b['mean_max_hops']:.1f} | E-best "
                  f"{'IN' if c['e_best_in_band'] else 'OUT of'} band | compact "
                  f"seed {'reachable' if c['compact_seed_reachable'] else 'NOT reachable'}")
        out["front"][tag] = [
            {"band": c["band"], "cap_s": c["cap_s"],
             "band_min_t_s": c["band_min"]["t_s"],
             "band_min_e_J": c["band_min"]["e_J"],
             "e_over_e_best": c["band_min_e_over_e_best"],
             "latency_paid_pct": (c["band_min"]["t_s"] / g_t["t_s"] - 1) * 100,
             "energy_bought_pct": (c["t_best_e_over_e_best"]
                                   - c["band_min_e_over_e_best"]) * 100,
             "e_best_in_band": c["e_best_in_band"]} for c in front]
        es = [c["band_min_e_over_e_best"] for c in front]
        assert all(b <= a + 1e-12 for a, b in zip(es, es[1:])), \
            "front not monotone: search-quality finding"
        for c_ in front:          # the feasible-point bound, now seeded
            assert not c_["e_best_in_band"] or \
                c_["band_min_e_over_e_best"] <= 1.0 + 1e-12, \
                "E-best feasible but not found: search-quality finding"
        c = out["cells"][tag]
        print(f"[{tag} {bw} GB/s, the {BAND*100:.1f}% band] T-best: T "
              f"{g_t['t_s']*1e3:.2f} E {g_t['e_J']:.4f} (+{(c['t_best_e_over_e_best']-1)*100:.2f}% "
              f"vs E-best) b/t {g_t['busiest_over_total']:.3f} surplus "
              f"{g_t['surplus_J']:.4f} hops {g_t['mean_max_hops']:.2f}")
        print(f"   E-best (clustered): T {g_e['t_s']*1e3:.2f} "
              f"({'IN' if c['e_best_in_band'] else 'OUT of'} band) E "
              f"{g_e['e_J']:.4f} b/t {g_e['busiest_over_total']:.3f} surplus "
              f"{g_e['surplus_J']:.4f} hops {g_e['mean_max_hops']:.2f}")
        g_c, g_b, runs = c["compact_seed"], c["band_min"], c["runs"]
        print(f"   compact-side seed (clustered polished by T descent): T "
              f"{g_c['t_s']*1e3:.2f} "
              f"({'IN' if c['compact_seed_reachable'] else 'NOT in'} band) "
              f"E {g_c['e_J']:.4f} b/t {g_c['busiest_over_total']:.3f}")
        print(f"   BAND MIN: T {g_b['t_s']*1e3:.2f} E {g_b['e_J']:.4f} "
              f"(+{(c['band_min_e_over_e_best']-1)*100:.2f}% vs E-best) b/t "
              f"{g_b['busiest_over_total']:.3f} surplus {g_b['surplus_J']:.4f} "
              f"hops {g_b['mean_max_hops']:.2f}; per-run best E "
              f"{ {k: round(v['best_e_J'],4) for k, v in runs.items()} }, "
              f"infeasible rejections "
              f"{ {k: v['rejected_infeasible'] for k, v in runs.items()} }")
    json.dump(out, open(OUT, "w"), indent=1)
    print("\nTRADE-OFF FRONT (latency paid -> energy bought, vs the "
          "E-best seating):")
    for tag in out["front"]:
        for r in out["front"][tag]:
            print(f"  {tag:5} band {r['band']*100:4.1f}%: latency paid "
                  f"{r['latency_paid_pct']:5.2f}%, energy still "
                  f"{(r['e_over_e_best']-1)*100:5.2f}% above E-best "
                  f"(bought back {r['energy_bought_pct']:5.2f} points)"
                  + ("  [E-best inside the band]" if r["e_best_in_band"] else ""))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
