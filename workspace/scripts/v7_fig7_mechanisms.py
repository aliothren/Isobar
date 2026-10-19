"""Fig. 7 data (Isobar_next_tasks section 3.7): capacity and legal
decomposition, resource organisation and workspace, phase / length, all
from the stored e9_* / e10_* records (exploration and confirmation
protocols kept apart), with the flow structure of each capacity point.

    python3 scripts/v7_fig7_mechanisms.py
      -> analysis/v7/offload_capacity.csv, offload_capacity_common_grid.csv, resource_organization_comparison.csv,
         workspace_thresholds.csv, workload_length_sweep.csv
"""
import json
import os
import re
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v7_common as V                      # noqa: E402
from scripts import v6_common as C                      # noqa: E402
from scripts import cimsim_cli as cli                   # noqa: E402

OPS = ["qkv_proj", "attention", "out_proj", "ffn1", "ffn2"]


def Hf(row):
    return row["H_s"] + row["prop_s"]


def tiling(tid):
    out = {}
    body = tid.split(":", 1)[1] if ":" in tid else tid
    for part in body.split("/"):
        for op in OPS:
            if part.startswith(op):
                m = re.match(r"(\d+)([MC]?)", part[len(op):]); out[op] = (int(m.group(1)), {"M": "column (output)", "C": "row (input, partial sums)", "": "unit"}[m.group(2)])
    return out


def base_row(unit, rec):
    s = rec["spec"]; att = rec["attention"]; lib = rec["candidates"]; runs = rec["search"]["runs"]; rep = rec["search"]["headline"]; st = rec["strongest"]; R = rec["N_s"] + rec["F_s"]
    Ch = att["unit"]["link_bandwidth_gbps"] * 1e9; Hb, Hs = Hf(lib[st]), Hf(runs[rep]); Hd = Hf(lib["sequential"])
    lb = att["layer_breakdown_s"]; L = s["L"]; K = len(att["hubs"]); u = att["unit"]; alg = att.get("unit_layer_cost", {}).get("algorithm", {})
    td = tiling(rec["provenance"].get("tiling_id", ""))
    gx, gy = rec["grid"]
    row = {"unit": unit, "config_id": rec["config_id"], "protocol_id": V.protocol_id(rec), "model": s["model"], "phase": s["phase"], "S": s["S"], "die_macros": s.get("die_macros", 8), "tiling": s["tiling"], "tiling_id": rec["provenance"].get("tiling_id", ""),
           **{f"dies_{op}": td.get(op, ("", ""))[0] for op in OPS}, **{f"split_{op}": td.get(op, ("", ""))[1] for op in OPS}, "dies_per_layer": rec["dies_per_layer"], "n_cim_dies": rec["n_dies"], "grid": f"{gx}x{gy}", "empty_slots": rec["empty_slots"],
           "n_units": K, "grouping": att.get("split", "layer"), "resource_mode": s["offload"].get("resource_mode"), "position": s["offload"].get("position"), "unit_slots": ";".join(map(str, att["hubs"])),
           "unit_mac_per_s_each": u["mac_per_second"], "unit_mac_per_s_total": u["mac_per_second"] * K, "kv_gbps_each": u["kv_words_per_second"] / 1e9, "kv_capacity_bytes_each": u["kv_capacity_words"], "hub_gbps_each": u["link_bandwidth_gbps"], "buffer_bytes_each": u.get("buffer_bytes", ""),
           "active_units_per_layer": K if att.get("split") == "head" else 1, "attention_algorithm": alg.get("algorithm", ""), "n_query_tiles": alg.get("n_tiles", ""), "workspace_bytes_per_unit": alg.get("workspace_bytes", ""), "kv_reads_per_layer": alg.get("kv_reads_per_layer", ""), "extra_memory_words_per_layer": alg.get("extra_memory_words", ""),
           "kv_fits": all(k["fits"] for k in att["kv_capacity"]) if att.get("kv_capacity") else "", "kv_bytes_per_unit": att["kv_capacity"][0]["kv_bytes"] if att.get("kv_capacity") else "",
           "R_s": R, "R_cim_compute_s": lb["cim_compute_s"] * L, "R_cim_write_s": lb.get("cim_write_s", 0) * L, "R_digital_elementwise_s": lb["digital_elementwise_s"] * L, "R_unit_compute_s": lb["unit_compute_s"] * L, "R_unit_kv_s": lb["unit_kv_s"] * L,
           "default": "sequential", "H_default_s": Hd, "T_default_s": lib["sequential"]["T_s"], "best_baseline": st, "best_baseline_class": "random" if st.startswith("random_s") else "named rule", "strongest_named_rule": rec["strongest_rule"], "strongest_random": rec["strongest_random"],
           "H_best_baseline_s": Hb, "T_best_baseline_s": lib[st]["T_s"], "search_representative": rep, "H_search_s": Hs, "T_search_s": runs[rep]["T_s"], "eta_comm": 1 - Hs / Hb, "r0": Hb / lib[st]["T_s"], "G": 1 - runs[rep]["T_s"] / lib[st]["T_s"],
           "G_seed_median": rec["search"]["gain_median_pct"] / 100, "G_seed_min": rec["search"]["gain_min_pct"] / 100, "G_seed_max": rec["search"]["gain_max_pct"] / 100, "comm_speedup_default_over_best": Hd / Hb, "comm_speedup_default_over_search": Hd / Hs,
           "B_eq_gbps": V.solve_B(lib[st], Hs, Ch) or "", "hub_words_sum_best": lib[st].get("hub_words_sum", ""), "hub_words_sum_search": runs[rep].get("hub_words_sum", ""), "payload_words_total": lib[st].get("words", ""), "E_best_J": lib[st]["E_J"], "E_search_J": runs[rep]["E_J"],
           "record": V.record_path(unit)}
    return row


