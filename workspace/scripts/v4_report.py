"""Report over the next-round deployment units (analysis/v4/e7_*): one table
per unit with the model, the structure, the denominators and the gain
statistics of every record, including the records that did not run (model
length limit, attention-die capacity, missing account).

    python3 scripts/v4_report.py   -> analysis/v4/REPORT.md, analysis/v4/all_e7.csv
"""
import csv
import glob
import json
import os
import statistics

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(WS, "analysis", "v4")
UNITS = ("e7_ref", "e7_struct", "e7_len", "e7_lencap", "e7_geom", "e7_tiling") + tuple(f"e8_cap_m{n}" for n in (2, 4, 6, 8, 12, 16, 24, 32)) + tuple(f"e8_common_m{n}" for n in (8, 16, 24, 32))
TITLES = {"e7_ref": "Reference workpoint (prefill 512, kappa 2, XY, 0.4 GB/s), near-square and 2:1 grids",
          "e7_struct": "Port ratio x routing on the near-square grid (prefill 512)",
          "e7_len": "Lengths and phases on the near-square grid (kappa 2, XY, 0.4 GB/s)",
          "e7_lencap": "Lengths above the standard attention die, with the attention die ASSUMED larger (declared in the account; static operators on the standard die)",
          "e7_geom": "Geometry (2:1, 4:1) x routing x port ratio (prefill 512)",
          "e7_tiling": "Tiling variants with their own mapper accounts (row: row-split preference on every operator; mixed: ffn2 row-split; mixed2: ffn2 and out_proj row-split); colrow is e7_ref"}
for _n in (8, 16, 24, 32):
    TITLES[f"e8_common_m{_n}"] = f"Common-grid control: the {_n}-macro die's configuration on the other capacity's die grid (same network, routing, link bandwidth and port ratio; only the occupancy differs)"
for _n in (2, 4, 6, 8, 12, 16, 24, 32):
    TITLES[f"e8_cap_m{_n}"] = f"Capacity axis: {_n} macros per die ({_n / 8:g} x the base capacity), prefill 512, kappa 2, XY, near-square and 2:1 grids; every operator re-measured and re-tiled on this die"


def row_of(r, unit):
    s = r["spec"]
    base = {"unit": unit, "config_id": r["config_id"], "model": s["model"], "status": r["status"], "phase": s["phase"], "S": s["S"],
            "kappa": s["kappa"], "routing": s["routing"], "grid": "x".join(map(str, r["grid"])) if r.get("grid") else "", "reason": r.get("reason", ""),
            "die_macros": s.get("die_macros", 8), "account_suffix": s.get("account_suffix", ""), "chain": "; ".join(f"{n} {k}{(' ' + sp) if sp else ''}" for n, k, sp in r.get("chain", []))}
    if r["status"] != "done":
        return base
    m, b, sr, t = r["metrics"], r["band"], r["search"], r["timing"]
    pt = [p for p in r["cost_grid"] if p["rate"] == 1 and abs(p["bw"] - s["bw"]) < 1e-9]
    # energy: communication share, the minimum-energy point of the library + endpoints, non-dominance of the headline
    c0, h = r["candidates"][r["strongest"]], r["search"]["runs"][r["search"]["headline"]]
    pts = [(x["T_s"], x["E_J"], n) for n, x in r["candidates"].items()] + [(x["T_s"], x["E_J"], n) for n, x in r["search"]["runs"].items()]
    nd = [q for q in pts if not any((o[0] <= q[0] and o[1] <= q[1] and (o[0] < q[0] or o[1] < q[1])) for o in pts)]
    minE = min(pts, key=lambda q: q[1])
    energy = {"E_comm_share_strongest": c0["E_comm_J"] / c0["E_J"] * 100, "E_comm_share_headline": h["E_comm_J"] / h["E_J"] * 100,
              "headline_nondominated": any(q[2] == r["search"]["headline"] for q in nd), "n_nondominated": len(nd),
              "minE_point": minE[2], "minE_gain": (1 - minE[0] / r["T_base_s"]) * 100, "minE_dE": (minE[1] / c0["E_J"] - 1) * 100}
    base.update({"n_dies": r["n_dies"], "empty_slots": r["empty_slots"], "account": r["account_status"], "strongest": r["strongest"], "strongest_rule": r["strongest_rule"],
                 "T_base_ms": r["T_base_s"] * 1e3, "headline_T_ms": sr["headline_T_s"] * 1e3, "G_median": sr["gain_median_pct"], "G_min": sr["gain_min_pct"], "G_max": sr["gain_max_pct"],
                 "eta": m["eta_comm"] * 100, "r0": m["r0"] * 100, "g_bw": (m["g_bw_eq"] or 0) * 100, "B_eq": m["B_eq_gbps"], "G_vs_default": m["gain_vs_default_pct"], "G_vs_rule": m["gain_vs_strongest_rule_pct"],
                 "dE": m["dE_pct"], "B_minus": b["rules"]["B_minus"], "B_plus": b["rules"]["B_plus"], "band_ratio": b["rules"]["ratio"], "region": pt[0]["region"] if pt else "",
                 "strongest_invariant": r["ordering_invariant_over_grid"], "steps": sr["steps"], "full_score_ms": t["full_score_ms"], "wall_s": t["config_wall_s"],
                 "tiling_id": r.get("provenance", {}).get("tiling_id", ""), "protocol_id": r.get("provenance", {}).get("protocol_id", ""), **energy})
    return base


