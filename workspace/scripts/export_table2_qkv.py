"""Table II data: OPT-13B with the QKV projection row-split (10 dies per
layer, 2200 dies) or column-split (15 dies per layer, 2400 dies) on the
same 49 x 49 mesh, central unit at the same coordinate, confirmation
protocol: per configuration the best baseline and the search
representative (communication time, end-to-end time, eta), the flow
structure, and the per-stage loads of the default fill, the best baseline
and the search representative.

    python3 scripts/export_table2_qkv.py
      -> results/exports/qkv_common_grid_comparison.csv, qkv_common_grid_stage_loads.csv
"""
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import export_common as V                  # noqa: E402
from scripts import export_fig7_mechanisms as F7        # noqa: E402
from scripts import records as C                        # noqa: E402
from scripts import search_space as ss                  # noqa: E402

CASES = [("row-49x49", "qkv_split", "opt13b_prefill512_colrow_49x49_mesh_xy_k2_b0.4_offcenterK1"),
         ("column-49x49", "qkv_split", "opt13b_prefill512_col_sq_mesh_xy_k2_b0.4_tlcol_offcenterK1")]


def main():
    rows, loads = [], []
    for label, unit, cid in CASES:
        try:
            rec = C.find_record(unit, cid)
        except (KeyError, FileNotFoundError):
            rows.append({"configuration": label, "unit": unit, "config_id": cid, "status": "not available"}); continue
        if rec["status"] != "done":
            rows.append({"configuration": label, "unit": unit, "config_id": cid, "status": rec["status"]}); continue
        row = F7.base_row(unit, rec); row["configuration"] = label; row["status"] = "done"
        s = rec["spec"]; phase = s["phase"]; bw = float(s["bw"]); kappa = float(s["kappa"])
        W = C.workload_from_record(rec); row.update(F7.flow_structure(rec))
        runs = rec["search"]["runs"]; rep = rec["search"]["headline"]; st = rec["strongest"]
        gx, gy = rec["grid"]; row["unit_xy"] = ";".join(f"({h % gx},{h // gx})" for h in rec["attention"]["hubs"])
        for n, p in ((st, C.candidate_layout(W, st)), (rep, ss.Pi.from_json(runs[rep]["best_pi"])), ("sequential", C.candidate_layout(W, "sequential"))):
            sc, bs = C.evaluate(W, p, phase, bw)
            agg = {}
            for r in C.stage_rows(W, bs, bw, kappa):
                d = agg.setdefault(r["stage"], {"n": 0, "payload_words": 0.0, "service_s": 0.0, "propagation_s": 0.0, "busiest_link_words_max": 0.0, "hub_port_words_max": 0.0, "binding": {}})
                d["n"] += 1; d["payload_words"] += r["payload_words"]; d["service_s"] += r["service_s"]; d["propagation_s"] += r["propagation_s"]
                d["busiest_link_words_max"] = max(d["busiest_link_words_max"], r["link_max_words"]); d["hub_port_words_max"] = max(d["hub_port_words_max"], r["hub_port_max_words"]); d["binding"][r["binding"]] = d["binding"].get(r["binding"], 0) + 1
            for stg, d in agg.items():
                loads.append({"configuration": label, "config_id": cid, "layout": n, "role": "best baseline" if n == st else ("search representative" if n == rep else "default"), "stage": stg, "n_handoffs": d["n"], "payload_words_total": d["payload_words"], "H_stage_total_s": d["service_s"] + d["propagation_s"], "service_s_total": d["service_s"], "propagation_s_total": d["propagation_s"],
                              "busiest_link_words_max": d["busiest_link_words_max"], "hub_port_words_max": d["hub_port_words_max"], "binding_counts": ";".join(f"{k}:{v}" for k, v in sorted(d["binding"].items())), "T_s": sc.t_opt_s, "H_full_s": sc.per_phase[phase]["decomp"]["d2d_serial_s"] + sc.per_phase[phase]["decomp"]["propagation_s"]})
            if n == st:
                row["qkv_to_unit_payload_words_total_best"] = agg.get("qkv->unit", {}).get("payload_words", ""); row["ffn2_to_qkv_payload_words_total_best"] = agg.get("ffn2->next qkv", {}).get("payload_words", ""); row["max_link_words_best"] = max(d["busiest_link_words_max"] for d in agg.values())
            if n == rep:
                row["max_link_words_search"] = max(d["busiest_link_words_max"] for d in agg.values())
        row["precision_note"] = "activations 1 B; row-split qkv consumer of ffn2 output receives its slice (1 B); column-split qkv produces full-width outputs; partial sums (row-split operators) 2 B per element"
        rows.append(row)
    V.write_csv("qkv_common_grid_comparison.csv", rows); V.write_csv("qkv_common_grid_stage_loads.csv", loads)
    for r in rows:
        if r.get("status") == "done":
            print(f"  {r['configuration']:18s} dies {r['n_cim_dies']} {r['grid']} empty {r['empty_slots']} unit {r['unit_xy']} qkv dies {r['dies_qkv_proj']} {r['split_qkv_proj'][:6]} | T best {r['T_best_baseline_s']*1e3:8.1f} search {r['T_search_s']*1e3:8.1f} | H {r['H_best_baseline_s']*1e3:8.1f}->{r['H_search_s']*1e3:8.1f} eta {r['eta_comm']*100:5.1f} r0 {r['r0']*100:5.1f} G {r['G']*100:5.1f} | hub words best {r['hub_words_sum_best']:.3g} | qkv->unit words {r.get('qkv_to_unit_payload_words_total_best','')}")
        else:
            print("  ", r["configuration"], r["status"])


if __name__ == "__main__":
    main()
