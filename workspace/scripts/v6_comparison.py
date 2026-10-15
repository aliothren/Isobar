"""Follow-up P1 (section 7.3): the cross-model comparison export over the
representative configuration families (reference 8-macro central K = 1;
16-macro capacity central K = 1; K = 4 fixed-total head groups; the
expanded OPT-13B cases), from the confirmation records where they exist
and the exploration records otherwise (the protocol id says which).

    python3 scripts/v6_comparison.py  -> analysis/v6/representative_configurations.csv, comparison_candidates.csv,
                                         comparison_seed_statistics.csv, comparison_metrics.csv, expanded_case_confirmation.csv
"""
import csv
import math
import os
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v6_common as C                       # noqa: E402
from scripts import v3_sweep as v3                       # noqa: E402

FAMILIES = [  # (family, model, candidate units in order of preference, config id)
    *[("reference 8-macro central K=1", m, ["e9_confirm", "e9_ref"], f"{m}_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1") for m in ("opt6.7b", "gemma7b", "opt13b")],
    *[("capacity 16-macro central K=1", m, ["e10_confirm_cap_m16", "e10_cap_m16"], f"{m}_prefill512_colrow_sq_mesh_xy_k2_b0.4_m16_offcenterK1") for m in ("opt6.7b", "gemma7b", "opt13b")],
    *[("distributed K=4 fixed-total head groups", m, ["e10_confirm", "e10_head", "e9_head"], f"{m}_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK4TH") for m in ("opt6.7b", "gemma7b", "opt13b")],
    ("expanded: OPT-13B K=4 per-unit layer groups", "opt13b", ["e10_confirm", "e9_hub"], "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK4"),
    ("expanded: OPT-13B column-split QKV central K=1", "opt13b", ["e10_confirm", "e10_tiling"], "opt13b_prefill512_col_sq_mesh_xy_k2_b0.4_tlcol_offcenterK1"),
    ("expanded: OPT-13B K=4 fixed-total layer groups", "opt13b", ["e9_hub"], "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK4T"),
]


def H_at(row, bw, Ch):
    return row["prop_s"] + sum(max(max(l, dp) / (bw * 1e9), h / Ch) for l, dp, h in row["comp"])


def solve_Beq(base_row, target, bw, Ch):
    if H_at(base_row, 1e9, Ch) > target:
        return None
    lo, hi = bw, 1e6
    for _ in range(100):
        mid = math.sqrt(lo * hi)
        if H_at(base_row, mid, Ch) > target:
            lo = mid
        else:
            hi = mid
    return hi


