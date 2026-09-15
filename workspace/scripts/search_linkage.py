"""S4 day 10 (C64-e): the DP+SA linkage on the A4 payload + the three
exhibits + the two front-matter dues.

Pieces (re-issued under the corrected hand-off accounting, D.3 items
3-4; pre-registered in FIXLIST before any number):
  * SessionJ -- the diff-driven ScoreSession-backed incremental
    objective; [AMENDED 15]: the 2.7B SEATING instance's main objective
    is T (E the tie-break, reported alongside); run at the GRS and the
    weak-D2D cells.
  * constrained(B) -- min T_decode (single caliber) s.t. every prefill
    stage <= B, EXACT under the D.2 cost table (per-layer, seat-
    dependent times and fees); the B-scan staircase is EX1.
  * backfill(seating) -- the D.2 loop: the DP table rebuilt at the
    SA-found seating vs the A4 default, judged under the pre-registered
    "no cut change AND shift < 1%" standard.
  * weave exhibit (EX2) -- the seating SA rerun under torus / ring vs
    the mesh default, T objective (the latency side now carries the
    weave: hand-offs are routed on it).
  * seam exhibit (EX3) -- cuts bound to the A4 seam example (2 layers
    per package, 16 segments) vs the DP's free plan at the same k.

    python3 scripts/search_linkage.py        (the official run)
"""
import json
import os
import sys
from typing import Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import search_baselines as sb
from scripts import search_dp as sd
from scripts import search_eval as se
from scripts import search_sa as sa
from scripts import search_space as ss

GRS = 12.5
WEAK = 0.4
B_PREFILL_S = 0.120                 # the proposed demonstration budget
# [AMENDED 15]: the seating instance's main objective is T (E tie-break);
# t0 in seconds, declared per cell (hand-off moves scale with 1/bw)
SEATING_SCHED = {GRS: sa.Schedule(t0=0.002, alpha=0.996, steps=1200),
                 WEAK: sa.Schedule(t0=0.020, alpha=0.996, steps=1200)}
SEATING_SEEDS = ("clustered", "snake", "random")
OUT_JSON = os.path.join(se.A, "search_linkage.json")
# the ladder rungs are READ from the regenerated table rather than
# transcribed: a hard-coded copy went stale the moment the hand-off
# term changed (the port revision), and a regret against stale rungs
# is meaningless -- caught on the first port rerun, fixed here.
def _ladder(cell_key):
    t = json.load(open(os.path.join(se.A, "ladder_v0.json")))["table_2p7b"]
    return {n: r[cell_key] for n, r in t.items()}
LADDER_E = {"clustered": 2.3379, "least_manhattan": 2.3382,
            "nmap_greedy": 2.3393, "snake": 2.3537, "sequential": 2.3937,
            "heaviest_first": 2.4394, "random": 2.5251}


# --------------------------------------------- the seating objective(s)
class SessionJ:
    """Diff-driven incremental objective on ScoreSession: any requested
    Pi is diffed against the committed seat and applied via update()
    (the engine's reject-then-move-on sequence needs no explicit
    rollback). column = "t" (t_opt_s, the [AMENDED 15] main objective)
    or "e" (e_J); the other column rides along via last_score."""

    def __init__(self, W, pi0, column="t", d2d_gbps=GRS):
        self.W, self.column = W, column
        self.sess = se.ScoreSession(pi0, W, d2d_gbps=d2d_gbps)
        self.last_score = None

    def __call__(self, pi) -> float:
        delta = {n: tuple(v) for n, v in pi.seat.items()
                 if tuple(v) != tuple(self.sess.pi.seat[n])}
        sc = self.sess.update(delta) if delta else \
            se._assemble(self.sess.pi, self.W, self.sess.bs, self.sess.mu,
                         self.sess.caliber, self.sess.d2d_gbps,
                         self.sess.device_scale)
        self.last_score = sc
        return sc.t_opt_s if self.column == "t" else sc.e_J


class SessionE(SessionJ):
    """The energy column (kept for the L2 pin and the tie-break)."""

    def __init__(self, W, pi0, d2d_gbps=GRS):
        super().__init__(W, pi0, "e", d2d_gbps)


