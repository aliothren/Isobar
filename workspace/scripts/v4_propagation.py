"""Next-round item 1.1: the propagation term in the package evaluation.

Post-processing of the V3 records (no new searches). Every candidate and
every search endpoint in analysis/v3/<unit>/configs.jsonl carries its
decomposition (N, F, P, A, E) at the main bandwidth, so this script

  1. checks the recorded full score against the separable formula
     T = N/rate + F + P + A/B for every candidate and endpoint (the
     evaluator's H is A/B alone; P is the propagation of each hand-off's
     longest path at 20 ns per hop and is recorded apart);
  2. reports the propagation share P/(P + A/B) at the main point and over
     the whole rate x bandwidth grid for the frozen headline layout;
  3. recomputes the communication / non-communication boundary with P,
     B_c = A/(R(s) - P), against the closed form without P, B_c = A/R(s),
     for every named rule and for the whole pool, at every planned rate;
     counts the rates with no finite boundary (R(s) <= P) and the grid
     points whose region label changes;
  4. recomputes the bandwidth the strongest baseline would need to match
     the selected layout's communication time with P,
     B0,eq = A0 / (A1/B + P1 - P0), against the no-P value B A0/A1;
  5. splits the ordering check into three statements, each along the rate
     axis (B fixed at the main value) and the bandwidth axis (rate 1):
     the full candidate ordering, the identity of the strongest baseline,
     and the sign of the headline's gain against the strongest at that
     point. The V3 field ordering_invariant_over_grid is the second one.

The cost grid is a re-scoring of frozen layouts: the headline layout is
the search endpoint at the main point, and the strongest baseline at each
grid point is re-selected from the saved candidate library (rules + pool);
no point of the grid is an independent search.

    python3 scripts/v4_propagation.py   -> analysis/v4/propagation/{per_config.csv, boundaries.csv, summary.md}
"""
import csv
import glob
import json
import math
import os
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v3_sweep as v3     # noqa: E402

V3 = v3.V3
OUT = os.path.join(WS, "analysis", "v4", "propagation")
UNITS = ("e0", "e1a", "e1t", "e1s", "e1b", "e2_depth", "e2_width", "e2_ffn", "e4", "confirm")
RATES, BWS = v3.RATES, v3.BWS


def T_of(row, N, F, rate, B):
    return N / rate + F + row["prop_s"] + row["A_words"] / (B * 1e9)


