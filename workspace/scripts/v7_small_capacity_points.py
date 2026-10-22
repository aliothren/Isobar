"""Fig. 7(a) data: OPT-1.3B at 4, 8, 16 and 32 macros per die under the capacity
curve's exploration protocol (pool 100, seeds 0-4, t_norm objective, the
e10_cap budget rule), from the e11_small_expl / e11_small_cap_expl(_m4, _m32)
deployments; the columns of offload_capacity.csv that the panel reads.

    python3 scripts/v7_small_capacity_points.py
      -> analysis/v7/offload_capacity_small.csv
"""
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v7_common as V                      # noqa: E402
from scripts import v6_common as C                      # noqa: E402

UNITS = [("e11_small_cap_expl_m4", "opt1.3b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m4_offcenterK1", 4),
         ("e11_small_expl", "opt1.3b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1", 8),
         ("e11_small_cap_expl", "opt1.3b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m16_offcenterK1", 16),
         ("e11_small_cap_expl_m32", "opt1.3b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m32_offcenterK1", 32)]


def Hf(row):
    return row["H_s"] + row["prop_s"]


def main():
    rows = []
    for unit, cid, macros in UNITS:
        rec = C.find_record(unit, cid)
        lib, runs = rec["candidates"], rec["search"]["runs"]
        base, rep = lib[rec["strongest"]], runs[rec["search"]["headline"]]
        R = rec["N_s"] + rec["F_s"]
        Hb, Hs, Hd = Hf(base), Hf(rep), Hf(lib["sequential"])
        gx, gy = rec["grid"]
        rows.append({"unit": unit, "config_id": cid, "protocol_id": V.protocol_id(rec), "model": "opt1.3b", "phase": "prefill",
                     "S": 512, "die_macros": macros, "grid": f"{gx}x{gy}", "n_cim_dies": rec["n_dies"],
                     "R_s": R, "H_default_s": Hd, "T_default_s": R + Hd, "best_baseline": rec["strongest"],
                     "strongest_named_rule": rec["strongest_rule"], "strongest_random": rec["strongest_random"],
                     "H_best_baseline_s": Hb, "T_best_baseline_s": R + Hb, "search_representative": rec["search"]["headline"],
                     "H_search_s": Hs, "T_search_s": R + Hs, "eta_comm": 1 - Hs / Hb, "r0": Hb / (R + Hb),
                     "G": 1 - (R + Hs) / (R + Hb), "comm_speedup_default_over_best": Hd / Hb,
                     "comm_speedup_default_over_search": Hd / Hs, "record": V.record_path(unit), "status": "done",
                     "grid_kind": "natural", "protocol_group": "exploration"})
    V.write_csv("offload_capacity_small.csv", rows)
    for r in rows:
        print(f"{r['die_macros']:>3} macros: {r['n_cim_dies']} dies {r['grid']}, eta {100 * r['eta_comm']:.2f}%, "
              f"G {100 * r['G']:.2f}%, r0 {100 * r['r0']:.1f}%, {r['protocol_id']}")


if __name__ == "__main__":
    main()