def seating_leg(W, label, column="t", d2d_gbps=GRS, seeds=SEATING_SEEDS,
                sched=None):
    """The 2.7B seating instance: multi-start SA on the declared column
    at the declared cell; both columns reported for the winner."""
    sched = sched or SEATING_SCHED[d2d_gbps]
    pis = {n: sb.generate(n, W, seed=0) for n in seeds}
    results = {}
    for i, name in enumerate(sorted(pis)):
        J = SessionJ(W, pis[name], column, d2d_gbps)
        r = sa.anneal(J, pis[name], W.fab.level("die").per_parent, sched,
                      seed=1000003 * 0 + i)
        results[name] = r
    best = min(sorted(results), key=lambda n: results[n].best_j)
    r = results[best]
    sc = se.score(r.best_pi, W, d2d_gbps=d2d_gbps)
    d = sc.per_phase["prefill"]["decomp"]
    return {"label": label, "column": column, "d2d_gbps": d2d_gbps,
            "per_start": {n: {"start_j": x.start_j, "best_j": x.best_j,
                              "accepted": x.accepted}
                          for n, x in results.items()},
            "best_start": best, "best_j": r.best_j,
            "best_t_single_s": sc.t_opt_s, "best_e_J": sc.e_J,
            "best_busiest_over_total": d["d2d_busiest_words"] / d["d2d_words"],
            "best_pi": r.best_pi.to_json()}


# ------------------------------------------------ the constrained exhibit
def constrained(B_s: float, pi=None):
    """min T_decode(single) s.t. T_prefill(pipe interval) <= B -- EXACT
    under the D.2 cost table (per-layer, seat-dependent prefill and
    decode times and fees at the given seating; default A4). The
    interval constraint is per segment, so the problem is a 1-D DP:
    F(j) = min over i < j with prefill_stage(i, j) <= B of
    F(i) + decode_fee(i); T_decode = sum of decode layer times + F(L).
    (The former k-indexed staircase assumed uniform layers and
    inter-layer-only fees; superseded.)"""
    return _solve_constrained(_tables(pi), B_s)


_TABLES = {}


def _tables(pi=None):
    """The D.2 cost tables (prefill + decode) at a seating, built once
    per seating object and cached -- the B-scan must not rebuild them."""
    key = id(pi) if pi is not None else None
    if key not in _TABLES:
        inst_p, meta_p = sd.standing_instance(pi, "prefill", GRS)
        inst_d, meta_d = sd.standing_instance(pi, "decode", GRS)
        _TABLES[key] = (meta_p["L"], [t[0] for t in inst_p.taus],
                        [t[0] for t in inst_d.taus], inst_p.fees,
                        inst_d.fees)
    return _TABLES[key]


def _solve_constrained(tables, B_s: float):
    L, tau_p, tau_d, fee_p, fee_d = tables
    pre = [0.0]
    for t in tau_p:
        pre.append(pre[-1] + t)

    def stage(i, j):
        return pre[j] - pre[i] + fee_p[i]

    INF = float("inf")
    # objective = (decode fee sum, number of cuts): with the frozen
    # model's zero cut fee every feasible segmentation ties on decode,
    # and the fewest-cuts plan is returned (the smallest feasible depth)
    F = [(INF, INF)] * (L + 1)
    back = [None] * (L + 1)
    F[0] = (0.0, 0)
    for j in range(1, L + 1):
        for i in range(j):
            if F[i][0] < INF and stage(i, j) <= B_s + 1e-15:
                c = (F[i][0] + fee_d[i], F[i][1] + (1 if i > 0 else 0))
                if c < F[j]:
                    F[j], back[j] = c, i
    if F[L][0] == INF:
        return {"B_s": B_s, "feasible": False, "meta": {
            "min_single_layer_stage_s": max(tau_p[i] + fee_p[i]
                                            for i in range(L))}}
    cuts, j = [], L
    while j > 0:
        i = back[j]
        if i > 0:
            cuts.append(i)
        j = i
    cuts.sort()
    bounds = [0] + cuts + [L]
    segs = list(zip(bounds[:-1], bounds[1:]))
    return {"B_s": B_s, "feasible": True, "k": len(segs),
            "cuts": cuts, "segment_sizes": [j - i for i, j in segs],
            "t_prefill_s": max(stage(i, j) for i, j in segs),
            "t_decode_s": sum(tau_d) + F[L][0],
            "t_decode_unconstrained_s": sum(tau_d),      # k = 1
            "meta": {"tau_p_range_s": (min(tau_p), max(tau_p)),
                     "fee_p_range_s": (min(fee_p[1:]), max(fee_p[1:])),
                     "fee_d_range_s": (min(fee_d[1:]), max(fee_d[1:]))}}