def main():
    os.makedirs(OUT, exist_ok=True)
    per, bnd = [], []
    for u in UNITS:
        p = os.path.join(V3, u, "configs.jsonl")
        if not os.path.exists(p):
            continue
        for line in open(p):
            r = json.loads(line)
            if r.get("status") != "done":
                continue
            N, F, B = r["N_s"], r["F_s"], r["bw_gbps"]
            cands, runs = r["candidates"], r["search"]["runs"]
            strongest, head = r["strongest"], r["search"]["headline"]
            c0, c1 = cands[strongest], runs[head]
            # 1. consistency
            errs = [abs(T_of(x, N, F, 1.0, B) - x["T_s"]) / x["T_s"] for x in list(cands.values()) + list(runs.values())]
            errs_H = [abs(x["A_words"] / (B * 1e9) - x["H_s"]) / x["H_s"] for x in list(cands.values()) + list(runs.values()) if x["H_s"]]
            # 2. propagation share
            share = lambda x, Bq: x["prop_s"] / (x["prop_s"] + x["A_words"] / (Bq * 1e9)) if (x["prop_s"] + x["A_words"]) else 0.0
            sh_main = [share(x, B) for x in cands.values()]
            sh_grid = {Bq: share(c1, Bq) for Bq in BWS}
            # 3. boundaries with P (rate axis), rules and pool
            rules = [n for n in cands if not n.startswith("random_s")]
            names_all = list(cands)
            R = lambda s: N / s + F
            nofinite = {"rules": 0, "pool": 0}
            maxdiff = {"rules": 0.0, "pool": 0.0}
            band0 = {}
            bandP = {}
            for s in RATES:
                Rs = R(s)
                for key, names in (("rules", rules), ("pool", names_all)):
                    b0 = [cands[n]["A_words"] / Rs / 1e9 for n in names]
                    bP = [cands[n]["A_words"] / (Rs - cands[n]["prop_s"]) / 1e9 if Rs > cands[n]["prop_s"] else None for n in names]
                    nf = sum(1 for x in bP if x is None)
                    nofinite[key] += nf
                    if nf == 0:
                        maxdiff[key] = max(maxdiff[key], max(abs(y / x - 1) for x, y in zip(b0, bP)))
                    if key == "rules":
                        band0[s] = (min(b0), max(b0))
                        bandP[s] = (min(x for x in bP if x is not None), max(x for x in bP if x is not None)) if nf < len(bP) else None
                    bnd.append({"config_id": r["config_id"], "unit": u, "set": key, "rate": s, "R_s": Rs,
                                "B_minus_noP": min(b0), "B_plus_noP": max(b0),
                                "B_minus_P": (min(x for x in bP if x is not None) if nf < len(bP) else ""),
                                "B_plus_P": (max(x for x in bP if x is not None) if nf < len(bP) else ""),
                                "n_no_finite": nf, "n": len(names),
                                "max_rel_diff": (max(abs(y / x - 1) for x, y in zip(b0, bP)) if nf == 0 else "")})
            # region labels at the grid points, rules band, with and without P
            region_changes, n_pts = 0, 0
            for s in RATES:
                for Bq in BWS:
                    n_pts += 1
                    lo0, hi0 = band0[s]
                    reg0 = "below" if Bq < lo0 else "above" if Bq > hi0 else "inside"
                    if bandP[s] is None:
                        regP = "no finite boundary"
                    else:
                        loP, hiP = bandP[s]
                        regP = "below" if Bq < loP else "above" if Bq > hiP else "inside"
                    region_changes += reg0 != regP
            # 4. equivalent bandwidth with P
            A0, A1, P0, P1 = c0["A_words"], c1["A_words"], c0["prop_s"], c1["prop_s"]
            Beq0 = B * A0 / A1 if A1 else None
            den = A1 / (B * 1e9) + P1 - P0
            BeqP = A0 / den / 1e9 if den > 0 else None
            # 5. ordering along the two axes
            def order_at(rate, Bq):
                Tb = {n: T_of(cands[n], N, F, rate, Bq) for n in cands}
                order = tuple(sorted(Tb, key=Tb.get))
                top = order[0]
                sign = T_of(c1, N, F, rate, Bq) < Tb[top]
                return order, top, sign
            o_main, t_main, s_main = order_at(1.0, B)
            ax = {}
            for axis, pts in (("rate", [(s, B) for s in RATES]), ("bw", [(1.0, Bq) for Bq in BWS])):
                oc = tc = sc = 0
                for (s, Bq) in pts:
                    o, t, sg = order_at(s, Bq)
                    oc += o != o_main
                    tc += t != t_main
                    sc += sg != s_main
                ax[axis] = (oc, tc, sc, len(pts))
            per.append({"config_id": r["config_id"], "unit": u, "phase": r["spec"]["phase"], "n_dies": r["n_dies"], "kappa": r["kappa"], "bw": B,
                        "n_candidates": len(cands), "n_endpoints": len(runs),
                        "max_rel_err_T": max(errs), "max_rel_err_H_is_A_over_B": max(errs_H) if errs_H else 0.0,
                        "P_share_main_max_pct": max(sh_main) * 100, "P_share_main_median_pct": statistics.median(sh_main) * 100,
                        "P_share_headline_main_pct": share(c1, B) * 100, "P_share_headline_B50_pct": sh_grid[50.0] * 100,
                        "P_share_headline_grid_max_pct": max(sh_grid.values()) * 100,
                        "P0_ms": P0 * 1e3, "P1_ms": P1 * 1e3, "A0_over_B_ms": A0 / (B * 1e9) * 1e3, "A1_over_B_ms": A1 / (B * 1e9) * 1e3,
                        "R_rate1_ms": R(1.0) * 1e3, "R_rate32_ms": R(32.0) * 1e3,
                        "band_rules_no_finite_rates": nofinite["rules"], "band_pool_no_finite_rates": nofinite["pool"],
                        "band_rules_max_rel_diff_pct": maxdiff["rules"] * 100, "band_pool_max_rel_diff_pct": maxdiff["pool"] * 100,
                        "region_label_changes": region_changes, "grid_points": n_pts,
                        "B_eq_noP_gbps": Beq0, "B_eq_P_gbps": BeqP if BeqP is not None else "",
                        "g_bw_noP_pct": (A0 / A1 - 1) * 100 if A1 else "", "g_bw_P_pct": (BeqP / B - 1) * 100 if BeqP is not None else "",
                        "B_eq_P_rel_diff_pct": (BeqP / Beq0 - 1) * 100 if (BeqP is not None and Beq0) else "",
                        "rate_axis_full_order_changes": ax["rate"][0], "rate_axis_strongest_changes": ax["rate"][1], "rate_axis_sign_changes": ax["rate"][2], "rate_axis_points": ax["rate"][3],
                        "bw_axis_full_order_changes": ax["bw"][0], "bw_axis_strongest_changes": ax["bw"][1], "bw_axis_sign_changes": ax["bw"][2], "bw_axis_points": ax["bw"][3],
                        "v3_ordering_invariant_field": r["ordering_invariant_over_grid"]})
    with open(os.path.join(OUT, "per_config.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per[0].keys())); w.writeheader(); w.writerows(per)
    with open(os.path.join(OUT, "boundaries.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(bnd[0].keys())); w.writeheader(); w.writerows(bnd)
    # summary
    pre = [x for x in per if x["phase"] == "prefill"]
    dec = [x for x in per if x["phase"] == "decode"]
    md = ["# Item 1.1: the propagation term (post-processing of the V3 records)\n",
          f"Records: {len(per)} done configurations over units {', '.join(UNITS)}; {sum(x['n_candidates'] for x in per)} candidates and {sum(x['n_endpoints'] for x in per)} search endpoints checked.\n",
          "## Definitions as implemented (`scripts/search_eval.py`, `_assemble`)\n",
          "- N = n_layers x per-layer device compute (rows x t_row), scales with the device rate; F = n_layers x (weight write + digital elementwise) per layer; both are per-operator account sums and do not depend on the placement (the same N_s, F_s are stored once per configuration and reused for every candidate).",
          "- A = sum over hand-offs of the busiest-resource load in words (max over links and ports with the port ratio); H = A/B exactly (`d2d_serial_s`); P = sum over hand-offs of the longest path's hops x 20 ns (`propagation_s`), independent of B and of the rate.",
          "- Full score: T = N/rate + F + P + A/B. The record's H does not include P; the figure-set formula H = sum_k L_k + P in formulation.md is the sum of the two recorded terms.\n",
          "## 1. Consistency\n",
          f"- max relative error of the separable formula against the recorded full score over every candidate and endpoint: {max(x['max_rel_err_T'] for x in per):.2e}; max relative error of H = A/B: {max(x['max_rel_err_H_is_A_over_B'] for x in per):.2e}.\n",
          "## 2. Propagation share P/(P + A/B)\n",
          f"- Main point (B = 0.4 GB/s), prefill: headline layouts {min(x['P_share_headline_main_pct'] for x in pre):.3f} to {max(x['P_share_headline_main_pct'] for x in pre):.3f}%; the largest over any candidate {max(x['P_share_main_max_pct'] for x in pre):.3f}%.",
          f"- Main point, decode: headline layouts {min(x['P_share_headline_main_pct'] for x in dec):.2f} to {max(x['P_share_headline_main_pct'] for x in dec):.2f}%; largest over any candidate {max(x['P_share_main_max_pct'] for x in dec):.2f}%.",
          f"- Over the bandwidth grid (headline layout): at 50 GB/s the share is {min(x['P_share_headline_B50_pct'] for x in pre):.1f} to {max(x['P_share_headline_B50_pct'] for x in pre):.1f}% on prefill and {min(x['P_share_headline_B50_pct'] for x in dec):.1f} to {max(x['P_share_headline_B50_pct'] for x in dec):.1f}% on decode. The small share at the main point is a statement about that point; the grid rows carry the share at every bandwidth.\n",
          "## 3. Boundary with P: B_c = A/(R(s) - P) vs A/R(s)\n",
          f"- Rates with no finite boundary (R(s) <= P for some rule): {sum(x['band_rules_no_finite_rates'] for x in per)} rule-rate pairs over all configurations (pool: {sum(x['band_pool_no_finite_rates'] for x in per)} candidate-rate pairs); configurations affected: {sum(1 for x in per if x['band_rules_no_finite_rates'])} (rules), {sum(1 for x in per if x['band_pool_no_finite_rates'])} (pool).",
          f"- Where finite, the largest relative change of a rule's threshold over the planned rates 1/16 to 32: prefill {max(x['band_rules_max_rel_diff_pct'] for x in pre):.2f}% (median over configurations {statistics.median(x['band_rules_max_rel_diff_pct'] for x in pre):.3f}%), decode {max(x['band_rules_max_rel_diff_pct'] for x in dec):.1f}%.",
          f"- Region labels at the 10 x 14 grid points, rules band with vs without P: {sum(x['region_label_changes'] for x in per)} of {sum(x['grid_points'] for x in per)} points change label; configurations with any change: {sum(1 for x in per if x['region_label_changes'])} ({', '.join(sorted({x['phase'] for x in per if x['region_label_changes']}))}).\n",
          "## 4. Equivalent bandwidth with P\n",
          f"- B0,eq = A0/(A1/B + P1 - P0): non-positive denominator on {sum(1 for x in per if x['B_eq_P_gbps'] == '')} configurations; relative difference to B A0/A1 on the others: prefill max |{max(abs(x['B_eq_P_rel_diff_pct']) for x in pre if x['B_eq_P_rel_diff_pct'] != ''):.3f}|%, decode max |{max(abs(x['B_eq_P_rel_diff_pct']) for x in dec if x['B_eq_P_rel_diff_pct'] != ''):.2f}|%.\n",
          "## 5. Ordering along the two axes (candidate library + headline, re-scored)\n",
          f"- Rate axis (B = main, 10 rates): full-order changes on {sum(1 for x in per if x['rate_axis_full_order_changes'])} configurations, strongest-identity changes on {sum(1 for x in per if x['rate_axis_strongest_changes'])}, gain-sign changes on {sum(1 for x in per if x['rate_axis_sign_changes'])}.",
          f"- Bandwidth axis (rate 1, 14 bandwidths): full-order changes on {sum(1 for x in per if x['bw_axis_full_order_changes'])} configurations, strongest-identity changes on {sum(1 for x in per if x['bw_axis_strongest_changes'])}, gain-sign changes on {sum(1 for x in per if x['bw_axis_sign_changes'])}.",
          "- The V3 field `ordering_invariant` is the strongest-identity statement over the full grid; it is renamed accordingly in the v4 tables.\n",
          "## Nature of the cost grid\n",
          "Every grid point re-scores frozen layouts: the headline is the search endpoint found at the main point, and the strongest baseline is re-selected at each point from the saved library (named rules + random pool). No grid point is an independent search; the grid therefore bounds the gain of the frozen pair, not the gain a search at that point would find.\n",
          "## Main-case candidates (confirmation unit)\n",
          "| config | P1 (ms) | A1/B (ms) | P share main | P share 50 GB/s | B_eq no P | B_eq with P | g_BW no P | g_BW with P | band max rel diff |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for x in per:
        if x["unit"] == "confirm":
            md.append(f"| {x['config_id']} | {x['P1_ms']:.3f} | {x['A1_over_B_ms']:.1f} | {x['P_share_headline_main_pct']:.3f}% | {x['P_share_headline_B50_pct']:.1f}% | {x['B_eq_noP_gbps']:.4f} | "
                      f"{x['B_eq_P_gbps']:.4f} | {x['g_bw_noP_pct']:.2f}% | {x['g_bw_P_pct']:.2f}% | {x['band_rules_max_rel_diff_pct']:.3f}% |")
    md.append("")
    md.append("## Configurations whose region label or strongest identity changes along the bandwidth axis\n")
    md.append("| config | phase | region label changes | bw-axis strongest changes | bw-axis full-order changes | P share at 50 GB/s |")
    md.append("|---|---|---|---|---|---|")
    for x in sorted(per, key=lambda x: -x["bw_axis_strongest_changes"]):
        if x["region_label_changes"] or x["bw_axis_strongest_changes"]:
            md.append(f"| {x['config_id']} | {x['phase']} | {x['region_label_changes']} | {x['bw_axis_strongest_changes']} / {x['bw_axis_points']} | {x['bw_axis_full_order_changes']} / {x['bw_axis_points']} | {x['P_share_headline_B50_pct']:.1f}% |")
    open(os.path.join(OUT, "summary.md"), "w").write("\n".join(md) + "\n")
    print("->", OUT, len(per), "configs")


if __name__ == "__main__":
    main()