def flow_structure(rec):
    """Flows / hand-offs / payload per stage type of a record (layout independent)."""
    W = C.workload_from_record(rec); phase = rec["spec"]["phase"]
    from scripts import search_space as ss
    pi = ss.Pi.from_json(rec["search"]["runs"][rec["search"]["headline"]]["best_pi"])   # a stored legal layout; the flow structure is layout independent
    hs = cli.handoff_flows(W, pi, phase)
    per = {}
    L = rec["spec"]["L"]
    for into, fl in hs:
        st = C.STAGE.get(into.rsplit("@L", 1)[0], into)
        d = per.setdefault(st, {"n_handoffs": 0, "n_flows": 0, "payload_words": 0.0, "producers": set(), "consumers": set(), "widths": set()})
        d["n_handoffs"] += 1; d["n_flows"] += len(fl); d["payload_words"] += sum(f["volume"] * f["width"] for f in fl)
        d["producers"].add(len({f["nodes"][0] for f in fl})); d["consumers"].add(len({f["nodes"][1] for f in fl})); d["widths"].update({x["width"] for x in fl})
    out = {"n_handoffs_total": sum(d["n_handoffs"] for d in per.values()), "n_flows_total": sum(d["n_flows"] for d in per.values()), "payload_words_total": sum(d["payload_words"] for d in per.values())}
    for st, d in per.items():
        tag = st.replace("->", "_to_").replace(" ", "")
        out[f"flows_per_handoff_{tag}"] = d["n_flows"] / d["n_handoffs"]; out[f"payload_words_per_handoff_{tag}"] = d["payload_words"] / d["n_handoffs"]; out[f"fanout_{tag}"] = f"{sorted(d['producers'])}x{sorted(d['consumers'])}"; out[f"width_bytes_{tag}"] = ";".join(map(str, sorted(d["widths"])))
    return out


