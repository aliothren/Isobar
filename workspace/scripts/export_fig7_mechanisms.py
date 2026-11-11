"""Fig. 7 data, all under the exploration protocol. (a) CIM capacity: the
four models at 4 / 8 / 16 / 32 macros per die on their natural meshes,
with the flow structure of each point, and Gemma-7B at 16 / 32 macros on
its 8-macro mesh (36 x 36) as the control. (b) Resource organisation:
Gemma-7B prefill with the same total digital resource as one central
unit, four layer-group units or four head-group units. (d) Context
length: Gemma-7B prefill and decode at 128-4096 tokens. Panel (c) comes
from export_fig7_bandwidth.py.

    python3 scripts/export_fig7_mechanisms.py
      -> results/exports/offload_capacity.csv, offload_capacity_common_grid.csv,
         resource_organization_comparison.csv, workload_length_sweep.csv
"""
import os
import re
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import export_common as V                  # noqa: E402
from scripts import objective as ob                     # noqa: E402
from scripts import records as C                        # noqa: E402

OPS = ["qkv_proj", "attention", "out_proj", "ffn1", "ffn2"]
MODELS = ("opt1.3b", "opt6.7b", "gemma7b", "opt13b")
MACROS = (4, 8, 16, 32)
ORGANISATION = {"K1T": "K=1 central", "K4T": "K=4 fixed-total layer groups", "K4TH": "K=4 fixed-total head groups"}
LENGTHS = (128, 256, 512, 1024, 2048, 4096)


def cap_cid(model, macros, grid="sq"):
    return f"{model}_prefill512_colrow_{grid}_mesh_xy_k2_b0.4{'' if macros == 8 else f'_m{macros}'}_offcenterK1"


def protocol_group(rec):
    return "confirmation" if rec["n_random"] == 500 else "exploration"


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
    hs = ob.handoff_flows(W, pi, phase)
    per = {}
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
    os.makedirs(V.EXPORTS, exist_ok=True)
    cap, cap_common, org, length = [], [], [], []
    # (a) capacity on the natural mesh of each point, and Gemma on its 8-macro mesh
    for model in MODELS:
        for macros in MACROS:
            unit, cid = f"capacity_sweep_m{macros}", cap_cid(model, macros)
            try:
                rec = C.find_record(unit, cid)
            except (KeyError, FileNotFoundError):
                cap.append({"unit": unit, "config_id": cid, "model": model, "die_macros": macros, "status": "not available", "grid_kind": "natural"}); continue
            if rec["status"] != "done":
                cap.append({"unit": unit, "config_id": cid, "model": model, "die_macros": macros, "status": rec["status"], "grid_kind": "natural"}); continue
            row = base_row(unit, rec); row["status"] = "done"; row["grid_kind"] = "natural"; row["protocol_group"] = protocol_group(rec)
            print("  flows for", cid, flush=True); row.update(flow_structure(rec)); cap.append(row)
    for macros, grid in ((8, "sq"), (16, "36x36"), (32, "36x36")):
        unit = f"capacity_sweep_m{macros}"
        rec = C.find_record(unit, cap_cid("gemma7b", macros, grid))
        row = base_row(unit, rec); row["status"] = "done"; row["protocol_group"] = protocol_group(rec)
        row["grid_kind"] = "common 36x36" if tuple(rec["grid"]) == (36, 36) else "natural"; cap_common.append(row)
    # (b) resource organisation
    for tag, label in ORGANISATION.items():
        rec = C.find_record("organisation", f"gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenter{tag}")
        row = base_row("organisation", rec); row["organisation"] = label; row["protocol_group"] = protocol_group(rec); org.append(row)
    # (d) context length
    for ph in ("prefill", "decode"):
        for S in LENGTHS:
            cid = f"gemma7b_{ph}{S}_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"
            try:
                rec = C.find_record("context_length", cid)
            except (KeyError, FileNotFoundError):
                length.append({"unit": "context_length", "config_id": cid, "model": "gemma7b", "phase": ph, "S": S, "status": "not available"}); continue
            if rec["status"] != "done":
                length.append({"unit": "context_length", "config_id": cid, "model": "gemma7b", "phase": ph, "S": S, "status": rec["status"], "reason": rec.get("reason", "")}); continue
            row = base_row("context_length", rec); row["status"] = "done"; row["protocol_group"] = protocol_group(rec)
            row["length_semantics"] = "prefill: input length S; decode: cache length S, one new token"; length.append(row)
    V.write_csv("offload_capacity.csv", cap); V.write_csv("offload_capacity_common_grid.csv", cap_common)
    V.write_csv("resource_organization_comparison.csv", org); V.write_csv("workload_length_sweep.csv", length)
    for r in cap:
        if r.get("status") == "done":
            print(f"  cap {r['model']:8s} m{r['die_macros']:<3d} dies {r['n_cim_dies']:5d} {r['grid']:6s} eta {r['eta_comm']*100:5.1f} r0 {r['r0']*100:5.1f} G {r['G']*100:5.1f} | H best {r['H_best_baseline_s']*1e3:8.1f} search {r['H_search_s']*1e3:8.1f} ms | flows {r['n_flows_total']} handoffs {r['n_handoffs_total']}")
        else:
            print(f"  cap {r['model']:8s} m{r['die_macros']:<3d} {r['status']}")
    for r in org:
        print(f"  org {r['organisation']:30s} eta {r['eta_comm']*100:5.1f} G {r['G']*100:5.1f}")


if __name__ == "__main__":
    main()
