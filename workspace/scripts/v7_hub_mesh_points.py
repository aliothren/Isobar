"""Second batch (Isobar_next_tasks section 6): the selected hub x mesh points
with three result sources each: the frozen reference pair re-priced, the
reselected pool (best baseline re-chosen among the saved rules + pool, best
saved search among the saved endpoints) and the fresh search (e11_hubmesh).

    python3 scripts/v7_hub_mesh_points.py -> analysis/v7/hub_mesh_selected_checks.csv, hub_mesh_fresh_search.csv
"""
import os
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v7_common as V                      # noqa: E402
from scripts import v6_common as C                      # noqa: E402

POINTS = [("prefill", 12.5, 1.6, "mesh competition near the reference: higher mesh bandwidth at the reference hub (gain moves > 3 points)"), ("prefill", 0.2, 0.4, "hub lower bound dominant: no finite boundary for the rules, strongest baseline changes"),
          ("prefill", 0.8, 0.8, "strongest baseline changes with the hub and mesh both raised; frozen gain drops"), ("prefill", 12.5, 12.5, "above B+ of the rules: strongest baseline changes, frozen eta drops"),
          ("decode", 0.4, 0.4, "decode: strongest baseline changes, hub at 0.4 GB/s (hub lower bound)"), ("decode", 1.6, 1.6, "decode: gain moves > 3 points vs the neighbour at a mid hub / mesh point")]


def Hf(r):
    return r["H_s"] + r["prop_s"]