def main():
    os.makedirs(C.V6, exist_ok=True)
    reps, cands, seeds, metrics = [], [], [], []
    for fam, model, units, cid in FAMILIES:
        rec = None
        for u in units:
            try:
                rec = C.find_record(u, cid); unit = u; break
            except (KeyError, FileNotFoundError):
                continue
        if rec is None or rec["status"] != "done":
            reps.append({"family": fam, "model": model, "config_id": cid, "status": "not available" if rec is None else rec["status"], "unit": "", "protocol_id": ""}); continue
        s = rec["spec"]; att = rec["attention"]; Ch = att["unit"]["link_bandwidth_gbps"] * 1e9; bw = float(s["bw"])
        prot = f"pool{rec['n_random']}_seeds{min(rec['search']['seeds'])}-{max(rec['search']['seeds'])}_obj{rec['search'].get('objective', 't_norm')}"
        R = rec["N_s"] + rec["F_s"]
        lib = rec["candidates"]; runs = rec["search"]["runs"]
        rules = [n for n in lib if not n.startswith("random_s")]
        strongest = rec["strongest"]; rep = rec["search"]["headline"]
        default = "sequential" if "sequential" in lib else min(rules, key=lambda n: lib[n]["T_s"])
        Hf = lambda row: row["H_s"] + row["prop_s"]
        Hd, Hb, Hs = Hf(lib[default]), Hf(lib[strongest]), Hf(runs[rep])
        Td, Tb, Ts = lib[default]["T_s"], lib[strongest]["T_s"], runs[rep]["T_s"]
        B_eq = solve_Beq(lib[strongest], Hs, bw, Ch)
        K = len(att["hubs"]); u = att["unit"]
        reps.append({"family": fam, "model": model, "config_id": cid, "status": "done", "unit": unit, "protocol_id": prot, "n_dies": rec["n_dies"], "grid": "x".join(map(str, rec["grid"])), "n_units": K,
                     "grouping": att.get("split", "layer"), "resource_mode": s["offload"].get("resource_mode"), "die_macros": s.get("die_macros", 8),
                     "unit_mac_per_s_each": u["mac_per_second"], "total_mac_per_s": u["mac_per_second"] * K, "kv_gbps_each": u["kv_words_per_second"] / 1e9, "kv_capacity_bytes_each": u["kv_capacity_words"],
                     "hub_gbps_per_direction_each": u["link_bandwidth_gbps"], "buffer_bytes_each": u["buffer_bytes"], "active_units_per_layer": K if att.get("split") == "head" else 1,
                     "R_s": R, "T_default_s": Td, "T_strongest_s": Tb, "T_search_s": Ts, "H_default_s": Hd, "H_strongest_s": Hb, "H_search_s": Hs, "strongest": strongest, "representative": rep})
        for role, name, row in (("default", default, lib[default]), ("strongest", strongest, lib[strongest]), ("search", rep, runs[rep])):
            cands.append({"family": fam, "model": model, "config_id": cid, "role": role, "layout": name, "T_s": row["T_s"], "H_full_s": Hf(row), "H_service_s": row["H_s"], "P_s": row["prop_s"], "E_J": row["E_J"], "protocol_id": prot})
        bests = {}
        for n, r in runs.items():
            if r["sa_seed"] not in bests or r["T_s"] < runs[bests[r["sa_seed"]]]["T_s"]:
                bests[r["sa_seed"]] = n
        for sd, n in sorted(bests.items()):
            seeds.append({"family": fam, "model": model, "config_id": cid, "seed": sd, "best_run": n, "start": runs[n]["start"], "T_s": runs[n]["T_s"], "H_full_s": Hf(runs[n]), "G_backbone": 1 - runs[n]["T_s"] / Tb, "eta_comm": 1 - Hf(runs[n]) / Hb, "is_representative": n == rep})
        gains = sorted(1 - runs[n]["T_s"] / Tb for n in bests.values())
        metrics.append({"family": fam, "model": model, "config_id": cid, "protocol_id": prot, "H_strongest_over_H_default": Hb / Hd, "H_search_over_H_default": Hs / Hd, "comm_speedup_default_over_strongest": Hd / Hb, "comm_speedup_default_over_search": Hd / Hs,
                        "eta_strongest_vs_default": 1 - Hb / Hd, "eta_search_vs_default": 1 - Hs / Hd, "eta_comm_search_vs_strongest": 1 - Hs / Hb, "r0": Hb / Tb, "G_backbone_search_vs_strongest": 1 - Ts / Tb,
                        "G_median_seeds": statistics.median(gains), "G_min_seeds": gains[0], "G_max_seeds": gains[-1], "B_eq_gbps": B_eq if B_eq else "", "g_bw": (B_eq / bw - 1) if B_eq else "", "B_eq_reachable": B_eq is not None,
                        "identity_check_abs": abs((1 - Ts / Tb) - (1 - Hs / Hb) * (Hb / Tb))})
    for name, rows in (("representative_configurations.csv", reps), ("comparison_candidates.csv", cands), ("comparison_seed_statistics.csv", seeds), ("comparison_metrics.csv", metrics)):
        keys = []
        for r in rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with open(os.path.join(C.V6, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    with open(os.path.join(C.V6, "expanded_case_confirmation.csv"), "w", newline="") as f:
        rows = [m for m in metrics if m["family"].startswith("expanded")]
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    for m, r in zip(metrics, [x for x in reps if x["status"] == "done"]):
        print(f"{m['family'][:40]:40s} {m['model']:8s} [{m['protocol_id'][:24]}] T strongest {r['T_strongest_s']*1e3:8.1f} search {r['T_search_s']*1e3:8.1f} ms | eta {m['eta_comm_search_vs_strongest']*100:5.1f} r0 {m['r0']*100:5.1f} G {m['G_backbone_search_vs_strongest']*100:5.2f} [{m['G_min_seeds']*100:.2f},{m['G_max_seeds']*100:.2f}] | B_eq {m['B_eq_gbps'] if m['B_eq_gbps']=='' else round(m['B_eq_gbps'],3)} | H/H_default {m['H_search_over_H_default']:.3f}")
    for r in reps:
        if r["status"] != "done":
            print("not available:", r["family"], r["model"], r["status"])
    print("->", C.V6)


if __name__ == "__main__":
    main()
