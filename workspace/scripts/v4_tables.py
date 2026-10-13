"""Next-round item 1.4 (and the existing-record part of 4.4): bookkeeping
tables over the V3 records, computed from the raw configs.jsonl files.

  - physical configurations vs records: one physical key per (d, dh, d_ff,
    L, S, phase, tiling, actual grid, topology, routing, kappa, bw), with
    the protocol of each record (pool size, seed range) as protocol_id;
    auto1/auto2 aliases are resolved to the grid the record used;
  - the gain distribution over distinct physical configurations under the
    exploration protocol (100 fills, seeds 0-4), the confirmation set apart;
  - old and new endpoints of the reference configuration re-scored under
    one evaluator against both the old denominator (random_s3, best of 5)
    and the new one (random_s146, best of 500);
  - pool-size effect on the denominator (best of 5 / 20 / 100 / 500);
  - the energy outliers with their communication-energy shares, and a
    latency / dynamic-energy non-dominance count per configuration;
  - the ring / mesh reference ratio;
  - the single-die thresholds from the tiler's chain records;
  - the coverage of the previous plan's declared grid.

    python3 scripts/v4_tables.py  -> analysis/v4/tables/{records.csv, energy.csv, thresholds.csv, old_vs_new.csv, summary.md}
"""
import csv
import json
import os
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import search_baselines as sb      # noqa: E402
from scripts import search_eval as se           # noqa: E402
from scripts import search_space as ss          # noqa: E402
from scripts import v3_discrim as d3            # noqa: E402
from scripts import v3_sweep as v3              # noqa: E402

V3 = v3.V3
A = os.path.join(WS, "analysis")
OUT = os.path.join(A, "v4", "tables")
UNITS = ("e0", "e1a", "e1t", "e1s", "e1b", "e2_depth", "e2_width", "e2_ffn", "e4", "confirm")
UNIT_MEANING = {"e0": "reference under the new protocol", "e1a": "2.7B: grid shape x routing x port ratio", "e1t": "topologies (torus, ring)",
                "e1s": "workpoints (length, phase) on the reference", "e1b": "dh 64 family: width x FFN ratio x depth", "e2_depth": "depth scaling",
                "e2_width": "width scaling", "e2_ffn": "FFN ratio scaling", "e4": "tiling variants", "confirm": "confirmation (500 fills, seeds 5-14)"}


def phys_key(r):
    s = r["spec"]
    return (s["d"], s["dh"], s["d_ff"], s["L"], s["S"], s["phase"], s["tiling"], "x".join(map(str, r["grid"])), s["topology"], s["routing"], float(s["kappa"]), float(s["bw"]))


