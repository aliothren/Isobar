"""Fig. 2 data (Isobar_next_tasks section 3.2): one traceable example of the
evaluation pipeline on the Gemma-7B reference configuration and its
representative search layout: operator shapes -> CiMLoop account -> die
tiling -> seats -> flows -> physical routes -> resource loads -> stage
service / propagation -> R, H, T.

    python3 scripts/v7_fig2_pipeline.py
      -> analysis/v7/pipeline_example.json, example_flows.csv, example_resource_loads.csv
"""
import hashlib
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v7_common as V                      # noqa: E402
from scripts import v6_common as C                      # noqa: E402
from scripts import cimsim_cli as cli                   # noqa: E402
from scripts import search_eval as se                   # noqa: E402
from scripts import search_space as ss                  # noqa: E402

LAYER = 0


def sha(path_or_text, is_text=False):
    h = hashlib.sha256()
    h.update(path_or_text.encode() if is_text else open(path_or_text, "rb").read())
    return h.hexdigest()[:16]


def main():
    rec = C.find_record(*V.GEMMA_REF); spec = rec["spec"]; phase = spec["phase"]; bw = float(spec["bw"]); kappa = float(spec["kappa"])
    W = C.workload_from_record(rec)
    rep = rec["search"]["headline"]; pi = ss.Pi.from_json(rec["search"]["runs"][rep]["best_pi"])
    acc = json.load(open(spec["account_path"]))
    gx, gy = rec["grid"]; xy = lambda n: (n % gx, n // gx)
    unit = W.offload.unit; Ch = unit["link_bandwidth_gbps"] * 1e9; hubs = set(W.hub_nodes())
    # 1. operators and account
    ops = []
    for o in acc["phases"][phase]:
        ops.append({"name": o["name"], "kind": o["kind"], "P_rows": o["P"], "C_in": o["C"], "M_out": o["M"], "N": o["N"], "dies": o["dies"], "compute_s_per_layer": o["compute_s"], "write_s_per_layer": o["write_s"], "energy_J_per_layer": o["energy_J"],
                    "die_flow_words": o.get("die_flow_words"), "cycle_s": o["cycle_s"], "mapper": acc["derivation"]})
    chain = [{k: (v if not isinstance(v, tuple) else list(v)) for k, v in e.items()} for e in W.chain_entries(phase)]
    # 2. seats of layer 0
    names = [f"{e['name']}@L{LAYER}" for e in chain]
    seats = {n: se.seats_of(W, pi, n) for n in names}
    # 3. flows, routes, loads of the hand-offs INTO layer 0's entries and the one into the next layer's qkv
    hs = [(into, fl) for into, fl in cli.handoff_flows(W, pi, phase) if into.endswith(f"@L{LAYER}") or into == f"qkv_proj@L{LAYER + 1}"]
    sc, bs = C.evaluate(W, pi, phase, bw); bsd = {b["into"]: b for b in bs}
    flows_rows, load_rows, stages = [], [], []
    for into, fl in hs:
        raw = se.resource_loads(fl, W.die_ic, ports=True, kappa=1.0)
        res = []
        for key, words in raw.items():
            if key[0] == "port":
                node = key[1]; kind = "hub port" if node in hubs else "die port"; cap = Ch if node in hubs else kappa * bw * 1e9
                rid = f"{kind}:{node}:{key[2]}"; direction = key[2]; node_xy = xy(node)
            else:
                kind = "mesh link"; cap = bw * 1e9; rid = key[0]; direction = key[1]; node_xy = ""
            res.append({"into": into, "resource_id": rid, "resource_kind": kind, "direction": direction, "node_xy": str(node_xy), "payload_words": words, "payload_bytes": words, "capacity_words_per_s": cap, "service_s": words / cap})
        tmax = max(r["service_s"] for r in res)
        for r in res:
            r["is_stage_maximum"] = abs(r["service_s"] - tmax) < 1e-15
        res.sort(key=lambda r: -r["service_s"])
        load_rows += res
        prop = bsd[into]["max_hops"] * se.NS_PER_HOP_D2D * 1e-9
        stages.append({"into": into, "stage": C.STAGE.get(into.rsplit("@L", 1)[0], ""), "n_flows": len(fl), "payload_words": sum(f["volume"] * f["width"] for f in fl), "n_resources_loaded": len(res), "max_service_s": tmax, "max_resource": res[0]["resource_id"], "max_resource_kind": res[0]["resource_kind"],
                       "propagation_s": prop, "max_hops": bsd[into]["max_hops"], "stage_H_s": tmax + prop, "record_link_words": bsd[into]["link_words"], "record_dport_words_over_kappa": bsd[into]["dport_words"], "record_hub_words": bsd[into]["hub_words"],
                       "check_max_equals_record": abs(tmax - max(bsd[into]["link_words"] / (bw * 1e9), bsd[into]["dport_words"] / (bw * 1e9), bsd[into]["hub_words"] / Ch)) < 1e-12})
        for i, f in enumerate(fl):
            a, b = f["nodes"]; path = W.die_ic.path_directed(a, b)
            flows_rows.append({"into": into, "flow_id": f"{into}#{i}", "src": f["src"], "dst": f["dst"], "src_slot": a, "dst_slot": b, "src_xy": str(xy(a)), "dst_xy": str(xy(b)), "src_is_unit": a in hubs, "dst_is_unit": b in hubs,
                               "volume_elements": f["volume"], "width_bytes": f["width"], "payload_words": f["volume"] * f["width"], "hops": W.die_ic.hops(a, b), "route_xy": " > ".join(f"{r}{t}" for r, t in path), "level": f["level"]})
    L = W.cfg.n_layers; lb = rec["attention"]["layer_breakdown_s"]
    ex = {"config_id": rec["config_id"], "protocol_id": V.protocol_id(rec), "record": V.record_path(V.GEMMA_REF[0]), "layout": rep, "layout_sha256_16": sha(rec["search"]["runs"][rep]["best_pi"], True), "account": os.path.relpath(spec["account_path"], WS), "account_sha256_16": sha(spec["account_path"]),
          "phase": phase, "S": spec["S"], "layer_shown": LAYER, "grid": f"{gx}x{gy}", "n_cim_dies": rec["n_dies"], "empty_slots": rec["empty_slots"], "unit_slot": sorted(hubs), "unit_xy": [xy(h) for h in sorted(hubs)],
          "model": {"name": acc["config"]["name"], **{k: acc["config"][k] for k in ("d_model", "n_heads", "n_kv_heads", "head_dim", "d_ff", "n_layers", "ffn_gated", "activation")}, "scope": acc["scope"]},
          "cim_fabric": {"die_macros": spec.get("die_macros", 8), "macro_mesh": acc["fabric"]["macro_mesh"], "core_mesh": acc["fabric"]["core_mesh"], "crossbar_mesh": acc["fabric"]["crossbar_mesh"], "device": acc["fabric"]["device"], "ref_words_per_cycle": acc["ref_words_per_cycle"]},
          "operators_account": ops, "chain_entries": chain, "tiling_id": rec["provenance"]["tiling_id"], "seats_layer": {n: s for n, s in seats.items()}, "seats_xy": {n: [xy(x) for x in s] for n, s in seats.items()},
          "resources": {"mesh link": f"{bw} GB/s per direction (B_mesh)", "die port": f"{kappa} x B_mesh per direction (kappa)", "hub port": f"{unit['link_bandwidth_gbps']} GB/s per direction (C_hub, the unit's interface)", "propagation": f"{se.NS_PER_HOP_D2D} ns per hop (max hops of the hand-off)"},
          "digital_unit": {k: unit[k] for k in ("mac_per_second", "kv_words_per_second", "kv_capacity_words", "link_bandwidth_gbps", "buffer_bytes", "pj_per_mac", "kv_pj_per_word_read", "kv_pj_per_word_write", "link_pj_per_word")}, "attention": rec["attention"]["unit_layer_cost"],
          "stages_layer": stages,
          "R_terms": {"per_layer_s": lb, "n_layers": L, "N_cim_compute_s": lb["cim_compute_s"] * L, "F_fixed_s": (lb["digital_elementwise_s"] + lb["unit_compute_s"] + lb["unit_kv_s"] + lb["cim_write_s"]) * L, "R_s": rec["N_s"] + rec["F_s"], "check_record_R": abs(rec["N_s"] + rec["F_s"] - sc.per_phase[phase]["decomp"]["layers_s"]) < 1e-9},
          "H": {"H_service_s": sc.per_phase[phase]["decomp"]["d2d_serial_s"], "P_s": sc.per_phase[phase]["decomp"]["propagation_s"], "H_full_s": sc.per_phase[phase]["decomp"]["d2d_serial_s"] + sc.per_phase[phase]["decomp"]["propagation_s"], "n_handoffs": len(bs), "layer_0_handoffs_H_s": sum(s["stage_H_s"] for s in stages)},
          "T": {"T_s": sc.t_opt_s, "recorded_T_s": rec["search"]["runs"][rep]["T_s"], "reproduces_record": abs(sc.t_opt_s - rec["search"]["runs"][rep]["T_s"]) < 1e-9, "E_J": sc.e_J},
          "billing_paths": {"CIM static operators": "CiMLoop account per operator (compute_s, write_s, energy_J) x layers -> R", "digital element-wise (norm, activation, residual)": "DigitalUnit lanes x clock, Horowitz-class pJ per add / mul / lut at 16 bit -> R (digital_elementwise_s)",
                            "attention on the unit": "MAC-equivalent ops / rate + K/V words / K/V bandwidth (+ spill or re-read per the algorithm) -> R (unit_compute_s, unit_kv_s)", "K/V access": "the unit's K/V memory: written once per layer (new tokens), read once per layer (context) or per query tile; never on the mesh",
                            "CIM -> unit hand-off": "flows from the qkv dies to the unit node: mesh links at B, source die injection ports at kappa B, the unit's ejection port at C_hub", "unit -> CIM hand-off": "the unit's injection port at C_hub, mesh links, the out_proj dies' ejection ports at kappa B",
                            "CIM -> CIM hand-off": "mesh links at B and die ports at kappa B; row-split consumers receive only their slice; partial sums travel at 2 B per element (width)"},
          "code_version": V.code_version()}
    V.write_json("pipeline_example.json", ex); V.write_csv("example_flows.csv", flows_rows); V.write_csv("example_resource_loads.csv", load_rows)
    for s in stages:
        print(f"  {s['into']:18s} {s['stage']:16s} flows {s['n_flows']:3d} words {s['payload_words']:.3e} max {s['max_resource_kind']:9s} {s['max_service_s']*1e3:7.3f} ms + prop {s['propagation_s']*1e6:.2f} us  check {s['check_max_equals_record']}")
    print("T", sc.t_opt_s, "record", rec["search"]["runs"][rep]["T_s"])


if __name__ == "__main__":
    main()