def main():
    os.makedirs(V.V7, exist_ok=True)
    cap, cap_common, org, ws, length = [], [], [], [], []
    # (a) capacity: natural grid
    for model in ("opt6.7b", "gemma7b", "opt13b"):
        for macros, units in ((4, ["e10_cap_m4"]), (8, ["e9_ref"]), (8, ["e9_confirm"]), (16, ["e10_cap_m16"]), (16, ["e10_confirm_cap"]), (32, ["e10_cap_m32"])):
            cid = f"{model}_prefill512_colrow_sq_mesh_xy_k2_b0.4{'' if macros == 8 else f'_m{macros}'}_offcenterK1"
            rec = None
            for u in units:
                try:
                    rec = C.find_record(u, cid); unit = u; break
                except (KeyError, FileNotFoundError):
                    pass
            if rec is None or rec["status"] != "done":
                cap.append({"unit": units[0], "config_id": cid, "model": model, "die_macros": macros, "status": "blocked_missing_account" if (model == "opt13b" and macros == 4) else ("not available" if rec is None else rec["status"]), "grid_kind": "natural"}); continue
            row = base_row(unit, rec); row["status"] = "done"; row["grid_kind"] = "natural"; row["protocol_group"] = "confirmation" if rec["n_random"] == 500 else "exploration"
            print("  flows for", cid, unit, flush=True); row.update(flow_structure(rec)); cap.append(row)
    # (a) common grid 36x36 (Gemma)
    for macros, unit, cid in ((8, "e9_confirm", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"), (8, "e9_ref", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"), (16, "e10_cap_common_m16", "gemma7b_prefill512_colrow_36x36_mesh_xy_k2_b0.4_m16_offcenterK1"), (32, "e10_cap_common_m32", "gemma7b_prefill512_colrow_36x36_mesh_xy_k2_b0.4_m32_offcenterK1"),
                              (16, "e10_cap_m16", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m16_offcenterK1"), (32, "e10_cap_m32", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m32_offcenterK1")):
        rec = C.find_record(unit, cid); row = base_row(unit, rec); row["status"] = "done"; row["grid_kind"] = "common 36x36" if "36x36" in cid or macros == 8 else "natural"; row["protocol_group"] = "confirmation" if rec["n_random"] == 500 else "exploration"; cap_common.append(row)
    # (b) resource organisation
    for model in ("gemma7b", "opt13b", "opt6.7b"):
        for ph in ("prefill", "decode"):
            for unit, tag in (("e9_hub", "K1"), ("e9_hub", "K2"), ("e9_hub", "K2T"), ("e9_hub", "K4"), ("e9_hub", "K4T"), ("e9_head", "K1T"), ("e9_head", "K2T"), ("e9_head", "K2TH"), ("e9_head", "K4T"), ("e9_head", "K4TH"), ("e10_head", "K4TH"), ("e9_confirm", "K1"), ("e10_confirm", "K4TH"), ("e10_confirm", "K4")):
                cid = f"{model}_{ph}512_colrow_sq_mesh_xy_k2_b0.4_offcenter{tag}"
                try:
                    rec = C.find_record(unit, cid)
                except (KeyError, FileNotFoundError):
                    continue
                if rec["status"] != "done":
                    continue
                row = base_row(unit, rec); row["organisation"] = {"K1": "K=1 central", "K1T": "K=1 (fixed-total = per-unit)", "K2": "K=2 per-unit layer groups", "K2T": "K=2 fixed-total layer groups", "K2TH": "K=2 fixed-total head groups", "K4": "K=4 per-unit layer groups", "K4T": "K=4 fixed-total layer groups", "K4TH": "K=4 fixed-total head groups"}[tag]
                row["protocol_group"] = "confirmation" if rec["n_random"] == 500 else "exploration"; org.append(row)
    # (c) workspace thresholds and length sweep
    for unit, cid in [("e10_ws", c) for c in ("gemma7b_prefill1024_colrow_sq_mesh_xy_k2_b0.4_offcenterK1T", "gemma7b_prefill1024_colrow_sq_mesh_xy_k2_b0.4_offcenterK4TH", "gemma7b_prefill2048_colrow_sq_mesh_xy_k2_b0.4_offcenterK1T", "gemma7b_prefill2048_colrow_sq_mesh_xy_k2_b0.4_offcenterK4TH",
                                              "gemma7b_decode1024_colrow_sq_mesh_xy_k2_b0.4_offcenterK1T", "gemma7b_decode1024_colrow_sq_mesh_xy_k2_b0.4_offcenterK4TH", "gemma7b_decode2048_colrow_sq_mesh_xy_k2_b0.4_offcenterK1T", "gemma7b_decode2048_colrow_sq_mesh_xy_k2_b0.4_offcenterK4TH")] + \
                     [("e9_head", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1T"), ("e9_head", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK4TH"), ("e9_head", "gemma7b_decode512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1T"), ("e9_head", "gemma7b_decode512_colrow_sq_mesh_xy_k2_b0.4_offcenterK4TH"),
                      ("e9_ref", "gemma7b_prefill1024_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"), ("e9_ref", "gemma7b_prefill2048_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"), ("e9_ref", "gemma7b_prefill4096_colrow_sq_mesh_xy_k2_b0.4_offcenterK1")]:
        try:
            rec = C.find_record(unit, cid)
        except (KeyError, FileNotFoundError):
            continue
        row = base_row(unit, rec); row["protocol_group"] = "confirmation" if rec["n_random"] == 500 else "exploration"
        att = rec["attention"]; u = att["unit"]; ulc = att.get("unit_layer_cost", {})
        row.update({"unit_kv_write_words_per_layer": ulc.get("kv_write_words", ""), "unit_kv_read_words_per_layer": ulc.get("kv_read_words", ""), "unit_macs_per_layer": ulc.get("macs", ""), "workspace_bytes_per_head": ulc.get("algorithm", {}).get("workspace_bytes_per_head", ""), "P_tile": ulc.get("algorithm", {}).get("P_tile", ""), "spill": ulc.get("algorithm", {}).get("spill", "")})
        ws.append(row)
    for model in ("gemma7b", "opt6.7b", "opt13b"):
        for ph in ("prefill", "decode"):
            for S in (128, 256, 512, 1024, 2048, 4096):
                cid = f"{model}_{ph}{S}_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"
                try:
                    rec = C.find_record("e9_ref", cid)
                except (KeyError, FileNotFoundError):
                    length.append({"unit": "e9_ref", "config_id": cid, "model": model, "phase": ph, "S": S, "status": "not available"}); continue
                if rec["status"] != "done":
                    length.append({"unit": "e9_ref", "config_id": cid, "model": model, "phase": ph, "S": S, "status": rec["status"], "reason": rec.get("reason", "")}); continue
                row = base_row("e9_ref", rec); row["status"] = "done"; row["protocol_group"] = "exploration"; row["length_semantics"] = "prefill: input length S; decode: cache length S, one new token"; length.append(row)
    V.write_csv("offload_capacity.csv", cap); V.write_csv("offload_capacity_common_grid.csv", cap_common); V.write_csv("resource_organization_comparison.csv", org); V.write_csv("workspace_thresholds.csv", ws); V.write_csv("workload_length_sweep.csv", length)
    for r in cap:
        if r.get("status") == "done":
            print(f"  cap {r['model']:8s} m{r['die_macros']:<3d} {r['protocol_group'][:4]} dies {r['n_cim_dies']:5d} {r['grid']:6s} eta {r['eta_comm']*100:5.1f} r0 {r['r0']*100:5.1f} G {r['G']*100:5.1f} | H best {r['H_best_baseline_s']*1e3:8.1f} search {r['H_search_s']*1e3:8.1f} ms | flows {r['n_flows_total']} handoffs {r['n_handoffs_total']}")
        else:
            print(f"  cap {r['model']:8s} m{r['die_macros']:<3d} {r['status']}")


if __name__ == "__main__":
    main()
