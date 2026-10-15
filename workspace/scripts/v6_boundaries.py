"""Follow-up P0 (section 5.2): finite / no-finite boundary status of every
rule and candidate of the offloaded records (those with an independent
interface plateau), from the stored per-hand-off components.

For a candidate p: H(B) = P + sum_j max(A_j / B, U_j), A_j = max(link_j, dport_j / kappa) in words,
U_j = hub_j / C_hub in seconds (fixed), lim H = P + sum_j U_j. Boundary
B_c = inf{B > 0 : H(B) <= R}. Statuses: finite; no finite boundary
(lim H > R); limit equals R (lim H within tolerance of R: reachable only
as B -> inf); beyond scan limit (B_c > 1e6 GB/s).

    python3 scripts/v6_boundaries.py  -> analysis/v6/boundary_candidates.csv, boundary_status_summary.md
"""
import csv
import glob
import json
import math
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(WS, "analysis", "v4"); V6 = os.path.join(WS, "analysis", "v6")
TOL = 1e-9; BMAX = 1e6


def status_of(row, R, C):
    comp = row["comp"]; P = row["prop_s"]
    U = sum(h / C for _, _, h in comp)
    lim = P + U
    A = sum(max(l, dp) for l, dp, _ in comp)
    def H(B):
        return P + sum(max(max(l, dp) / (B * 1e9), h / C) for l, dp, h in comp)
    if lim > R * (1 + TOL):
        return "no finite boundary", None, lim, U, A
    if abs(lim - R) <= R * TOL:
        return "limit equals R", None, lim, U, A
    lo, hi = 1e-6, BMAX
    if H(hi) > R:
        return "beyond scan limit", None, lim, U, A
    for _ in range(100):
        mid = math.sqrt(lo * hi)
        if H(mid) > R:
            lo = mid
        else:
            hi = mid
    return "finite", hi, lim, U, A


def main():
    os.makedirs(V6, exist_ok=True)
    rows, summ = [], []
    for p in sorted(glob.glob(os.path.join(V4, "e9_*", "configs.jsonl"))) + sorted(glob.glob(os.path.join(V4, "e10_*", "configs.jsonl"))):
        unit = os.path.basename(os.path.dirname(p))
        for line in open(p):
            r = json.loads(line)
            if r["status"] != "done" or (r.get("attention") or {}).get("mode") != "unit":
                continue
            C = r["attention"]["unit"]["link_bandwidth_gbps"] * 1e9
            R = r["N_s"] + r["F_s"]
            rules = [n for n in r["candidates"] if not n.startswith("random_s")]
            stat = {}
            for n, row in r["candidates"].items():
                if "comp" not in row:
                    continue
                s, Bc, lim, U, A = status_of(row, R, C)
                stat[n] = (s, Bc)
                if n in rules or n == r["strongest"]:
                    rows.append({"unit": unit, "config_id": r["config_id"], "candidate": n, "is_rule": n in rules, "is_strongest": n == r["strongest"], "R_s": R, "P_s": row["prop_s"],
                                 "sum_interface_floor_U_s": U, "sum_A_words": A, "H_limit_s": lim, "H_at_bw_s": row["H_s"] + row["prop_s"], "bw_mesh_gbps": r["bw_gbps"], "C_hub_gbps": C / 1e9,
                                 "status": s, "B_c_gbps": Bc if Bc is not None else "", "tolerance": TOL, "scan_limit_gbps": BMAX})
            fin = [Bc for n, (s, Bc) in stat.items() if n in rules and s == "finite"]
            summ.append({"unit": unit, "config_id": r["config_id"], "n_rules": len(rules), "rules_finite": len(fin), "rules_no_finite": sum(1 for n in rules if stat.get(n, ("",))[0] == "no finite boundary"),
                         "rules_limit_equals_R": sum(1 for n in rules if stat.get(n, ("",))[0] == "limit equals R"), "rules_beyond_scan": sum(1 for n in rules if stat.get(n, ("",))[0] == "beyond scan limit"),
                         "rules_B_minus": min(fin) if fin else "", "rules_B_plus": max(fin) if fin else "", "rules_B_plus_inf": any(stat.get(n, ("",))[0] != "finite" for n in rules),
                         "pool_finite": sum(1 for n, (s, _) in stat.items() if s == "finite"), "pool_no_finite": sum(1 for n, (s, _) in stat.items() if s != "finite"),
                         "strongest_status": stat.get(r["strongest"], ("",))[0]})
    with open(os.path.join(V6, "boundary_candidates.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    md = ["# Boundary status (follow-up 5.2): offloaded records, from the stored per-hand-off components\n",
          "B_c = inf{B > 0 : H(B) <= R} with H(B) = P + sum_j max(A_j / B, U_j), the interface floor U_j = hub_j / C_hub fixed; status per rule and per candidate; a rules band with a non-finite member is reported with B_plus = inf.\n",
          "| unit | config | rules finite / no finite / limit = R / beyond scan | rules B- | rules B+ | pool finite / not | strongest |", "|---|---|---|---|---|---|---|"]
    for s in summ:
        if s["rules_no_finite"] or s["rules_limit_equals_R"] or s["rules_beyond_scan"] or s["pool_no_finite"]:
            bm = "" if s["rules_B_minus"] == "" else "%.3f" % s["rules_B_minus"]
            bp = "inf" if s["rules_B_plus_inf"] else ("" if s["rules_B_plus"] == "" else "%.3f" % s["rules_B_plus"])
            md.append(f"| {s['unit']} | {s['config_id']} | {s['rules_finite']} / {s['rules_no_finite']} / {s['rules_limit_equals_R']} / {s['rules_beyond_scan']} | {bm} | {bp} | {s['pool_finite']} / {s['pool_no_finite']} | {s['strongest_status']} |")
    md.append(f"\nRecords examined: {len(summ)}; with at least one non-finite rule: {sum(1 for s in summ if s['rules_no_finite'] or s['rules_limit_equals_R'] or s['rules_beyond_scan'])}; with a non-finite pool member: {sum(1 for s in summ if s['pool_no_finite'])}. The full per-candidate table (rules and the strongest fill of every record) is `boundary_candidates.csv`.")
    with open(os.path.join(V6, "boundary_status.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys())); w.writeheader(); w.writerows(summ)
    open(os.path.join(V6, "boundary_status_summary.md"), "w").write("\n".join(md) + "\n")
    print("->", V6, len(summ), "records,", len(rows), "candidate rows")


if __name__ == "__main__":
    main()