def staircase(pi=None, B_lo_s=0.025, B_hi_s=1.100, step_s=0.00025):
    """The critical points: scanning B, the budgets at which k* changes,
    with the readings on both sides."""
    steps, last_k = [], None
    tables = _tables(pi)
    B = B_hi_s
    while B >= B_lo_s - 1e-12:
        c = _solve_constrained(tables, B)
        k = c["k"] if c["feasible"] else None
        if k != last_k:
            steps.append({"B_s": B, "k": k,
                          "t_prefill_s": c.get("t_prefill_s"),
                          "t_decode_s": c.get("t_decode_s")})
            last_k = k
        B -= step_s
    return steps


# --------------------------------- the DP-at-seating loop (D.2 ruling)
def backfill(pi_best, ks=(2, 4, 8, 16, 32)):
    """D.2's loop: the DP cost table is rebuilt at the SA-found seating
    and compared with the table at the A4 default seating -- do the cut
    decisions change, and by how much does the bottleneck stage move?
    Judged under the pre-registered "no cut change AND shift < 1%"
    standard. (The former hop-optimism backfill is superseded: costs are
    now actual at whichever seating the table is built on.)"""
    inst_ref, meta_ref = sd.standing_instance()             # A4 seating
    inst_act, meta_act = sd.standing_instance(pi_best)      # SA seating
    out = {"per_k": [],
           "d2d_total_ref_s": meta_ref["d2d_total_s"],
           "d2d_total_act_s": meta_act["d2d_total_s"]}
    for k in ks:
        v_ref, plan_ref = sd.solve(inst_ref, k, "pipe")
        v_act, plan_act = sd.solve(inst_act, k, "pipe")
        out["per_k"].append({
            "k": k, "cuts_ref": [i for i, _, _ in plan_ref],
            "cuts_act": [i for i, _, _ in plan_act],
            "cuts_changed": ([i for i, _, _ in plan_ref]
                             != [i for i, _, _ in plan_act]),
            "bottleneck_ref_s": v_ref, "bottleneck_act_s": v_act,
            "shift_rel": abs(v_act - v_ref) / v_ref})
    out["negligible"] = (all(not r["cuts_changed"] for r in out["per_k"])
                         and all(r["shift_rel"] < 0.01
                                 for r in out["per_k"]))
    return out


