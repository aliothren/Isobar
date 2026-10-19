"""Fig. 5 / Fig. 6 data (Isobar_next_tasks sections 3.5, 3.6): the Gemma
main-case additions (panel-(a) bars, the local bandwidth curve of the
frozen layout pair, the consistency checks of the existing gemma_*
exports) and the nine-cell comparison with the actual layout pair and the
seed statistics separated.

    python3 scripts/v7_fig5_fig6_results.py
      -> analysis/v7/gemma_panel_a.csv, gemma_bandwidth_curve.csv, gemma_checks.json,
         ninecell_configurations.csv, ninecell_candidates.csv, ninecell_seed_statistics.csv, ninecell_metrics.csv
"""
import csv
import json
import os
import statistics
import sys

import numpy as np

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v7_common as V                      # noqa: E402
from scripts import v6_common as C                      # noqa: E402
from scripts import v6_comparison as CMP                # noqa: E402


def Hf(row):
    return row["H_s"] + row["prop_s"]


# ------------------------------------------------------------------ Fig. 5
def gemma():
    rec = C.find_record(*V.GEMMA_REF)
    Ch = rec["attention"]["unit"]["link_bandwidth_gbps"] * 1e9; bw = float(rec["spec"]["bw"]); R = rec["N_s"] + rec["F_s"]
    lib = rec["candidates"]; runs = rec["search"]["runs"]; rep = rec["search"]["headline"]; strongest = rec["strongest"]
    Hb = Hf(lib[strongest]); Hs = Hf(runs[rep])
    # panel (a) bars
    rows = []
    bests = {}
    for n, r in runs.items():
        if r["sa_seed"] not in bests or r["T_s"] < runs[bests[r["sa_seed"]]]["T_s"]:
            bests[r["sa_seed"]] = n
    seedH = sorted(Hf(runs[n]) for n in bests.values())
    for name, role in [("sequential", "default fill")] + [(n, "named rule") for n in lib if not n.startswith("random_s") and n != "sequential"] + [(rec["strongest_random"], "strongest random of the pool"), (strongest, "best baseline (strongest of rules + pool)"), (rep, "search representative (median seed's best run)")]:
        row = lib.get(name) or runs[name]
        rows.append({"layout": name, "role": role, "H_full_s": Hf(row), "H_over_H_best_baseline": Hf(row) / Hb, "H_default_over_H": Hf(lib["sequential"]) / Hf(row), "T_s": row["T_s"], "R_s": R, "P_s": row["prop_s"], "E_J": row["E_J"],
                     "seed_H_min_s": seedH[0] if role.startswith("search") else "", "seed_H_median_s": statistics.median(seedH) if role.startswith("search") else "", "seed_H_max_s": seedH[-1] if role.startswith("search") else "",
                     "seed_H_over_H_best_min": seedH[0] / Hb if role.startswith("search") else "", "seed_H_over_H_best_max": seedH[-1] / Hb if role.startswith("search") else "", "n_seeds": len(seedH) if role.startswith("search") else "",
                     "is_strongest_named_rule": name == rec["strongest_rule"], "config_id": rec["config_id"], "protocol_id": V.protocol_id(rec)})
    # bandwidth curve: the frozen pair over 0.3-0.65 GB/s, dense near the root
    Beq = V.solve_B(lib[strongest], Hs, Ch)
    Bs = sorted(set([round(x, 6) for x in np.arange(0.30, 0.6501, 0.005)] + [round(x, 6) for x in np.arange(Beq - 0.01, Beq + 0.0101, 0.001)] + [0.4, Beq]))
    curve = []
    for B in Bs:
        hb, hs = V.H_of(lib[strongest], B, Ch), V.H_of(runs[rep], B, Ch)
        bind = V.H_binding(lib[strongest], B, Ch)
        curve.append({"B_mesh_gbps": B, "H_baseline_s": hb, "H_search_s": hs, "T_baseline_s": R + hb, "T_search_s": R + hs, "H_search_at_B_ref_s": Hs, "baseline_reaches_target": hb <= Hs, "is_B_ref": abs(B - 0.4) < 1e-9, "is_B_eq": abs(B - Beq) < 1e-9,
                      "baseline_binding_link": bind["link"], "baseline_binding_die_port": bind["die port"], "baseline_binding_hub_port": bind["hub port"], "baseline_layout": strongest, "search_layout": rep, "C_hub_gbps": Ch / 1e9, "kappa": rec["spec"]["kappa"],
                      "held_fixed": "hub capacity, K/V and digital resources, attention algorithm, both layouts; die ports at kappa x B"})
    # checks of the existing exports
    txt = open(os.path.join(C.V6, "gemma_stage_delta.csv")).read().split("\n\n")[0].splitlines()   # the per-hand-off block (a category block follows after a blank line)
    sd = list(csv.DictReader(txt))
    dsum = sum(float(r["delta_s"]) for r in sd)
    cats = {}
    for r in sd:
        cats[r["stage"]] = cats.get(r["stage"], 0.0) + float(r["delta_s"])
    seeds = [r for r in csv.DictReader(open(os.path.join(C.V6, "gemma_seed_statistics.csv"))) if r["seed"].isdigit()]   # summary rows follow the per-run rows
    bestG = {}
    for r in seeds:
        s = int(r["seed"])
        if s not in bestG or float(r["T_s"]) < bestG[s][0]:
            bestG[s] = (float(r["T_s"]), float(r["G_backbone"]), float(r["eta_comm"]), r["run"])
    Gs = sorted(v[1] for v in bestG.values()); etas = sorted(v[2] for v in bestG.values())
    cands = list(csv.DictReader(open(os.path.join(C.V6, "gemma_candidates.csv"))))
    checks = {"pair": {"baseline": strongest, "search": rep, "H_baseline_s": Hb, "H_search_s": Hs, "eta_comm": 1 - Hs / Hb, "T_baseline_s": lib[strongest]["T_s"], "T_search_s": runs[rep]["T_s"], "G_actual_pair": 1 - runs[rep]["T_s"] / lib[strongest]["T_s"], "r0": Hb / lib[strongest]["T_s"]},
              "stage_delta_sum_s": dsum, "stage_delta_sign": "delta = H_representative - H_baseline (negative = saving)", "savings_sum_s": -dsum, "savings_sum_minus_pair_difference_s": -dsum - (Hb - Hs), "n_handoffs": len(sd), "category_shares": {k: v / dsum for k, v in cats.items()}, "category_savings_s": cats,
              "seed_statistics": {"n_seeds": len(Gs), "G_median": statistics.median(Gs), "G_min": Gs[0], "G_max": Gs[-1], "eta_median": statistics.median(etas), "eta_min": etas[0], "eta_max": etas[-1], "statistic": "per seed the best of the three starts, then median / min / max"},
              "B_eq": {"B_eq_gbps": Beq, "g_bw": Beq / bw - 1, "reachable": Beq is not None, "recorded_in_v6": [r for r in csv.DictReader(open(os.path.join(C.V6, "gemma_bandwidth_equivalence.csv")))][0]["B_eq_gbps"]},
              "gemma_candidates_rows": len(cands), "gemma_candidates_reproduce_record": all(r["reproduces_record"] == "True" for r in cands),
              "energy": {r["layout"]: r["E_total_J"] for r in csv.DictReader(open(os.path.join(C.V6, "gemma_energy_breakdown.csv"))) if r["layout"] in (strongest, rep)},
              "config_id": rec["config_id"], "protocol_id": V.protocol_id(rec), "record": V.record_path(V.GEMMA_REF[0]), "code_version": V.code_version()}
    checks["energy"]["dE_pair"] = checks["energy"][rep] and (float(checks["energy"][rep]) / float(checks["energy"][strongest]) - 1)
    return rows, curve, checks


