"""Comparison summary (section 5): per configuration the request-weighted
mean CIM time and energy, the GPU baseline, the ratios, the remaining
background-power budget and the component shares; plus the resource table
of every configuration.

    python3 gpu_comparison/scripts/summarize.py -> gpu_comparison/comparison_summary.csv, cim_requests.csv, configs/resources.csv
"""
import csv
import glob
import json
import os

G = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GPU = {"A": {"T_s": 1024 / 47.33, "T_window_s": "", "E_J": 253.0 * 1024 / 47.33, "O": 1024, "label": "A100 40 GB, FasterTransformer, 64:1024 (GPU power 253 W, 47.33 tok/s)", "boundary": "GPU device power"},
       "B": {"T_s": 24.826377788208873, "T_window_s": 24.82546911085952, "E_J": 1898.6848416950472, "O": 500, "label": "Jetson AGX Thor, llama.cpp Q8_0, 541 IFEval requests x 500 output tokens (board VIN)", "boundary": "whole board input power"}}
COMP = ["cim", "digital_elementwise", "unit_compute", "unit_kv", "comm", "model_end"]


def main():
    allrows, summ, res = [], [], []
    for p in sorted(glob.glob(os.path.join(G, "cim_requests_*.csv"))):
        rows = list(csv.DictReader(open(p))); meta = json.load(open(p.replace(".csv", "_meta.json"))); cfg = json.load(open(os.path.join(G, "configs", meta["id"] + ".json")))
        allrows += rows
        n = sum(int(r["count"]) for r in rows)
        wm = lambda k: sum(float(r[k]) * int(r["count"]) for r in rows) / n
        g = GPU[meta["id"][0]]; T, E = wm("T_request_s"), wm("E_request_J")
        shares_t = {c: wm(f"T_{c}_s_request") / T for c in COMP}; shares_e = {c: wm(f"E_{c}_J_request") / E for c in COMP}
        summ.append({"config_id": meta["id"], "group": "A_opt13b_a100" if meta["id"][0] == "A" else "B_gemma7b_thor", "model": cfg["model"], "note": cfg["note"], "n_requests": n, "output_tokens": g["O"],
                     "GPU_T_request_s": g["T_s"], "GPU_T_execution_window_s": g["T_window_s"], "GPU_E_request_J": g["E_J"], "GPU_E_per_output_token_J": g["E_J"] / g["O"], "GPU_label": g["label"], "GPU_energy_boundary": g["boundary"],
                     "CIM_T_request_s": T, "CIM_T_prefill_s": wm("T_prefill_s"), "CIM_T_decode_sum_s": wm("T_decode_sum_s"), "CIM_E_request_J": E, "CIM_E_per_output_token_J": E / g["O"], "CIM_energy_boundary": "dynamic energy of CIM arrays and periphery (account), digital element-wise, unit attention compute, K/V memory, interconnect, model-end operators; no static / background power modelled",
                     "energy_advantage_GPU_over_CIM": g["E_J"] / E, "energy_saving": 1 - E / g["E_J"], "speedup_GPU_over_CIM": g["T_s"] / T, "P_remaining_budget_W": (g["E_J"] - E) / T,
                     **{f"T_share_{c}": shares_t[c] for c in COMP}, **{f"E_share_{c}": shares_e[c] for c in COMP}, "decode_time_share": wm("T_decode_sum_s") / T, "kv_fits_all": all(r["kv_fits"] == "True" for r in rows),
                     "energy_label": "modeled dynamic energy (no static / idle power in any model term)", "E_scenario_all_links_on_J": meta.get("E_scenario_all_links_on_J") or "", "scenario_all_links_on_power_W": meta.get("scenario_all_links_on_power_W") or "", "n_link_directions_extended_grid": meta.get("n_link_directions_extended_grid", ""),
                     "E_dynamic_plus_scenario_all_links_on_J": (E + meta["E_scenario_all_links_on_J"]) if meta.get("E_scenario_all_links_on_J") else "", "interconnect_energy_model": "traffic-based (per bit) as Gemini HPCA 2024 section V-B2 for clock-forwarding GRS / UCIe links; the all-links-on figure is a scenario, not a modelled static term", "extended_grid_with_lm_head": "x".join(map(str, meta["extended_grid_with_lm_head"])), "lm_head_dies": meta["lm_head_dies"], "kv_bytes_per_element": meta["kv_bytes_per_element"],
                     **{f"E_{c}_J": wm(f"E_{c}_J_request") for c in COMP},
                     "layout": meta["layout"], "record_config_id": cfg["config_id"], "statistic": "request-weighted means over the length frequencies (B) / the single request (A); ratios of means", "precision": cfg["precision"]})
        u = meta["unit"]; gx, gy = meta["grid"]
        res.append({"config_id": meta["id"], "model": cfg["model"], "die_macros": cfg["die_macros"], "cim_cells_per_die": cfg["die_macros"] * 32 * 256 * 256, "n_cim_dies_backbone": meta["n_cim_dies"], "grid": f"{gx}x{gy}", "lm_head_dies_extra": meta["lm_head"]["dies"], "n_digital_units": 1, "unit_total_mac_per_s": u["mac_per_second"],
                    "kv_bandwidth_gbps": u["kv_words_per_second"] / 1e9, "kv_capacity_bytes": u["kv_capacity_words"], "unit_buffer_bytes": u.get("buffer_bytes", ""), "hub_gbps_per_direction": u["link_bandwidth_gbps"], "mesh_gbps_per_direction": meta["bw_gbps"], "die_port_gbps": meta["kappa"] * meta["bw_gbps"], "kappa": meta["kappa"], "routing": "XY", "propagation_ns_per_hop": 20,
                    "device_row_time_us": 10.14, "device": "NeuRRAM-class RRAM macro (CiMLoop calibration)", "energy_coefficients": "CIM: account per operator; digital: Horowitz-class 16 bit + GLB 15.47 pJ/word; unit 1 pJ per MAC-eq op; K/V 50 pJ/B; link 10 pJ/word + 10 pJ/word/surplus hop; DRAM read 50 pJ/word", "sources": json.dumps(cfg["sources"])})
    for name, rows in (("comparison_summary.csv", summ), ("cim_requests.csv", allrows), (os.path.join("configs", "resources.csv"), res)):
        keys = []
        for r in rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with open(os.path.join(G, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    for s in summ:
        print(f"{s['config_id']:14s} GPU T {s['GPU_T_request_s']:7.2f} s E {s['GPU_E_request_J']:7.1f} J | CIM T {s['CIM_T_request_s']:7.3f} s (prefill {s['CIM_T_prefill_s']:.3f}) E {s['CIM_E_request_J']:6.2f} J | adv {s['energy_advantage_GPU_over_CIM']:6.1f}x speedup {s['speedup_GPU_over_CIM']:5.2f}x budget {s['P_remaining_budget_W']:7.1f} W | T shares " + " ".join(f"{c[:6]} {s[f'T_share_{c}']*100:4.1f}" for c in COMP) + " | E shares " + " ".join(f"{c[:6]} {s[f'E_share_{c}']*100:4.1f}" for c in COMP))


if __name__ == "__main__":
    main()
