"""Configuration sweep (section 4.1, extended): die capacity x device rate x
mesh bandwidth x K/V bandwidth (x QKV split for OPT-13B), every point the
same fixed layout of the die-variant record re-priced (no re-search),
against the two GPU baselines.

    CIMSIM_FABRIC=<variant of --macros> python3 gpu_comparison/scripts/sweep.py --model opt13b --macros 8 [--split col]
      -> gpu_comparison/sweep/sweep_<model>_m<macros>[_col].csv
"""
import argparse
import csv
import json
import os
import sys

G = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(G, "scripts"))
from cim_request import RequestModel                    # noqa: E402

GPU = {"opt13b": {"T_s": 1024 / 47.33, "E_J": 253.0 * 1024 / 47.33, "O": 1024, "lengths": [[64, 1]]}, "gemma7b": {"T_s": 24.826377788208873, "E_J": 1898.6848416950472, "O": 500, "lengths": None}}
RATES = [("neurram_10.14us", 1.0, "NeuRRAM-class measured row time 10.14 us (reference)"), ("isaac_1.6us", 10.14 / 1.6, "ISAAC design point: 16 one-bit input slices x 100 ns = 1.6 us per row"),
         ("hermes_4phase_0.52us", 10.14 / 0.52, "HERMES 64-core, 4-phase MVM 520 ns per row (derived from the published peak)"), ("hermes_1phase_0.133us", 10.14 / 0.133, "HERMES 1-phase MVM 133 ns per row (63.1 TOPS peak / 64 cores)")]
MESH = [(0.4, "HERMES-class analog link, 3.2 Gbit/s per link"), (1.6, "intermediate tier (4x the analog link)"), (4.0, "ISAAC-class inter-tile link, 32 bit at 1 GHz"), (12.5, "Simba GRS package link, 25 Gb/s x 4 lanes")]
KV = [(25.6e9, "LPDDR4 two 32-bit channels at 3200 MT/s (reference)"), (51.2e9, "LPDDR5 two 32-bit channels at 6400 MT/s"), (136e9, "one LPDDR5X x128 package, 8 channels x 17 GB/s (CXL-PNM paper, Table I)")]
RECORDS = {("opt13b", 8, "colrow"): ("e9_confirm", "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"), ("opt13b", 16, "colrow"): ("e10_confirm_cap", "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m16_offcenterK1"), ("opt13b", 32, "colrow"): ("e10_cap_m32", "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m32_offcenterK1"),
           ("opt13b", 4, "colrow"): ("e10_cap_m4", "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m4_offcenterK1"), ("opt13b", 8, "col"): ("e10_confirm", "opt13b_prefill512_col_sq_mesh_xy_k2_b0.4_tlcol_offcenterK1"),
           ("gemma7b", 8, "colrow"): ("e9_confirm", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"), ("gemma7b", 16, "colrow"): ("e10_confirm_cap", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m16_offcenterK1"), ("gemma7b", 32, "colrow"): ("e10_cap_m32", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m32_offcenterK1"),
           ("gemma7b", 4, "colrow"): ("e10_cap_m4", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m4_offcenterK1")}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--model", required=True); ap.add_argument("--macros", type=int, required=True); ap.add_argument("--split", default="colrow"); args = ap.parse_args()
    unit, cid = RECORDS[(args.model, args.macros, args.split)]
    g = GPU[args.model]
    lengths = g["lengths"] or [[int(r["input_tokens"]), int(r["count"])] for r in csv.DictReader(open(os.path.join(G, "sources", "hydra_input_lengths.csv")))]
    base = {"id": f"sweep_{args.model}_m{args.macros}_{args.split}", "model": args.model, "record_unit": unit, "config_id": cid, "die_macros": args.macros, "unit_overrides": {}, "rope": args.model == "gemma7b", "learned_positions": args.model == "opt13b", "lengths": lengths, "output_tokens": g["O"]}
    M = RequestModel(base)
    n = sum(c for _, c in lengths); rows = []
    for bw, bw_src in MESH:
        for rtag, rf, r_src in RATES:
            for kv, kv_src in KV:
                M.set_variant(bw=bw, rate_factor=rf, unit_overrides={"kv_words_per_second": kv})
                acc = {}
                for Lin, cnt in lengths:
                    r = M.request(int(Lin), g["O"])
                    for k, v in r.items():
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            acc[k] = acc.get(k, 0.0) + v * cnt
                mean = {k: v / n for k, v in acc.items()}
                T, E = mean["T_request_s"], mean["E_request_J"]
                row = {"model": args.model, "qkv_split": args.split, "die_macros": args.macros, "n_cim_dies": M.rec["n_dies"], "grid": "x".join(map(str, M.rec["grid"])), "device_rate": rtag, "device_rate_factor": rf, "device_rate_source": r_src, "row_time_us": 10.14 / rf,
                       "mesh_gbps": bw, "mesh_source": bw_src, "kv_gbps": kv / 1e9, "kv_source": kv_src, "hub_gbps": M.unit["link_bandwidth_gbps"], "unit_mac_per_s": M.unit["mac_per_second"], "layout": M.layout, "record": f"{unit}/{cid}",
                       "T_request_s": T, "T_prefill_s": mean["T_prefill_s"], "T_decode_sum_s": mean["T_decode_sum_s"], "E_request_J": E, "E_per_output_token_J": E / g["O"], "GPU_T_s": g["T_s"], "GPU_E_J": g["E_J"],
                       "energy_advantage": g["E_J"] / E, "energy_saving": 1 - E / g["E_J"], "speedup": g["T_s"] / T, "P_remaining_budget_W": (g["E_J"] - E) / T}
                for c in ("cim", "digital_elementwise", "unit_compute", "unit_kv", "comm", "model_end"):
                    row[f"T_share_{c}"] = mean[f"T_{c}_s_request"] / T; row[f"E_share_{c}"] = mean[f"E_{c}_J_request"] / E
                rows.append(row)
                print(f"{args.model} m{args.macros} {args.split} {rtag:22s} mesh {bw:5.1f} kv {kv/1e9:6.1f} | T {T:7.3f} s E {E:6.2f} J | x{row['speedup']:5.2f} adv {row['energy_advantage']:6.1f}", flush=True)
    os.makedirs(os.path.join(G, "sweep"), exist_ok=True)
    out = os.path.join(G, "sweep", f"sweep_{args.model}_m{args.macros}{'_' + args.split if args.split != 'colrow' else ''}.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("->", out)


if __name__ == "__main__":
    main()