def main():
    os.makedirs(OUT, exist_ok=True)
    recs = []
    for u in UNITS:
        p = os.path.join(V3, u, "configs.jsonl")
        if not os.path.exists(p):
            continue
        for line in open(p):
            r = json.loads(line); r["unit"] = u; recs.append(r)
    done = [r for r in recs if r["status"] == "done"]
    rows = []
    for r in recs:
        seeds = r["search"]["seeds"] if r["status"] == "done" else []
        rows.append({"config_id": r["config_id"], "unit": r["unit"], "unit_meaning": UNIT_MEANING[r["unit"]], "status": r["status"],
                     "physical_key": "|".join(map(str, phys_key(r))) if r["status"] == "done" else "", "grid": "x".join(map(str, r["grid"])) if r["status"] == "done" else "",
                     "protocol_id": (f"pool{r['n_random']}_seeds{min(seeds)}-{max(seeds)}_steps{r['search']['steps']}" if seeds else ""),
                     "n_dies": r.get("n_dies", ""), "empty_slots": r.get("empty_slots", ""), "account": r.get("account_status", ""),
                     "G_median": r["search"]["gain_median_pct"] if r["status"] == "done" else "", "G_min": r["search"]["gain_min_pct"] if r["status"] == "done" else "",
                     "G_max": r["search"]["gain_max_pct"] if r["status"] == "done" else "", "headline_run": r["search"]["headline"] if r["status"] == "done" else "",
                     "strongest": r.get("strongest", ""), "T_base_ms": r["T_base_s"] * 1e3 if r["status"] == "done" else "",
                     "eta": r["metrics"]["eta_comm"] * 100 if r["status"] == "done" else "", "r0": r["metrics"]["r0"] * 100 if r["status"] == "done" else "",
                     "dE_pct": r["metrics"]["dE_pct"] if r["status"] == "done" else "", "reason": r.get("reason", "")})
    with open(os.path.join(OUT, "records.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    # distinct physical configurations under the exploration protocol
    expl = [r for r in done if r["unit"] != "confirm"]
    by_key = {}
    for r in expl:
        by_key.setdefault(phys_key(r), []).append(r)
    dup = {k: v for k, v in by_key.items() if len(v) > 1}
    dist = [v[0]["search"]["gain_median_pct"] for v in by_key.values()]
    conf = [r for r in done if r["unit"] == "confirm"]
    conf_keys = {phys_key(r) for r in conf}
    q = lambda xs, p: sorted(xs)[int(round((len(xs) - 1) * p))]
    md = ["# Item 1.4: bookkeeping over the V3 records\n",
          "## Records vs physical configurations\n",
          f"- Records: {len(recs)} planned ({len(done)} done, {len(recs) - len(done)} infeasible) over {len(UNITS)} units. Exploration protocol (100 fills, seeds 0-4): {len(expl)} done records = {len(by_key)} distinct physical configurations; "
          f"{len(dup)} configurations appear in more than one unit ({sum(len(v) for v in dup.values())} records): " + "; ".join(f"{k[0]}/{k[2]}/{k[7]}/k{k[10]:g}/{k[4]}{k[5]} in {', '.join(x['unit'] for x in v)}" for k, v in dup.items()) + ".",
          f"- Confirmation protocol (500 fills, seeds 5-14): {len(conf)} records, {len(conf_keys)} physical configurations, all of which also exist under the exploration protocol ({sum(1 for k in conf_keys if k in by_key)} matched); the e0 record of the reference is a third protocol (500 fills, seeds 0-4).",
          "- Aliases: auto1 / auto2 in a config id mean the near-square / 2:1 grid chosen for the die count; the actual grid is the record's `grid` field and is the one used in the physical key (records.csv).\n",
          "## Gain distribution (distinct physical configurations, exploration protocol; the confirmation set is not mixed in)\n",
          f"- n = {len(dist)}; median {statistics.median(dist):.2f}%, quartiles {q(dist, .25):.2f} / {q(dist, .75):.2f}%, min {min(dist):.2f}%, max {max(dist):.2f}%; zero-gain configurations {sum(1 for x in dist if abs(x) < 1e-9)}; negative {sum(1 for x in dist if x < -1e-9)}.",
          f"- by port ratio: " + "; ".join(f"kappa {k:g}: n {len(v)}, median {statistics.median(v):.2f}%" for k, v in sorted({kk: [x[0]['search']['gain_median_pct'] for kk2, x in by_key.items() if kk2[10] == kk] for kk in {k[10] for k in by_key}}.items())) + ".",
          f"- Confirmation set: n = {len(conf)}, median {statistics.median(r['search']['gain_median_pct'] for r in conf):.2f}%, range {min(r['search']['gain_median_pct'] for r in conf):.2f} to {max(r['search']['gain_median_pct'] for r in conf):.2f}% (selected high-gain configurations plus the reference; not a sample of the sweep).\n"]
    # old vs new endpoints under one evaluator
    W = d3.make_W((24, 24), 32, kappa=2.0, phase="prefill")
    mu = {"prefill": 1.0}
    ev = lambda pi: se.score(pi, W, mu=mu, caliber="single", d2d_gbps=0.4).t_opt_s
    old_runs = json.load(open(os.path.join(A, "kappa_geometry_sweep.json")))["cells"]["24x24/k2"]["runs"]
    old_T = {n: ev(ss.Pi.from_json(r["best_pi"])) for n, r in old_runs.items()}
    r3 = ev(sb.generate("random", W, seed=3))
    conf_ref = [r for r in conf if r["spec"]["d"] == 2560 and r["spec"]["d_ff"] == 10240 and r["spec"]["S"] == 512][0]
    e0 = [r for r in done if r["unit"] == "e0"][0]
    r146 = conf_ref["candidates"]["random_s146"]["T_s"]
    main_old = json.load(open(os.path.join(A, "main_config_results.json")))["rows"]
    ovn = []
    for n, T in old_T.items():
        ovn.append({"set": "old (3 starts x 3 seeds, 1200 steps, t0 20 ms)", "run": n, "T_ms": T * 1e3, "T_recorded_ms": main_old[n]["prefill"]["0.4"]["T_s"] * 1e3 if n in main_old else "",
                    "gain_vs_random_s3_pct": (1 - T / r3) * 100, "gain_vs_random_s146_pct": (1 - T / r146) * 100})
    for tag, rec in (("new e0 (seeds 0-4, 500 fills)", e0), ("new confirm (seeds 5-14, 500 fills)", conf_ref)):
        for n, r in rec["search"]["runs"].items():
            ovn.append({"set": tag, "run": n, "T_ms": r["T_s"] * 1e3, "T_recorded_ms": r["T_s"] * 1e3,
                        "gain_vs_random_s3_pct": (1 - r["T_s"] / r3) * 100, "gain_vs_random_s146_pct": (1 - r["T_s"] / r146) * 100})
    with open(os.path.join(OUT, "old_vs_new.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ovn[0].keys())); w.writeheader(); w.writerows(ovn)
    def per_seed_median(rec):
        ps = rec["search"]["per_seed_best"]
        return statistics.median(rec["search"]["runs"][v]["T_s"] for v in ps.values())
    old_vals = sorted(old_T.values())
    old_per_seed = [min(old_T[f"sa_{st}_s{s}"] for st in ("clustered", "random", "snake")) for s in range(3)]
    md += ["## Reference configuration: old and new endpoints under one evaluator (2.7B, 24x24, kappa 2, 0.4 GB/s)\n",
           f"- Denominators: random_s3 (best of 5) {r3*1e3:.2f} ms; random_s8 (best of 100) {e0['random_best_of']['100']*1e3:.2f} ms; random_s146 (best of 500) {r146*1e3:.2f} ms. Best-of-5 to best-of-500: {(1 - r146 / r3)*100:.2f}%; best-of-100 to best-of-500: {(1 - r146 / e0['random_best_of']['100'])*100:.2f}%; best-of-20: {e0['random_best_of']['20']*1e3:.2f} ms.",
           f"- Old endpoints (9 runs, `kappa_geometry_sweep.json` 24x24/k2, re-scored today): {old_vals[0]*1e3:.1f} to {old_vals[-1]*1e3:.1f} ms; per-seed best {', '.join(f'{x*1e3:.1f}' for x in old_per_seed)} ms, median {statistics.median(old_per_seed)*1e3:.1f} ms "
           f"= {(1 - statistics.median(old_per_seed) / r3)*100:.2f}% vs random_s3 (the draft's 9.91%) and {(1 - statistics.median(old_per_seed) / r146)*100:.2f}% vs random_s146. Re-scoring reproduces the recorded old values to {max(abs(old_T[n] / main_old[n]['prefill']['0.4']['T_s'] - 1) for n in old_T if n in main_old):.1e}.",
           f"- New endpoints, e0 (15 runs, seeds 0-4): per-seed median {per_seed_median(e0)*1e3:.1f} ms = {(1 - per_seed_median(e0) / r146)*100:.2f}% vs random_s146, {(1 - per_seed_median(e0) / r3)*100:.2f}% vs random_s3; confirm (30 runs, seeds 5-14): per-seed median {per_seed_median(conf_ref)*1e3:.1f} ms = {(1 - per_seed_median(conf_ref) / r146)*100:.2f}% vs random_s146, {(1 - per_seed_median(conf_ref) / r3)*100:.2f}% vs random_s3.",
           f"- Every endpoint (old and new) with both gains is in `old_vs_new.csv`. The headline layout of the confirmation ({conf_ref['search']['headline']}, {conf_ref['search']['headline_T_s']*1e3:.1f} ms) is one actual layout (the median seed's best run); the 10-seed median of the per-seed bests is {per_seed_median(conf_ref)*1e3:.1f} ms (even count: the mean of the two middle values).\n"]
    # energy
    en = []
    for r in done:
        c0 = r["candidates"][r["strongest"]]; h = r["search"]["runs"][r["search"]["headline"]]
        pts = [(x["T_s"], x["E_J"], n) for n, x in r["candidates"].items()] + [(x["T_s"], x["E_J"], n) for n, x in r["search"]["runs"].items()]
        nd = [p for p in pts if not any((q[0] <= p[0] and q[1] <= p[1] and (q[0] < p[0] or q[1] < p[1])) for q in pts)]
        head_nd = any(p[2] == r["search"]["headline"] for p in nd)
        minE = min(pts, key=lambda p: p[1]); minT = min(pts, key=lambda p: p[0])
        en.append({"config_id": r["config_id"], "unit": r["unit"], "grid": "x".join(map(str, r["grid"])), "kappa": r["kappa"], "G_median_pct": r["search"]["gain_median_pct"],
                   "dE_pct": r["metrics"]["dE_pct"], "dE_comm_pct": r["metrics"]["dE_comm_pct"], "E_comm_share_strongest_pct": c0["E_comm_J"] / c0["E_J"] * 100,
                   "E_comm_share_headline_pct": h["E_comm_J"] / h["E_J"] * 100, "words_strongest": c0["words"], "words_headline": h["words"],
                   "A_strongest": c0["A_words"], "A_headline": h["A_words"], "n_points": len(pts), "n_nondominated": len(nd), "headline_nondominated": head_nd,
                   "minE_point": minE[2], "minE_gain_pct": (1 - minE[0] / c0["T_s"]) * 100, "minE_dE_pct": (minE[1] / c0["E_J"] - 1) * 100,
                   "minT_point": minT[2], "minT_dE_pct": (minT[1] / c0["E_J"] - 1) * 100})
    with open(os.path.join(OUT, "energy.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(en[0].keys())); w.writeheader(); w.writerows(en)
    en_s = sorted(en, key=lambda x: -x["dE_pct"])
    md += ["## Dynamic energy over the records (`energy.csv`)\n",
           f"- dE of the headline vs the strongest baseline: median {statistics.median(x['dE_pct'] for x in en):+.2f}%, quartiles {q([x['dE_pct'] for x in en], .25):+.2f} / {q([x['dE_pct'] for x in en], .75):+.2f}%, min {min(x['dE_pct'] for x in en):+.2f}%, max {max(x['dE_pct'] for x in en):+.2f}%; configurations above +5%: {sum(1 for x in en if x['dE_pct'] > 5)}, above +1%: {sum(1 for x in en if x['dE_pct'] > 1)}.",
           "- The energy model charges 10 pJ per delivered word per link hop (surplus over the flat delivery), so dE follows the change in word-hops; the latency objective charges the busiest resource and is indifferent to hops. The communication share of the dynamic energy is the quantity that converts a word-hop change into a system change.",
           f"- Confirmation set: dE {min(x['dE_pct'] for x in en if x['unit'] == 'confirm'):+.2f} to {max(x['dE_pct'] for x in en if x['unit'] == 'confirm'):+.2f}% (communication share of the dynamic energy {min(x['E_comm_share_strongest_pct'] for x in en if x['unit'] == 'confirm'):.1f} to {max(x['E_comm_share_strongest_pct'] for x in en if x['unit'] == 'confirm'):.1f}%); the near-neutral statement is for these configurations.",
           "- Latency / energy non-dominance over each configuration's candidates and endpoints: the headline is non-dominated on " + f"{sum(1 for x in en if x['headline_nondominated'])} of {len(en)} configurations; the minimum-energy point is a baseline fill on {sum(1 for x in en if not x['minE_point'].startswith('sa_'))} configurations, with a latency gain of {statistics.median(x['minE_gain_pct'] for x in en):.2f}% (median) against the strongest.\n",
           "| config (largest dE) | unit | grid | G | dE | dE comm | comm share of E (strongest / headline) | words strongest / headline | headline non-dominated | min-E point: gain, dE |", "|---|---|---|---|---|---|---|---|---|---|"]
    for x in en_s[:12]:
        md.append(f"| {x['config_id']} | {x['unit']} | {x['grid']} | {x['G_median_pct']:.2f}% | {x['dE_pct']:+.2f}% | {x['dE_comm_pct']:+.1f}% | {x['E_comm_share_strongest_pct']:.2f} / {x['E_comm_share_headline_pct']:.2f}% | {x['words_strongest']:.3g} / {x['words_headline']:.3g} | {x['headline_nondominated']} | {x['minE_point']}: {x['minE_gain_pct']:.2f}%, {x['minE_dE_pct']:+.2f}% |")
    md.append("")
    # ring / mesh
    ring = [r for r in done if r["spec"]["topology"] == "ring"]
    mesh24 = [r for r in done if r["unit"] == "e1a" and tuple(r["grid"]) == (24, 24) and r["spec"]["routing"] == "xy" and float(r["spec"]["kappa"]) == 2.0][0]
    md += ["## Ring vs mesh (reference model, 24x24 slots, kappa 2)\n",
           f"- Ring strongest baseline {ring[0]['T_base_s']*1e3:.1f} ms ({ring[0]['strongest']}) vs mesh XY {mesh24['T_base_s']*1e3:.1f} ms ({mesh24['strongest']}): ratio {ring[0]['T_base_s'] / mesh24['T_base_s']:.3f}; communication term H {ring[0]['candidates'][ring[0]['strongest']]['H_s']*1e3:.1f} vs {mesh24['candidates'][mesh24['strongest']]['H_s']*1e3:.1f} ms (ratio {ring[0]['candidates'][ring[0]['strongest']]['H_s'] / mesh24['candidates'][mesh24['strongest']]['H_s']:.2f}); gains {ring[0]['search']['gain_median_pct']:.2f}% vs {mesh24['search']['gain_median_pct']:.2f}%.\n"]
    # thresholds from the chain records
    th = {}
    for r in done:
        s = r["spec"]
        if s["phase"] != "prefill" or s["S"] != 512 or s["tiling"] != "colrow":
            continue
        key = (s["d"], s["dh"], round(s["d_ff"] / s["d"], 3))
        th.setdefault(key, (r["chain"], r["unit"], r["config_id"]))
    trows = []
    for (d, dh, ratio), (chain, u, cid) in sorted(th.items()):
        spanning = [(n, k) for n, k, _ in chain if k > 1]
        trows.append({"d": d, "dh": dh, "ratio": ratio, "dies_per_layer": sum(k for _, k, _ in chain), "chain": "; ".join(f"{n}:{k}{('/' + str(sp)) if sp else ''}" for n, k, sp in chain),
                      "spanning_ops": "; ".join(f"{n}:{k}" for n, k in spanning) or "none", "first_record": cid})
    with open(os.path.join(OUT, "thresholds.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trows[0].keys())); w.writeheader(); w.writerows(trows)
    one_die = sorted({(x["d"], x["ratio"]) for x in trows if x["spanning_ops"] == "none"})
    first = {}
    for x in sorted(trows, key=lambda x: x["d"]):
        if x["spanning_ops"] != "none" and x["ratio"] not in first:
            first[x["ratio"]] = x
    last_one = {r: max([x["d"] for x in trows if x["ratio"] == r and x["spanning_ops"] == "none"], default=None) for r in first}
    md += ["## Single-die thresholds from the tiler's chain records (`thresholds.csv`; prefill 512, colrow; the chain column carries each operator's die count and split)\n",
           "- Configurations where no static operator spans a die (every operator on one die): " + ", ".join(f"d {d} ratio {r:g}" for d, r in one_die) + ".",
           "- Largest single-die width and first spanning width in the records, by ratio: " + "; ".join(f"ratio {r:g}: one die up to d {last_one[r] if last_one[r] is not None else "(no single-die record)"}, spanning from d {first[r]['d']} ({first[r]['spanning_ops']})" for r in sorted(first)) + ". The records sample the widths of the sweeps (512, 640, 768, 1024, 1280, 1536, ...), so a threshold lies between the two widths named, not at them.",
           "- These are the tiler facts behind the 'no lever below the first spanning operator' statement; the V3 notes' two ranges (d <= 1024 at every ratio; d <= 768 at ratio 8) are superseded by this table: at ratio 8, d 1024 is still one die per operator in the record.\n"]
    # coverage of the previous plan
    def cnt(pred):
        xs = [r for r in recs if pred(r)]
        return f"{sum(1 for r in xs if r['status'] == 'done')} done / {len(xs)} planned"
    md += ["## Coverage of the previous plan's declared grid\n",
           "| declared axis | declared points | records | not covered |", "|---|---|---|---|",
           f"| 576-slot grid shapes x routing x kappa (2.7B) | 13 shapes x xy/yx x kappa 1, 1.5, 2, 3, 4, 8 = 156 | {cnt(lambda r: r['unit'] == 'e1a')} | o1turn routing (listed as optional) |",
           f"| topologies | torus xy/yx, ring | {cnt(lambda r: r['unit'] == 'e1t')} | cmesh / express / hier_wide / switch at die level (listed as extensions) |",
           f"| workpoints on the reference | prefill and decode at S 128 ... 4096 (7 each) | {cnt(lambda r: r['unit'] == 'e1s')} | S 2048 and 4096 infeasible for the 2.7B attention die (capacity); batch > 1 not run (needs the block_ops batch parameter) |",
           f"| depth (d 2560, ratio 4) | L 4 ... 64 x near-square / 2:1 | {cnt(lambda r: r['unit'] == 'e2_depth')} | |",
           f"| width (L 32, ratio 4) | dh 64: 8 widths, dh 80: 6, dh 128: 7, x two grids | {cnt(lambda r: r['unit'] == 'e2_width')} | |",
           f"| FFN ratio (d 2560, L 32) | ratio 2, 3, 4, 6, 8 x two grids | {cnt(lambda r: r['unit'] == 'e2_ffn')} | |",
           f"| model family (dh 64) | d 512 ... 4096 x ratio 2, 4, 8 x L 8, 32 | {cnt(lambda r: r['unit'] == 'e1b')} | ratio 3 and 6, and L other than 8 / 32, only on the reference width; dh 80 / 128 families only at ratio 4 |",
           f"| tiling variants | col, colrow, row on d 2560 / 1536 / 4096 | {cnt(lambda r: r['unit'] == 'e4')} | col and colrow coincide on every workload (the tiler never needs the second dimension); only two distinct inputs per model |",
           f"| confirmation | 500 fills, seeds 5-14 | {cnt(lambda r: r['unit'] == 'confirm')} | |",
           "| kappa x geometry on other models | (interaction axis) | not run | geometry / routing / port ratio were swept on the reference model only |",
           "| intra-die extension | other widths | not run | needs the share-constrained mapper per instance |",
           ""]
    open(os.path.join(OUT, "summary.md"), "w").write("\n".join(md) + "\n")
    print("->", OUT, len(recs), "records")


if __name__ == "__main__":
    main()