# ------------------------------------------------------------------ Fig. 6
def ninecell():
    confs, cands, seeds, metrics = [], [], [], []
    for fam, model, units, cid in CMP.FAMILIES:
        rec = None
        for u in units:
            try:
                rec = C.find_record(u, cid); unit = u; break
            except (KeyError, FileNotFoundError):
                continue
        if rec is None or rec["status"] != "done":
            continue
        s = rec["spec"]; att = rec["attention"]; Ch = att["unit"]["link_bandwidth_gbps"] * 1e9; bw = float(s["bw"]); R = rec["N_s"] + rec["F_s"]
        lib = rec["candidates"]; runs = rec["search"]["runs"]; rep = rec["search"]["headline"]; strongest = rec["strongest"]
        default = "sequential"; prot = V.protocol_id(rec); gx, gy = rec["grid"]
        Hd, Hb = Hf(lib[default]), Hf(lib[strongest])
        alg = att.get("unit_layer_cost", {}).get("algorithm") or (att["kv_capacity"][0] if att.get("kv_capacity") else {})
        confs.append({"family": fam, "panel": {"reference 8-macro central K=1": "a", "capacity 16-macro central K=1": "b", "distributed K=4 fixed-total head groups": "c"}.get(fam, "expanded"), "model": model, "config_id": cid, "protocol_id": prot, "record_unit": unit, "record": V.record_path(unit),
                      "phase": s["phase"], "S": s["S"], "batch": 1, "tiling": s["tiling"], "tiling_id": rec["provenance"].get("tiling_id", ""), "die_macros": s.get("die_macros", 8), "n_cim_dies": rec["n_dies"], "grid": f"{gx}x{gy}", "empty_slots": rec["empty_slots"], "dies_per_layer": rec["dies_per_layer"],
                      "n_units": len(att["hubs"]), "unit_slots": ";".join(map(str, att["hubs"])), "unit_xy": ";".join(f"({h % gx},{h // gx})" for h in att["hubs"]), "grouping": att.get("split", "layer"), "resource_mode": s["offload"].get("resource_mode"), "position": s["offload"].get("position"),
                      "routing": s["routing"], "kappa": s["kappa"], "B_mesh_gbps": bw, "C_hub_gbps_per_direction_each": att["unit"]["link_bandwidth_gbps"], "unit_mac_per_s_each": att["unit"]["mac_per_second"], "kv_gbps_each": att["unit"]["kv_words_per_second"] / 1e9, "kv_capacity_bytes_each": att["unit"]["kv_capacity_words"], "buffer_bytes_each": att["unit"].get("buffer_bytes", ""),
                      "attention_algorithm": alg.get("algorithm", ""), "n_query_tiles": alg.get("n_tiles", ""), "R_s": R, "N_s": rec["N_s"], "F_s": rec["F_s"], "n_candidates_pool": len(lib), "n_named_rules": sum(1 for n in lib if not n.startswith("random_s")),
                      "rule_failures": json.dumps(rec.get("rule_failures", {})), "default": default, "strongest_named_rule": rec["strongest_rule"], "strongest_random": rec["strongest_random"], "best_baseline": strongest, "best_baseline_class": "random" if strongest.startswith("random_s") else "named rule", "search_representative": rep})
        roles = [("default", default, lib[default]), ("strongest named rule", rec["strongest_rule"], lib[rec["strongest_rule"]]), ("strongest random", rec["strongest_random"], lib[rec["strongest_random"]]), ("best baseline", strongest, lib[strongest]), ("search representative", rep, runs[rep])]
        for role, name, row in roles:
            H = Hf(row)
            cands.append({"family": fam, "model": model, "config_id": cid, "role": role, "layout": name, "candidate_class": ("search endpoint" if role.startswith("search") else "random" if name.startswith("random_s") else "named rule"), "statistic": "actual layout",
                          "R_s": R, "H_full_s": H, "H_service_s": row["H_s"], "P_s": row["prop_s"], "T_s": row["T_s"], "E_J": row["E_J"], "H_over_H_default": H / Hd, "comm_speedup_H_default_over_H": Hd / H, "eta_vs_best_baseline": 1 - H / Hb, "G_vs_best_baseline": 1 - row["T_s"] / lib[strongest]["T_s"],
                          "r0_of_best_baseline": Hb / lib[strongest]["T_s"], "B_eq_gbps": (V.solve_B(lib[strongest], H, Ch) or "") if role.startswith("search") else "", "protocol_id": prot})
        bests = {}
        for n, r in runs.items():
            if r["sa_seed"] not in bests or r["T_s"] < runs[bests[r["sa_seed"]]]["T_s"]:
                bests[r["sa_seed"]] = n
        per = []
        for sd, n in sorted(bests.items()):
            r = runs[n]; H = Hf(r)
            d = {"family": fam, "model": model, "config_id": cid, "seed": sd, "best_run": n, "start": r["start"], "start_layout": r.get("start_layout", ""), "H_full_s": H, "T_s": r["T_s"], "comm_speedup_H_default_over_H": Hd / H, "H_over_H_default": H / Hd, "eta_vs_best_baseline": 1 - H / Hb, "G_vs_best_baseline": 1 - r["T_s"] / lib[strongest]["T_s"], "is_representative": n == rep, "protocol_id": prot}
            per.append(d); seeds.append(d)
        for q in ("H_full_s", "T_s", "comm_speedup_H_default_over_H", "H_over_H_default", "eta_vs_best_baseline", "G_vs_best_baseline"):
            vals = sorted(x[q] for x in per); act = [x[q] for x in per if x["is_representative"]][0]
            for stat, val in (("actual_pair", act), ("seed_median", statistics.median(vals)), ("seed_min", vals[0]), ("seed_max", vals[-1])):
                metrics.append({"family": fam, "model": model, "config_id": cid, "quantity": q, "statistic": stat, "value": val, "n_seeds": len(vals), "representative_run": rep, "best_baseline": strongest, "default": default, "protocol_id": prot})
        for q, val in (("comm_speedup_H_default_over_H_best_baseline", Hd / Hb), ("H_best_baseline_over_H_default", Hb / Hd), ("r0_best_baseline", Hb / lib[strongest]["T_s"]), ("R_s", R), ("H_default_s", Hd), ("H_best_baseline_s", Hb), ("T_default_s", lib[default]["T_s"]), ("T_best_baseline_s", lib[strongest]["T_s"])):
            metrics.append({"family": fam, "model": model, "config_id": cid, "quantity": q, "statistic": "deterministic", "value": val, "n_seeds": "", "representative_run": rep, "best_baseline": strongest, "default": default, "protocol_id": prot})
    return confs, cands, seeds, metrics


