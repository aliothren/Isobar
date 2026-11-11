"""Table I data: the machine-readable evaluation setup (models and their
deployments, CIM die, interconnect, digital unit, protocols, metrics,
energy coefficients) and the parameter provenance table, read from the
records, accounts, fabric and code constants.

    python3 scripts/export_table1_setup.py
      -> results/exports/evaluation_setup.json, parameter_provenance.csv
"""
import dataclasses
import hashlib
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import experiment as v3                    # noqa: E402
from scripts import export_common as V                  # noqa: E402
from scripts import fabric as F                         # noqa: E402
from scripts import llm_workload as lw                  # noqa: E402
from scripts import records as C                        # noqa: E402
from scripts import search_eval as se                   # noqa: E402

REFS = [(m, "reference", f"{m}_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1") for m in ("opt1.3b", "opt6.7b", "gemma7b", "opt13b")]


def protocols():
    common = {"t0_norm": v3.T0_NORM, "alpha": v3.ALPHA, "budget": "max(1200, ceil(1200 n / 544)) steps, n = movable dies",
              "starts": "strongest named rule, strongest random of the pool, random seed 0",
              "statistic": "per seed the best of the starts; median and min/max over seeds; the representative is the median seed's best run"}
    return {"confirmation": {**v3.CONFIRMATION, **common}, "exploration": {**v3.EXPLORATION, **common}}


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def main():
    fab = F.default(); dev = dataclasses.asdict(fab.device); dig = dataclasses.asdict(fab.digital)
    models = {}
    for tag, unit, cid in REFS:
        rec = C.find_record(unit, cid); s = rec["spec"]; acc = json.load(open(s["account_path"])); cfg = acc["config"]; att = rec["attention"]; gx, gy = rec["grid"]
        models[tag] = {"config_id": cid, "protocol_id": V.protocol_id(rec), "name": cfg.get("name", tag), "d_model": cfg["d_model"], "n_layers": s["L"], "n_heads": cfg["n_heads"], "n_kv_heads": cfg.get("n_kv_heads", cfg["n_heads"]), "head_dim": cfg.get("head_dim", cfg["d_model"] // cfg["n_heads"]), "d_ff": cfg["d_ff"], "ffn_gated": cfg.get("ffn_gated", False), "activation": cfg.get("activation", ""), "vocab": cfg.get("vocab", ""),
                       "model_revision": rec["provenance"].get("model_revision", acc.get("model_revision", "")), "scope": rec["provenance"].get("scope", acc.get("scope", "")), "account": os.path.relpath(s["account_path"], WS), "account_sha256_16": sha(s["account_path"]), "account_derivation": acc.get("derivation", ""),
                       "tiling_id": rec["provenance"].get("tiling_id", ""), "dies_per_layer": rec["dies_per_layer"], "n_cim_dies": rec["n_dies"], "grid": f"{gx}x{gy}", "empty_slots": rec["empty_slots"], "unit_slots": att["hubs"], "unit_xy": [(h % gx, h // gx) for h in att["hubs"]], "phase": s["phase"], "S": s["S"], "batch": 1,
                       "operators_prefill": [{k: o.get(k, "") for k in ("name", "kind", "dies", "P", "C", "M", "compute_s", "write_s", "energy_J")} for o in acc["phases"]["prefill"]],
                       "static_weight_elements_per_layer": sum(o.get("C", 0) * o.get("M", 0) for o in acc["phases"]["prefill"] if o.get("kind") == "static"), "kv_bytes_per_unit": att["kv_capacity"][0]["kv_bytes"] if att.get("kv_capacity") else "", "attention_algorithm": att.get("unit_layer_cost", {}).get("algorithm", {})}
    g = C.find_record("reference", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"); gacc = json.load(open(g["spec"]["account_path"]))
    unit = g["attention"]["unit"]
    prot = protocols()
    setup = {"models": models,
             "cim": {"die": f"{g['spec'].get('die_macros', 8)} macros per die (reference); capacity variants 4 / 16 / 32 macros per die (models/fabric/variants)", "macro": "32 crossbars of 256 x 256 cells (core mesh 2x2 x crossbar mesh 4x2), NeuRRAM-class RRAM macro calibrated in CiMLoop (wan_nature_2022)",
                     "account_fabric": gacc["fabric"], "device": dev, "row_rate": {"t_row_s": fab.device.cycle_seconds * fab.device.input_slices_per_mvm, "input_slices_per_mvm": fab.device.input_slices_per_mvm, "note": "signed 8-bit inputs encoded in 7 bit slices; one input row through the resident array stack per 10.14 us"},
                     "words": "8-bit activations (1 byte per word); partial sums of row-split consumers at 2 bytes per element (flow width 2)", "weights": "static, resident; the CiMLoop account gives per-operator compute, write and energy at the legal decomposition (mapper run per (model, S))",
                     "tiling": "colrow: qkv_proj / out_proj / ffn1 column-split over output columns (M), ffn2 row-split over input rows (C, partial sums); row-split consumers receive only their slice"},
             "interconnect": {"topology": "2-D mesh of die slots, XY routing, one slot per CIM die, the digital unit(s) in reserved slots", "B_mesh_gbps_per_direction": 0.4, "kappa_port_ratio": 2.0, "die_port_capacity": "kappa x B_mesh per direction (one injection + one ejection port per die)",
                              "propagation_ns_per_hop": se.NS_PER_HOP_D2D, "link_energy_pj_per_word": se.PJ_D2D, "link_energy_rule": "PJ_D2D per word flat + PJ_D2D per word per surplus hop beyond the reference hop", "evaluated_tiers_gbps": [0.4, 12.5], "grids": {m: models[m]["grid"] for m in models}},
             "digital_unit": {"reference": {k: unit[k] for k in ("mac_per_second", "pj_per_mac", "kv_words_per_second", "kv_capacity_words", "link_bandwidth_gbps", "buffer_bytes", "kv_pj_per_word_read", "kv_pj_per_word_write", "link_pj_per_word", "score_bytes", "prob_bytes", "algorithm")},
                              "utilisation": 1.0, "op_counting": "MAC-equivalent operations: QK^T and AV MACs (2 P ctx H dh) plus softmax element operations (4 per score: 2 adds, 1 mul, 1 lookup); rate and energy coefficient apply per MAC-equivalent op",
                              "energy_coefficient": "1 pJ per MAC-equivalent operation (digital compute subsystem: arithmetic, buffers, control), applied to every MAC and softmax element operation; source: an accelerator-level 2 TOPS/W (4 TOPS INT8 at 2 W) = 0.5 pJ per op at 2 ops per MAC",
                              "K_units": {"grouping": "layer groups (contiguous layers -> unit) or head groups (complete head groups of every layer -> unit, all K active per layer)", "fixed_total": "rate, K/V bandwidth, K/V capacity, hub interface and working buffer divided by K per unit", "fixed_per_unit": "every unit keeps the reference values (K x total)", "positions": "center / edge / corner reserved slots"},
                              "kv": "K/V cache in the unit's memory: 1 byte per element; written once per layer per step (new tokens), read once per layer (materialized) or once per query tile (tiled); capacity check includes the algorithm's workspace"},
             "digital_elementwise": {**dig, "note": "norm / activation / residual element-wise work of the block at 16-bit intermediates; enters R and energy, never the mesh"},
             "energy_coefficients": {"cim": "CiMLoop per-operator energy (account energy_J per layer)", "digital_elementwise": f"pJ add {dig['pj_add']}, mul {dig['pj_mul']}, lut {dig['pj_lut']} (Horowitz ISSCC 2014 class) + GLB {lw.GLB_PJ_PER_WORD_REF} pJ per word", "unit_compute": "1 pJ per MAC-equivalent op", "kv": "50 pJ per byte read / write (LPDDR4 class)", "interconnect": f"{se.PJ_D2D} pJ per word flat + {se.PJ_D2D} pJ per word per surplus hop (GRS band midpoint)"},
             "protocols": {**prot, "budget_steps": "max(1200, ceil(1200 n / 544)), n = movable dies", "seed_rule": "SA seed = 1000003 s + start index", "objectives": {"t_norm": "T / T_base (exploration)", "h_norm": "(T - R) / (T_base - R) = H / H_base (confirmation)"}, "representative": "median seed's best run over the three starts",
                           "baseline_pool": "named rules sequential, snake, least_manhattan, clustered, nmap_greedy, heaviest_first (when constructible) + random fills (100 exploration / 500 confirmation); best baseline = strongest of rules and pool"},
             "metrics": {"T": "R + H", "R": "N / s + F: CIM compute (scales with device rate) + digital element-wise + unit attention compute + K/V time (fixed)", "H_full": "sum_j [P_j + max_r V_{j,r} / C_r] over hand-offs (links at B, die ports at kappa B, hub ports at C_hub)",
                         "eta_comm": "1 - H_search / H_best_baseline", "r0": "H_best_baseline / T_best_baseline", "G": "1 - T_search / T_best_baseline = eta_comm r0", "comm_speedup": "H_default / H_candidate", "B_eq": "mesh bandwidth at which the fixed best baseline's H equals the search layout's H at B = 0.4 (hub, K/V, unit, algorithm fixed; die ports at kappa B)"},
             "scope": "Transformer block (qkv, attention on the unit, out_proj, FFN, element-wise); embedding, LM head, final norm and position handling outside", "code_version": V.code_version()}
    V.write_json("evaluation_setup.json", setup)
    rows = []
    def add(block, p, val, unitn, loc, src, cls, note=""):
        rows.append({"block": block, "parameter": p, "value": val, "unit": unitn, "code_location": loc, "source": src, "evidence_class": cls, "note": note})
    add("CIM", "device row time", fab.device.cycle_seconds * fab.device.input_slices_per_mvm, "s per input row", "scripts/fabric.py Device (cycle_seconds x input_slices_per_mvm)", "CiMLoop calibration of the NeuRRAM-class macro (Wan et al., Nature 2022)", "calibrated model", "7 encoded input bit slices x 1.4486 us")
    add("CIM", "macro organisation", "2x2 cores x 4x2 crossbars of 256x256", "", "models/fabric/mlx300_multidie*.yaml; account fabric", "fabric declaration", "design", "")
    add("CIM", "macros per die", g["spec"].get("die_macros", 8), "macros", "spec die_macros; models/fabric/variants", "fabric declaration", "design", "capacity axis 4 / 8 / 16 / 32")
    add("CIM", "activation word", 1, "byte", "accounts (8-bit words)", "account convention", "design", "partial sums 2 bytes per element")
    add("CIM", "per-operator compute / write / energy", "account values", "", "results/accounts/*.json", "CiMLoop mapper run per (model, S)", "measured (mapper)", "legal decomposition per operator")
    add("interconnect", "B_mesh", 0.4, "GB/s per direction", "spec bw", "HERMES-class analog-chip link rate (3.2 Gbit/s per link, Le Gallo et al. 2023); 12.5 GB/s = one Simba GRS transceiver as the upper tier", "public specification", "")
    add("interconnect", "kappa", 2.0, "port / link rate", "spec kappa; search_eval.resource_loads", "model declaration", "design", "die port at kappa x the link rate")
    add("interconnect", "propagation", se.NS_PER_HOP_D2D, "ns per hop", "search_eval.NS_PER_HOP_D2D", "Simba NoP 20 ns per hop (MICRO'19 Tab 2)", "public specification", "")
    add("interconnect", "link energy", se.PJ_D2D, "pJ per word (flat and per surplus hop)", "search_eval.PJ_D2D", "GRS band midpoint 6.6-14 pJ/word (Zimmer et al., JSSC 2020)", "public (measured link class)", "")
    add("digital unit", "compute rate", unit["mac_per_second"], "MAC-equivalent op/s", "offload.REF_UNIT mac_per_second", "edge-NPU class: 4 TOPS INT8 (Google Edge TPU public figure) = 2 TMAC/s", "public specification (device class)", "utilisation 1; softmax element ops counted as MAC-equivalents")
    add("digital unit", "compute energy", unit["pj_per_mac"], "pJ per MAC-equivalent op", "offload.REF_UNIT pj_per_mac", "the same figure: 2 TOPS/W = 0.5 pJ per op = 1 pJ per MAC; subsystem-equivalent (arithmetic + buffers + control)", "public specification (accelerator level)", "applied to MACs and softmax element operations")
    add("digital unit", "K/V bandwidth", unit["kv_words_per_second"] / 1e9, "GB/s", "offload.REF_UNIT kv_words_per_second", "LPDDR4 class: two 32-bit channels at 3200 MT/s = 25.6 GB/s raw", "public specification (memory class)", "read and write share the rate")
    add("digital unit", "K/V capacity", unit["kv_capacity_words"], "bytes (decimal GB)", "offload.REF_UNIT kv_capacity_words", "one LPDDR4 package, 2 GB", "public specification (package class)", "capacity check includes the workspace")
    add("digital unit", "hub interface", unit["link_bandwidth_gbps"], "GB/s per direction", "offload.REF_UNIT link_bandwidth_gbps", "one Simba GRS transceiver macro: 4 lanes x 25 Gb/s (Zimmer et al., JSSC 2020)", "public specification (measured link macro)", "Rx and Tx independent")
    add("digital unit", "working buffer", unit.get("buffer_bytes", ""), "bytes", "offload.REF_UNIT buffer_bytes", "edge-NPU class on-chip SRAM 8 MB (Edge TPU public figure)", "public specification (device class)", "scores 2 B, probabilities 1 B; materialized vs tiled chosen per workpoint")
    add("digital unit", "K/V energy", unit["kv_pj_per_word_read"], "pJ per byte", "offload.REF_UNIT kv_pj_per_word_*", "LPDDR4-class access energy", "public (memory class)", "")
    add("digital unit", "hub link energy", unit["link_pj_per_word"], "pJ per word", "offload.REF_UNIT link_pj_per_word", "as the die links", "public (measured link class)", "")
    add("digital element-wise", "lanes x clock", f"{dig['lanes']} x {dig['clock_hz']:.0e}", "", "fabric.DigitalUnit", "generic example values", "design", "sized to the array output rate")
    add("digital element-wise", "pJ add / mul / lut", f"{dig['pj_add']} / {dig['pj_mul']} / {dig['pj_lut']}", "pJ at 16 bit", "fabric.DigitalUnit", "Horowitz ISSCC 2014 class", "public (technology class)", "")
    add("protocol", "exploration", "100 random fills, SA seeds 0-4, objective T / T_base", "", "scripts/experiment.py, scripts/run_experiments.py", "experiment.EXPLORATION", "protocol", "")
    add("protocol", "confirmation", "500 random fills, SA seeds 5-14, objective H / H_base", "", "scripts/experiment.py, scripts/run_experiments.py", "experiment.CONFIRMATION", "protocol", "")
    add("protocol", "SA schedule", f"t0 {v3.T0_NORM:.6f}, alpha {v3.ALPHA}, steps max(1200, ceil(1200 n / 544))", "", "experiment.T0_NORM / ALPHA / budget", "search protocol", "protocol", "")
    add("protocol", "starts", "strongest named rule, strongest random of the pool, random seed 0", "", "experiment.evaluate_config", "search protocol", "protocol", "seed = 1000003 s + start index")
    add("scope", "backbone", "Transformer block; embedding / LM head / final norm / positions outside", "", "accounts scope", "account scope field", "declaration", "")
    V.write_csv("parameter_provenance.csv", rows)
    print({m: (models[m]["n_cim_dies"], models[m]["grid"], models[m]["empty_slots"], models[m]["unit_xy"]) for m in models})


if __name__ == "__main__":
    main()
