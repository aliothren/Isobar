"""S8-U6: the intra-die (beta) cost integrated into a whole-model layer
objective on the A3 d = 1024 instance. See FIXLIST S8-U6.

    python3 scripts/intra_die_integration.py -> analysis/intra_die_integration.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import analyze_d2d as d2d
from scripts import analyze_soft_lever as asl
from scripts import anchors as an
from scripts import fabric
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_withindie as sw

OUT = os.path.join(se.A, "intra_die_integration.json")
PHASE = "prefill"
NS_PER_HOP = se.NS_PER_HOP_D2D


def lw_dmodel():
    from scripts import llm_workload as lw
    return lw.GptConfig().d_model


def op_time(rec, ser_s):
    prop = rec["latency_s"] - rec["write_s"] - max(rec["compute_s"], rec["serial_s"])
    assert prop >= -1e-15, (rec["name"], prop)          # no double count
    return rec["write_s"] + prop + max(rec["compute_s"], ser_s), max(0.0, ser_s - rec["compute_s"])


def main():
    src = json.load(open(asl.SRC))
    recs = {r["name"]: r for r in src["phases"][PHASE]["per_op"][asl.PROD]}
    n_layers = src["n_layers"]
    stored = json.load(open(os.path.join(se.A, "search_withindie.json"))) \
        if os.path.exists(os.path.join(se.A, "search_withindie.json")) else {}
    moved = {n for die in sw.DIES for n, _ in sw.DIES[die]}
    out = {"note": __doc__.strip(), "instance": "A3 co-residency, 355M-class d=1024, "
           "attention offloaded, 2x4 macro mesh glb centre", "n_layers": n_layers,
           "anchors_gbps": asl.ANCHOR_GBPS, "per_anchor": {}}
    Js = {die: sw.WithinDieJ(die, PHASE, sw.G_ACTIVE) for die in sw.DIES}
    ex = {die: Js[die].exhaustive() for die in sw.DIES}
    print(f"{'g GB/s':>7} {'T_ship ms':>10} {'T_best ms':>10} {'beta gain':>9} {'worst/best':>10} "
          f"{'exposed@ship':>12} {'exposed@best':>12} {'intra share':>11}")
    for g in asl.ANCHOR_GBPS:
        scale = asl.REF_WC / an.words_per_cycle(g)
        fixed, fixed_exposed = 0.0, 0.0
        for name, rec in recs.items():
            if name in moved:
                continue
            t, e = op_time(rec, rec["serial_s"] * scale if rec["serial_s"] else 0.0)
            fixed += t
            fixed_exposed += e
        die_rows = {}
        for die in sw.DIES:
            J = Js[die]
            def cost(seat):
                tot, exp_ = 0.0, 0.0
                for name, _k in J.ops:
                    t, e = op_time(J.recs[name], J.a3_ser(name, seat[name]) * scale)
                    tot += t
                    exp_ += e
                return tot, exp_
            costs = [(cost(seat), seat) for _c, _m, seat in ex[die]]
            best = min(costs, key=lambda x: x[0][0])
            worst = max(costs, key=lambda x: x[0][0])
            ship = cost(sw.SHIPPED[die])
            die_rows[die] = {"shipped_s": ship[0], "shipped_exposed_s": ship[1],
                             "best_s": best[0][0], "best_exposed_s": best[0][1],
                             "best_seat": {k: list(v) for k, v in best[1].items()},
                             "worst_s": worst[0][0], "n_seatings": len(costs)}
        T_ship = fixed + sum(r["shipped_s"] for r in die_rows.values())
        T_best = fixed + sum(r["best_s"] for r in die_rows.values())
        T_worst = fixed + sum(r["worst_s"] for r in die_rows.values())
        exp_ship = fixed_exposed + sum(r["shipped_exposed_s"] for r in die_rows.values())
        exp_best = fixed_exposed + sum(r["best_exposed_s"] for r in die_rows.values())
        intra_share = sum(r["shipped_s"] for r in die_rows.values()) / T_ship
        V_words = src["S"] * lw_dmodel()          # S9 task E: the chain's own two
        pkg_s = 2 * V_words / 0.4e9                # one-flow package hand-offs per layer
        row = {"scale": scale, "fixed_rest_s": fixed, "dies": die_rows,
               "package_handoffs_per_layer_s_at_0.4": pkg_s,
               "T_layer_shipped_incl_pkg_s": T_ship + pkg_s,
               "T_layer_best_incl_pkg_s": T_best + pkg_s,
               "beta_gain_incl_pkg_pct": (1 - (T_best + pkg_s) / (T_ship + pkg_s)) * 100,
               "package_share_of_layer_shipped": pkg_s / (T_ship + pkg_s),
               "T_layer_shipped_s": T_ship, "T_layer_best_s": T_best, "T_layer_worst_s": T_worst,
               "beta_gain_pct": (1 - T_best / T_ship) * 100,
               "band_worst_over_best": T_worst / T_best,
               "exposed_share_shipped": exp_ship / T_ship, "exposed_share_best": exp_best / T_best,
               "moved_dies_share_of_layer": intra_share,
               "T_stack_shipped_s": T_ship * n_layers}
        out["per_anchor"][str(g)] = row
        print(f"      incl. package hand-offs at 0.4 GB/s ({pkg_s*1e3:.2f} ms/layer, "
              f"{row['package_share_of_layer_shipped']*100:.1f}% of layer): beta gain "
              f"{row['beta_gain_incl_pkg_pct']:.2f}%")
        print(f"{g:7g} {T_ship*1e3:10.3f} {T_best*1e3:10.3f} {row['beta_gain_pct']:8.2f}% "
              f"{row['band_worst_over_best']:10.4f} {row['exposed_share_shipped']*100:11.2f}% "
              f"{row['exposed_share_best']*100:11.2f}% {intra_share*100:10.1f}%")
    # identity anchor: the band must reproduce the stored a3_stack_ratio rows
    chk = sw.fold_anchor_check()[PHASE]
    out["identity_anchor"] = [{"g": r["g_gbps"], "stored_stack_ratio": r["a3_stack_ratio"],
                               "recomputed": out["per_anchor"][str(r["g_gbps"])]["band_worst_over_best"]}
                              for r in chk]
    ok = all(abs(x["stored_stack_ratio"] - x["recomputed"]) < 1e-9 for x in out["identity_anchor"])
    print("identity anchor (band == stored a3_stack_ratio at every g):", ok)
    # alpha on this instance: the one-flow hand-off degeneration -> only propagation moves
    W = se.Workload355M(fabric.from_yaml(d2d.MULTI), 256.0)
    hops = {}
    for rule in ("sequential", "snake", "random", "clustered"):
        pi = sb.generate(rule, W, seed=0)
        a = W.assignment_of(pi)
        icl = __import__("scripts.interconnect", fromlist=["build"]).build(W.fab, "die", W.pl)
        hops[rule] = sum(icl.hops(a[u], a[u + 1]) for u in range(W.n_units - 1))
    hmax, hmin = max(hops.values()), min(hops.values())
    T_stack = out["per_anchor"]["0.4"]["T_stack_shipped_s"]
    out["alpha_on_this_instance"] = {
        "hand_off": "one die -> one die per unit; a one-flow hand-off's busiest resource is "
                    "its own volume for every seating (pinned degeneration): alpha moves only "
                    "propagation and energy",
        "total_hops_by_rule": hops,
        "alpha_latency_lever_bound_pct": (hmax - hmin) * NS_PER_HOP * 1e-9 / T_stack * 100,
        "T_stack_shipped_at_0.4_s": T_stack}
    print(f"alpha on this instance: total hops by rule {hops}; propagation lever bound "
          f"{out['alpha_on_this_instance']['alpha_latency_lever_bound_pct']:.4f}% of the stack time")
    out["separability"] = ("T(alpha, beta) = D2D(alpha) + sum_dies C(beta_die) + fixed: no term "
                           "couples a die's macro seating to the hand-offs entering it, so the "
                           "joint gain is exactly the sum of the two levers on this model")
    out["not_covered"] = "2.7B (A4 per-op mapping): no within-die levers stored -> not integrated"
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
