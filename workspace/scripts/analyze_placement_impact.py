"""What share of SYSTEM energy does the placement solver's saving represent?

die_solver reports its improvement as a ratio WITHIN the on-die reduction term
(0.89 -> 0.79 uJ flat, 1.48 -> 0.79 uJ distance-weighted). That ratio says
nothing about system impact until it is divided by the energy of the matmuls it
acts on -- the same denominator discipline applied to our own 3.62x / 17.8%.

This script supplies the denominator: it runs the solver's four matmuls
(BERT-100M shapes at P=128) through the full CiMLoop pipeline, then expresses
the solver's saving as a fraction of the measured total. It also cross-checks
the solver's lambda-1 reduction term against CiMLoop's OWN router charge for the
same matmuls -- two independent accountings of inter-core partial-sum movement.

Usage (in the container): python3 analyze_placement_impact.py
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")

from scripts import die_solver as ds
from scripts import llm_workload as lw

OUT = "/home/workspace/analysis"


def main():
    base_rows, base_flat, base_dist = ds.cost(ds.baseline_place(ds.ORDER))
    opt_rows, opt_flat, opt_dist = ds.cost(ds.optimizer_place(ds.ORDER))
    base = {r.name: r for r in base_rows}
    opt = {r.name: r for r in opt_rows}

    print(f"{'matmul':16}{'M':>6}{'C':>6}{'CiMLoop total(uJ)':>19}"
          f"{'router(uJ)':>12}{'red base(uJ)':>14}{'red opt(uJ)':>13}")
    rows, tot_e, tot_router = [], 0.0, 0.0
    for name in ds.ORDER:
        M, C = ds.MATMULS[name]
        r = lw.run_op(lw.Op(name, "static", P=ds.P_TOKENS, C=C, M=M),
                      phase="prefill")
        e_uj = r["compute_J"] * 1e6
        router_uj = r["levels"].get("router", {}).get("energy_J", 0.0) * 1e6
        rb = base[name].energy_dist_pj / 1e6
        ro = opt[name].energy_dist_pj / 1e6
        rows.append({"matmul": name, "M": M, "C": C, "total_uJ": e_uj,
                     "router_uJ": router_uj, "red_base_uJ": rb, "red_opt_uJ": ro})
        tot_e += e_uj
        tot_router += router_uj
        print(f"{name:16}{M:>6}{C:>6}{e_uj:>19,.1f}{router_uj:>12,.2f}"
              f"{rb:>14.3f}{ro:>13.3f}")

    save_dist = (base_dist - opt_dist) / 1e6
    save_flat = (base_flat - opt_flat) / 1e6
    print(f"\n{'TOTAL':16}{'':6}{'':6}{tot_e:>19,.1f}{tot_router:>12,.2f}"
          f"{base_dist/1e6:>14.3f}{opt_dist/1e6:>13.3f}")

    print("\n================ THE DENOMINATOR ================")
    print(f"  system energy of the 4 matmuls        : {tot_e:,.1f} uJ")
    print(f"  solver's reduction term (baseline)    : {base_dist/1e6:.3f} uJ"
          f"  = {100*base_dist/1e6/tot_e:.3f}% of system")
    print(f"  solver's saving, distance-weighted    : {save_dist:.3f} uJ"
          f"  = {100*save_dist/tot_e:.3f}% of system   (47% of the term)")
    print(f"  solver's saving, flat router          : {save_flat:.3f} uJ"
          f"  = {100*save_flat/tot_e:.3f}% of system   (11% of the term)")
    print("\n================ CROSS-CHECK vs CiMLoop's own router ================")
    print(f"  CiMLoop router energy, same 4 matmuls : {tot_router:,.2f} uJ"
          f"  = {100*tot_router/tot_e:.2f}% of system")
    print(f"  solver term / CiMLoop router          : "
          f"{base_dist/1e6/tot_router:.3f}x")
    print("  (the solver models the inter-core partial-sum share of what CiMLoop\n"
          "   charges in aggregate; a ratio << 1 means it is a sub-part, not a\n"
          "   competing total)")

    p = os.path.join(OUT, "placement_impact.json")
    with open(p, "w") as f:
        json.dump({"per_matmul": rows, "system_total_uJ": tot_e,
                   "cimloop_router_uJ": tot_router,
                   "reduction_baseline_uJ": base_dist / 1e6,
                   "reduction_optimized_uJ": opt_dist / 1e6,
                   "saving_dist_uJ": save_dist, "saving_flat_uJ": save_flat,
                   "saving_dist_pct_of_system": 100 * save_dist / tot_e,
                   "saving_flat_pct_of_system": 100 * save_flat / tot_e}, f, indent=1)
    print(f"\nJSON -> {p}")


if __name__ == "__main__":
    main()
