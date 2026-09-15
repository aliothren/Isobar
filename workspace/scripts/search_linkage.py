"""S4 day 10 (C64-e): the DP+SA linkage on the A4 payload + the three
exhibits + the two front-matter dues.

Pieces (pre-registered in FIXLIST before any number):
  * SessionE -- the diff-driven ScoreSession-backed incremental E
    objective (the 2.7B SEATING instance's evaluator; [AMENDED 13]:
    main objective E, T reported alongside as the flat column).
  * constrained(B) -- min T_decode (single caliber: cuts only ADD
    decode fees) s.t. T_prefill (pipe interval) <= B; optimum = the
    smallest k whose balanced interval fits; the threshold staircase
    is the exhibit (EX1).
  * backfill(seating) -- the [AMENDED 2] fee-optimism magnitude:
    re-run the DP with fees at the ACTUAL seating's cut-boundary hops
    (words/bw + max_hops x 20 ns) vs the reference (1 hop); the
    quantified negligibility standard is declared in FIXLIST.
  * weave exhibit (EX2) -- the seating SA rerun under torus / ring vs
    the mesh default (die_weave knob).
  * seam exhibit (EX3) -- cuts bound to the A4 seam example (16
    layers/package) vs the DP's free k = 2.

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
B_PREFILL_S = 0.120                 # the proposed demonstration budget
SEATING_SCHED = sa.Schedule(t0=0.005, alpha=0.996, steps=1200)
SEATING_SEEDS = ("clustered", "snake", "random")
OUT_JSON = os.path.join(se.A, "search_linkage.json")
LADDER_E = {"clustered": 2.3379, "least_manhattan": 2.3382,
            "nmap_greedy": 2.3393, "snake": 2.3537, "sequential": 2.3937,
            "heaviest_first": 2.4394, "random": 2.5251}


# ------------------------------------------------- the seating-E objective
class SessionE:
    """Diff-driven incremental E: wraps ScoreSession; any requested Pi is
    diffed against the committed seat and applied via update() (the
    engine's reject-then-move-on sequence needs no explicit rollback).
    Reports the T column alongside via last_score."""

    def __init__(self, W, pi0, d2d_gbps=GRS):
        self.W = W
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
        return sc.e_J


def seating_leg(W, label, seeds=SEATING_SEEDS, sched=SEATING_SCHED):
    """The 2.7B seating instance: multi-start SA on E."""
    pis = {n: sb.generate(n, W, seed=0) for n in seeds}
    results = {}
    for i, name in enumerate(sorted(pis)):
        J = SessionE(W, pis[name])
        r = sa.anneal(J, pis[name], W.fab.level("die").per_parent, sched,
                      seed=1000003 * 0 + i)
        results[name] = r
    best = min(sorted(results), key=lambda n: results[n].best_j)
    r = results[best]
    sc = se.score(r.best_pi, W, d2d_gbps=GRS)
    return {"label": label,
            "per_start": {n: {"start_e_J": x.start_j, "best_e_J": x.best_j,
                              "accepted": x.accepted}
                          for n, x in results.items()},
            "best_start": best, "best_e_J": r.best_j,
            "best_t_single_s": sc.t_opt_s,
            "best_pi": r.best_pi.to_json()}


# ------------------------------------------------ the constrained exhibit
def constrained(B_s: float):
    """min T_decode(single) s.t. T_prefill(pipe) <= B; exact via the DP
    at every k. Returns the optimum + the full k table."""
    inst_p, meta_p = sd.standing_instance()
    Wd = se.Workload2p7B()
    layer_d = Wd.layer_serial_s("decode")
    pi = sb.generate("sequential", Wd)
    bs = Wd.boundaries(pi, "decode")
    words_d = [b for b in bs if b["inter_layer"]][0]["words"]
    fee_d = words_d / (GRS * 1e9)
    L = meta_p["L"]
    table = []
    for k in range(1, L + 1):
        v_p, plan = sd.solve(inst_p, k, "pipe")
        t_d = L * layer_d + (k - 1) * fee_d
        table.append({"k": k, "t_prefill_s": v_p, "t_decode_s": t_d,
                      "feasible": v_p <= B_s})
    feas = [row for row in table if row["feasible"]]
    opt = min(feas, key=lambda r: (r["t_decode_s"], r["k"])) if feas else None
    return {"B_s": B_s, "table": table, "opt": opt,
            "unconstrained_k": min(table, key=lambda r: r["t_decode_s"])["k"],
            "meta": {"layer_decode_s": layer_d, "fee_decode_s": fee_d,
                     "words_decode": words_d}}


def staircase(table):
    """The critical points: B thresholds where k* changes (readings on
    both sides ride in the table)."""
    steps = []
    seen = set()
    for row in sorted(table, key=lambda r: r["k"]):
        v = row["t_prefill_s"]
        if v not in seen:
            seen.add(v)
            steps.append({"threshold_B_s": v, "smallest_k": row["k"],
                          "t_decode_s": row["t_decode_s"]})
    return sorted(steps, key=lambda s: -s["threshold_B_s"])


# ------------------------------------------------- the fee backfill (due)
def backfill(pi_best, ks=(2, 4, 8, 16, 32)):
    """[AMENDED 2] magnitude: DP with fees at the ACTUAL seating's
    cut-boundary hops vs the reference 1 hop."""
    W = se.Workload2p7B()
    inst, meta = sd.standing_instance()
    bs = W.boundaries(pi_best, "prefill")
    inter = [b for b in bs if b["inter_layer"]]
    hop_of = {int(b["into"].rsplit("@L", 1)[1]): b["max_hops"]
              for b in inter}
    ns = se.NS_PER_HOP_D2D * 1e-9
    out = {"per_k": [], "max_hops_seen": max(hop_of.values())}
    for k in ks:
        v_ref, plan_ref = sd.solve(inst, k, "pipe")
        fees = tuple(0.0 if b == 0 else
                     meta["fee_s"] + hop_of.get(b, 1.0) * ns
                     for b in range(meta["L"]))
        inst_act = sd.Instance(taus=inst.taus, fees=fees, G=inst.G,
                               budget=inst.budget)
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
    out = {"B_prefill_s": B_PREFILL_S}

    # EX1: the constrained two-phase table + staircase
    c = constrained(B_PREFILL_S)
    out["ex1_constrained"] = c
    st = staircase(c["table"])
    out["ex1_staircase"] = st
    print(f"[EX1] B = {B_PREFILL_S*1e3:.0f} ms -> constrained k* = "
          f"{c['opt']['k']} (T_prefill {c['opt']['t_prefill_s']*1e3:.2f} ms,"
          f" T_decode {c['opt']['t_decode_s']*1e3:.3f} ms); unconstrained "
          f"decode-optimal k = {c['unconstrained_k']}")
    print("[EX1] staircase (B threshold -> smallest k, T_decode):")
    for s_ in st[:8]:
        print(f"    B >= {s_['threshold_B_s']*1e3:8.2f} ms -> k = "
              f"{s_['smallest_k']:2d}  T_decode {s_['t_decode_s']*1e3:.3f} ms")

    # the seating instance (front-matter due 2) on the mesh default
    W = se.Workload2p7B()
    leg = seating_leg(W, "mesh_default")
    out["seating_mesh"] = leg
    e = leg["best_e_J"]
    print(f"[SEATING] best E {e:.4f} J (start {leg['best_start']}) vs "
          f"clustered 2.3379 -> regret {e/LADDER_E['clustered']:.4f}; "
          f"T flat column {leg['best_t_single_s']*1e3:.3f} ms")
    out["seating_regret_vs_rungs"] = {n: e / v for n, v in LADDER_E.items()}

    # front-matter due 1: the fee backfill at the SA-found seating
    bf = backfill(ss.Pi.from_json(leg["best_pi"]))
    out["backfill"] = bf
    print(f"[BACKFILL] max cut-boundary hops seen {bf['max_hops_seen']:.0f};"
          f" cuts changed at any k: "
          f"{any(r['cuts_changed'] for r in bf['per_k'])}; max bottleneck "
          f"shift {max(r['shift_rel'] for r in bf['per_k']):.3e} -> "
          f"negligible = {bf['negligible']}")

    # EX2: weave enumeration
    for topo, params in (("torus", {}), ("ring", {})):
        Ww = se.Workload2p7B(die_weave=(topo, params))
        legw = seating_leg(Ww, f"weave_{topo}")
        out[f"seating_{topo}"] = legw
        spread = (max(x["start_e_J"] for x in legw["per_start"].values())
                  / min(x["best_e_J"] for x in legw["per_start"].values()))
        print(f"[EX2 {topo}] best E {legw['best_e_J']:.4f} J "
              f"(start {legw['best_start']}); start-spread/best "
              f"{spread:.4f}")

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
    v_seam = max((hi - lo) * meta["layer_s"]
                 + (0.0 if lo == 0 else meta["fee_s"]) for lo, hi in seg)
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