def main():
    out, fresh = [], []
    for ph, Ch, B, why in POINTS:
        ref = C.find_record("e9_ref", f"gemma7b_{ph}512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1")
        R = ref["N_s"] + ref["F_s"]; Chw = Ch * 1e9
        lib = ref["candidates"]; runs = ref["search"]["runs"]; rep = ref["search"]["headline"]; st = ref["strongest"]
        base = {"phase": ph, "C_hub_gbps": Ch, "B_mesh_gbps": B, "selection_reason": why, "reference_record": V.record_path("e9_ref"), "reference_config_id": ref["config_id"], "R_s": R}
        # 1. frozen pair
        Hb, Hs = V.H_of(lib[st], B, Chw), V.H_of(runs[rep], B, Chw)
        out.append({**base, "source": "frozen pair", "candidate_set": "reference best baseline + reference representative, re-priced", "baseline": st, "search": rep, "H_baseline_s": Hb, "H_search_s": Hs, "T_baseline_s": R + Hb, "T_search_s": R + Hs, "eta_comm": 1 - Hs / Hb, "r0": Hb / (R + Hb), "G": 1 - (R + Hs) / (R + Hb),
                    "binding_baseline": str(V.H_binding(lib[st], B, Chw)), "binding_search": str(V.H_binding(runs[rep], B, Chw)), "B_eq_gbps": V.solve_B(lib[st], Hs, Chw) or "", "n_seeds": ""})
        # 2. reselected pool
        Hp = {n: V.H_of(r, B, Chw) for n, r in lib.items()}; He = {n: V.H_of(r, B, Chw) for n, r in runs.items()}
        st2 = min(Hp, key=Hp.get); se2 = min(He, key=He.get)
        out.append({**base, "source": "reselected pool", "candidate_set": f"saved rules + {ref['n_random']} random (best baseline re-chosen); saved {len(runs)} search endpoints (best saved search)", "baseline": st2, "search": se2, "H_baseline_s": Hp[st2], "H_search_s": He[se2], "T_baseline_s": R + Hp[st2], "T_search_s": R + He[se2],
                    "eta_comm": 1 - He[se2] / Hp[st2], "r0": Hp[st2] / (R + Hp[st2]), "G": 1 - (R + He[se2]) / (R + Hp[st2]), "binding_baseline": str(V.H_binding(lib[st2], B, Chw)), "binding_search": str(V.H_binding(runs[se2], B, Chw)), "B_eq_gbps": V.solve_B(lib[st2], He[se2], Chw) or "", "n_seeds": "",
                    "baseline_changed": st2 != st, "search_changed": se2 != rep})
        # 3. fresh search
        recs = [r for r in C.load_records("e11_hubmesh") if r["spec"]["phase"] == ph and abs(float(r["spec"]["bw"]) - B) < 1e-9 and abs(r["spec"]["offload"].get("unit", {}).get("link_bandwidth_gbps", 12.5) - Ch) < 1e-9]
        if not recs or recs[0]["status"] != "done":
            out.append({**base, "source": "fresh search", "candidate_set": "e11_hubmesh (100 random, seeds 0-4, h_norm)", "status": "not available" if not recs else recs[0]["status"]}); continue
        fr = recs[0]; flib = fr["candidates"]; fruns = fr["search"]["runs"]; frep = fr["search"]["headline"]; fst = fr["strongest"]
        Hb3, Hs3 = Hf(flib[fst]), Hf(fruns[frep])
        bests = {}
        for n, r in fruns.items():
            if r["sa_seed"] not in bests or r["T_s"] < fruns[bests[r["sa_seed"]]]["T_s"]:
                bests[r["sa_seed"]] = n
        Gs = sorted(1 - fruns[n]["T_s"] / flib[fst]["T_s"] for n in bests.values()); etas = sorted(1 - Hf(fruns[n]) / Hb3 for n in bests.values())
        out.append({**base, "source": "fresh search", "candidate_set": f"new pool: rules + {fr['n_random']} random; SA seeds {min(fr['search']['seeds'])}-{max(fr['search']['seeds'])}, objective {fr['search'].get('objective')}", "baseline": fst, "search": frep, "H_baseline_s": Hb3, "H_search_s": Hs3, "T_baseline_s": flib[fst]["T_s"], "T_search_s": fruns[frep]["T_s"],
                    "eta_comm": 1 - Hs3 / Hb3, "r0": Hb3 / flib[fst]["T_s"], "G": 1 - fruns[frep]["T_s"] / flib[fst]["T_s"], "binding_baseline": str(V.H_binding(flib[fst], B, Chw)), "binding_search": str(V.H_binding(fruns[frep], B, Chw)), "B_eq_gbps": V.solve_B(flib[fst], Hs3, Chw) or "", "n_seeds": len(Gs),
                    "G_seed_median": statistics.median(Gs), "G_seed_min": Gs[0], "G_seed_max": Gs[-1], "eta_seed_median": statistics.median(etas), "eta_seed_min": etas[0], "eta_seed_max": etas[-1], "fresh_config_id": fr["config_id"], "fresh_protocol_id": V.protocol_id(fr), "fresh_record": V.record_path("e11_hubmesh"),
                    "frozen_search_H_at_point_s": Hs, "frozen_search_vs_fresh_search_H_ratio": Hs / Hs3, "rules_B_minus_gbps": fr.get("band", {}).get("rules", {}).get("B_minus", ""), "rules_B_plus_gbps": fr.get("band", {}).get("rules", {}).get("B_plus", ""), "rules_no_finite": fr.get("band", {}).get("rules", {}).get("no_finite_boundary", "")})
        for sd, n in sorted(bests.items()):
            r = fruns[n]
            fresh.append({"phase": ph, "C_hub_gbps": Ch, "B_mesh_gbps": B, "config_id": fr["config_id"], "seed": sd, "best_run": n, "start": r["start"], "T_s": r["T_s"], "H_full_s": Hf(r), "eta_vs_best_baseline": 1 - Hf(r) / Hb3, "G_vs_best_baseline": 1 - r["T_s"] / flib[fst]["T_s"], "is_representative": n == frep, "best_baseline": fst, "protocol_id": V.protocol_id(fr)})
    V.write_csv("hub_mesh_selected_checks.csv", out); V.write_csv("hub_mesh_fresh_search.csv", fresh)
    for r in out:
        if r.get("status"):
            print(f"  {r['phase']:7s} Ch {r['C_hub_gbps']:5.2f} B {r['B_mesh_gbps']:5.2f} {r['source']:16s} {r['status']}")
        else:
            print(f"  {r['phase']:7s} Ch {r['C_hub_gbps']:5.2f} B {r['B_mesh_gbps']:5.2f} {r['source']:16s} base {r['baseline']:14s} search {r['search']:22s} H {r['H_baseline_s']*1e3:8.1f}->{r['H_search_s']*1e3:8.1f} eta {r['eta_comm']*100:5.1f} r0 {r['r0']*100:5.1f} G {r['G']*100:5.1f}" + (f" seeds [{r['G_seed_min']*100:.1f},{r['G_seed_max']*100:.1f}]" if r.get("n_seeds") else ""))


if __name__ == "__main__":
    main()