# ----------------------------------------------------------- official run
def main():
    out = {"B_prefill_s": B_PREFILL_S, "objective": "t ([AMENDED 15])",
           "quantifier": "observed",
           "evaluation_set": "3 named seeds (clustered/snake/random) x SA; the DP layer is exact"}

    # EX1: the constrained two-phase exhibit, exact under the D.2 table
    c = constrained(B_PREFILL_S)
    out["ex1_constrained"] = c
    st = staircase()
    out["ex1_staircase"] = st
    if c["feasible"]:
        print(f"[EX1] B = {B_PREFILL_S*1e3:.0f} ms -> k* = {c['k']} "
              f"(sizes {c['segment_sizes']}; T_prefill "
              f"{c['t_prefill_s']*1e3:.2f} ms, T_decode "
              f"{c['t_decode_s']*1e3:.3f} ms vs unconstrained k=1 "
              f"{c['t_decode_unconstrained_s']*1e3:.3f} ms)")
    else:
        print(f"[EX1] B = {B_PREFILL_S*1e3:.0f} ms INFEASIBLE (min single-"
              f"layer stage {c['meta']['min_single_layer_stage_s']*1e3:.2f})")
    print("[EX1] staircase (scanning B downward; k* changes at):")
    for s_ in st[:14]:
        print(f"    B = {s_['B_s']*1e3:8.2f} ms -> k* = {s_['k']}"
              + (f"  T_prefill {s_['t_prefill_s']*1e3:.2f}  T_decode "
                 f"{s_['t_decode_s']*1e3:.3f} ms" if s_["k"] else ""))

    # the seating instance ([AMENDED 15]: T objective), GRS and weak cells
    W = se.Workload2p7B()
    for bw, ladder, tag in (
            (GRS, _ladder("t_single_safe_s"), "mesh_grs"),
            (WEAK, _ladder("t_single_weak_d2d_s"), "mesh_weak")):
        leg = seating_leg(W, tag, "t", bw)
        out[f"seating_{tag}"] = leg
        t = leg["best_t_single_s"]
        best_named = min(ladder, key=ladder.get)
        print(f"[SEATING {tag}] best T {t*1e3:.3f} ms (start "
              f"{leg['best_start']}; E {leg['best_e_J']:.4f} J; busiest/"
              f"total {leg['best_busiest_over_total']:.4f}) vs best named "
              f"{best_named} {ladder[best_named]*1e3:.2f} ms -> regret "
              f"{t/ladder[best_named]:.4f}")
        out[f"seating_{tag}_regret_vs_rungs"] = {n: t / v
                                                 for n, v in ladder.items()}

    # D.2's loop: the DP table at the SA-found (GRS) seating vs A4
    bf = backfill(ss.Pi.from_json(out["seating_mesh_grs"]["best_pi"]))
    out["backfill"] = bf
    print(f"[DP@SEATING] cuts changed at any k: "
          f"{any(r['cuts_changed'] for r in bf['per_k'])}; max bottleneck "
          f"shift {max(r['shift_rel'] for r in bf['per_k']):.3e}; D2D total "
          f"A4 {bf['d2d_total_ref_s']*1e3:.2f} ms vs SA seating "
          f"{bf['d2d_total_act_s']*1e3:.2f} ms -> negligible = "
          f"{bf['negligible']}")

    # EX2: weave enumeration, T objective at GRS (the latency side now
    # carries the weave: hand-offs are routed on it)
    for topo, params in (("torus", {}), ("ring", {})):
        Ww = se.Workload2p7B(die_weave=(topo, params))
        legw = seating_leg(Ww, f"weave_{topo}", "t", GRS)
        out[f"seating_{topo}"] = legw
        spread = (max(x["start_j"] for x in legw["per_start"].values())
                  / min(x["best_j"] for x in legw["per_start"].values()))
        print(f"[EX2 {topo}] best T {legw['best_t_single_s']*1e3:.3f} ms "
              f"(E {legw['best_e_J']:.4f} J; start {legw['best_start']}); "
              f"start-spread/best {spread:.4f}")

    # EX3: seam-bound cuts vs the free DP at the seam's OWN segment
    # count (the A4 seam example is 16 packages x 2 layers -> cuts every
    # 2 layers, 16 segments; the day-10 pre-registration misread it as
    # 2 x 16 -- recorded as an expectation-premise error, the corrected
    # baseline is free k = 16)
    inst, meta = sd.standing_instance()
    pi_seam = ss.pi_from_a4_payload(use_seam=True)
    seg = pi_seam.segments()
    k_seam = len(seg)
    v_free, _ = sd.solve(inst, k_seam, "pipe")
    v_seam = max(sum(inst.taus[b][0] for b in range(lo, hi)) + inst.fees[lo]
                 for lo, hi in seg)
    out["ex3_seam"] = {"k_seam": k_seam,
                       "free_same_k_interval_s": v_free,
                       "seam_interval_s": v_seam,
                       "delta_rel": abs(v_seam - v_free) / v_free}
    print(f"[EX3] seam-bound ({k_seam} x {seg[0][1]-seg[0][0]}) interval "
          f"{v_seam*1e3:.4f} ms vs free k={k_seam} {v_free*1e3:.4f} ms -> "
          f"delta {out['ex3_seam']['delta_rel']:.2e}")

    json.dump(out, open(OUT_JSON, "w"), indent=1)
    print(f"results -> {OUT_JSON}")


if __name__ == "__main__":
    main()