def main():
    os.makedirs(V.V7, exist_ok=True)
    rows, curve, checks = gemma()
    V.write_csv("gemma_panel_a.csv", rows); V.write_csv("gemma_bandwidth_curve.csv", curve); V.write_json("gemma_checks.json", checks)
    print(f"gemma: eta {checks['pair']['eta_comm']*100:.2f}% G pair {checks['pair']['G_actual_pair']*100:.2f}% seeds median {checks['seed_statistics']['G_median']*100:.2f}% [{checks['seed_statistics']['G_min']*100:.2f},{checks['seed_statistics']['G_max']*100:.2f}] | savings sum {checks['savings_sum_s']*1e3:.2f} ms (pair diff residual {checks['savings_sum_minus_pair_difference_s']:.2e}) | B_eq {checks['B_eq']['B_eq_gbps']:.4f}")
    print("  category shares:", {k: round(v * 100, 2) for k, v in checks["category_shares"].items()})
    confs, cands, seeds, metrics = ninecell()
    V.write_csv("ninecell_configurations.csv", confs); V.write_csv("ninecell_candidates.csv", cands); V.write_csv("ninecell_seed_statistics.csv", seeds); V.write_csv("ninecell_metrics.csv", metrics)
    for c in confs:
        m = {(x["quantity"], x["statistic"]): x["value"] for x in metrics if x["config_id"] == c["config_id"] and x["family"] == c["family"]}
        print(f"  {c['family'][:38]:38s} {c['model']:8s} speedup default/best {m[('comm_speedup_H_default_over_H_best_baseline','deterministic')]:.3f} search median {m[('comm_speedup_H_default_over_H','seed_median')]:.3f} [{m[('comm_speedup_H_default_over_H','seed_min')]:.3f},{m[('comm_speedup_H_default_over_H','seed_max')]:.3f}] | eta pair {m[('eta_vs_best_baseline','actual_pair')]*100:.2f} median {m[('eta_vs_best_baseline','seed_median')]*100:.2f} | G pair {m[('G_vs_best_baseline','actual_pair')]*100:.2f} median {m[('G_vs_best_baseline','seed_median')]*100:.2f} | best {c['best_baseline']} rule {c['strongest_named_rule']}")


if __name__ == "__main__":
    main()