def main():
    rows = []
    md = ["# Next-round deployments of the real models (units e7_*; records in each unit's configs.jsonl, summary.csv, runs.csv, candidates.csv, cost_grid.csv)\n",
          "Protocol: 100 random fills (all saved), starts = strongest named rule / strongest random / random seed 0, SA seeds 0-4, budget max(1200, ceil(1200 n / 544)), objective T/T_base with t0 = 0.0094396 (the V3 protocol). "
          "Gains are against the strongest candidate of the configuration's own library (rules + pool). Accounts: one mapper run per operator per (model, S, phase) in `v4/accounts/`.\n"]
    for u in UNITS:
        p = os.path.join(V4, u, "configs.jsonl")
        if not os.path.exists(p):
            continue
        recs = [json.loads(l) for l in open(p)]
        rs = [row_of(r, u) for r in recs]
        rows += rs
        md.append(f"## {u}: {TITLES[u]}\n")
        md.append("| model | phase S | kappa | routing | dies / grid | chain (dies per operator) | strongest (rule) | T_base (ms) | G median [min, max] | eta | r0 | g_BW (B_eq) | vs default | vs rule | dE | band of rules (ratio) | region at 0.4 GB/s | wall (s) | status |")
        md.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for x in rs:
            if x["status"] != "done":
                md.append(f"| {x['model']} | {x['phase']} {x['S']} | {x['kappa']:g} | {x['routing']} | | | | | | | | | | | | | | | {x['status']}: {x['reason']} |")
                continue
            md.append(f"| {x['model']} | {x['phase']} {x['S']} | {x['kappa']:g} | {x['routing']} | {x['n_dies']} / {x['grid']} | {x['chain']} | {x['strongest']} ({x['strongest_rule']}) | {x['T_base_ms']:.1f} | "
                      f"{x['G_median']:.2f} [{x['G_min']:.2f}, {x['G_max']:.2f}] | {x['eta']:.1f} | {x['r0']:.1f} | {x['g_bw']:.1f}% ({x['B_eq']:.3f}) | {x['G_vs_default']:.1f} | {x['G_vs_rule']:.1f} | {x['dE']:+.2f} | "
                      f"{x['B_minus']:.2f}-{x['B_plus']:.2f} ({x['band_ratio']:.2f}) | {x['region']} | {x['wall_s']:.0f} | done |")
        md.append("")
        done = [x for x in rs if x["status"] == "done"]
        if done:
            md.append("Energy (dynamic, 10 pJ per word-hop surplus): | model | phase S | kappa | routing | grid | dE headline | comm share of E (strongest / headline) | headline non-dominated (T, E) | min-E point: gain, dE |")
            md.append("|---|---|---|---|---|---|---|---|---|")
            for x in done:
                md.append(f"| {x['model']} | {x['phase']} {x['S']} | {x['kappa']:g} | {x['routing']} | {x['grid']} | {x['dE']:+.2f}% | {x['E_comm_share_strongest']:.1f} / {x['E_comm_share_headline']:.1f}% | {x['headline_nondominated']} | {x['minE_point']}: {x['minE_gain']:.2f}%, {x['minE_dE']:+.2f}% |")
            md.append("")
            md.append(f"{len(done)} done of {len(rs)}; G median over the done records {statistics.median(x['G_median'] for x in done):.2f}%, r0 {min(x['r0'] for x in done):.1f} to {max(x['r0'] for x in done):.1f}%.\n")
    rf = sorted(glob.glob(os.path.join(V4, "e7_reuse", "*.csv")))
    if rf:
        md.append("## e7_reuse: the prefill-512 layout re-scored at every workpoint (500-fill pools; cold search = three V3 starts x 5 seeds; warm = the frozen layout as the start, incumbent kept)\n")
        md.append("| model | phase | S | strongest | T_base (ms) | comm share | reuse gain (eta) | cold search [min, max] | warm search [min, max] | status |")
        md.append("|---|---|---|---|---|---|---|---|---|---|")
        for f_ in rf:
            for x in csv.DictReader(open(f_)):
                m_ = os.path.basename(f_)[:-4]
                if x["status"] != "done":
                    md.append(f"| {m_} | {x['phase']} | {x['S']} | | | | | | | {x['status']} {x['reason']} |"); continue
                md.append(f"| {m_} | {x['phase']} | {x['S']} | {x['strongest']} | {float(x['T_base_ms']):.1f} | {float(x['comm_share_ref_pct']):.1f}% | {float(x['reuse_gain_pct']):.2f}% ({float(x['reuse_eta_pct']):.1f}%) | "
                          f"{float(x['cold_gain_pct']):.2f}% [{float(x['cold_min']):.2f}, {float(x['cold_max']):.2f}] | {float(x['warm_gain_pct']):.2f}% [{float(x['warm_min']):.2f}, {float(x['warm_max']):.2f}] | done |")
        md.append("")
    with open(os.path.join(V4, "all_e7.csv"), "w", newline="") as f:
        keys = []
        for x in rows:
            for k in x:
                if k not in keys:
                    keys.append(k)
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    open(os.path.join(V4, "REPORT.md"), "w").write("\n".join(md) + "\n")
    print("->", os.path.join(V4, "REPORT.md"), len(rows), "records")


if __name__ == "__main__":
    main()
