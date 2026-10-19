"""Second batch (Isobar_next_tasks section 4): the small-model exports from
the e11_small / e11_small_cap / e11_small_len records (OPT-1.3B,
Qwen2.5-1.5B), with the OPT family scale series (1.3B / 6.7B / 13B
reference points) alongside: structure (accounts, tiling, flows, K/V),
comparison (default / strongest named / strongest random / best baseline /
search), seed statistics, stage breakdown of the actual pair, boundaries.

    python3 scripts/v7_small_models.py
      -> analysis/v7/small_model_manifest.csv, small_model_operator_accounts.csv, small_model_comparison.csv,
         small_model_seed_statistics.csv, small_model_stage_breakdown.csv, small_model_stage_delta.csv, small_model_layouts.json
"""
import json
import os
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v7_common as V                      # noqa: E402
from scripts import v6_common as C                      # noqa: E402
from scripts import v7_fig7_mechanisms as F7            # noqa: E402
from scripts import search_space as ss                  # noqa: E402
from scripts import v4_models as vm                     # noqa: E402

SOURCES = [("e11_small", "A: core (8 macros, K=1, prefill and decode 512, confirmation)"), ("e11_small_cap", "B: capacity (16 macros, K=1, prefill 512, confirmation)"), ("e11_small_len", "C: length (S 128 / 2048, exploration h_norm)"),
           ("e9_confirm", "OPT family scale series (reference points)")]
SMALL = ("opt1.3b", "qwen2.5-1.5b")


def Hf(r):
    return r["H_s"] + r["prop_s"]


def stage_tables(unit, cid, macros, names):
    """Stage rows of named layouts; records of a die variant run in a subprocess with the matching fabric (rule construction follows the die menu)."""
    import subprocess
    env = dict(os.environ)
    if macros != 8:
        env["CIMSIM_FABRIC"] = os.path.join(WS, "models", "fabric", "variants", f"mlx300_multidie_m{macros}.yaml")
    out = subprocess.run([sys.executable, os.path.join(WS, "scripts", "v7_stage_worker.py"), unit, cid, *names], env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def main():
    man, accts, comp, seeds, stages, deltas, layouts = [], [], [], [], [], [], {}
    for unit, batch in SOURCES:
        for rec in C.load_records(unit):
            model = rec["spec"]["model"]
            if unit == "e9_confirm" and (model not in ("opt6.7b", "opt13b") or rec["spec"]["phase"] != "prefill"):
                continue
            if unit != "e9_confirm" and model not in SMALL:
                continue
            s = rec["spec"]; cid = rec["config_id"]
            if rec["status"] != "done":
                man.append({"batch": batch, "unit": unit, "config_id": cid, "model": model, "status": rec["status"], "reason": rec.get("reason", "")}); continue
            row = F7.base_row(unit, rec); row["batch"] = batch; row["protocol_group"] = "confirmation" if rec["n_random"] == 500 else "exploration"
            cfg = vm.cfg_of(model); m = vm.MODELS[model]
            acc = json.load(open(s["account_path"]))
            static_elems = sum(o["C"] * o["M"] for o in acc["phases"]["prefill"] if o["kind"] == "static") * s["L"]
            band = rec.get("band", {}).get("rules", {})
            row.update({"nominal_params": m["notes"].split("Nominal")[-1][:60] if "Nominal" in m["notes"] else "", "mapped_block_weight_bytes": static_elems, "d_model": cfg.d_model, "n_heads": cfg.n_heads, "n_kv_heads": cfg.kv_heads, "head_dim": cfg.dh, "d_ff": cfg.d_ff, "n_layers": s["L"], "ffn_gated": cfg.ffn_gated, "activation": cfg.activation,
                        "model_revision": json.dumps(m["sources"][0]["url"]), "torch_dtype_official": ("float16" if model.startswith("opt") else "bfloat16"), "simulated_encoding": "8-bit activations, 2-byte partial sums, CiMLoop account weights", "account": os.path.relpath(s["account_path"], WS),
                        "rules_B_minus_gbps": band.get("B_minus", ""), "rules_B_plus_gbps": band.get("B_plus", ""), "rules_band_ratio": band.get("ratio", ""), "rules_no_finite": band.get("no_finite_boundary", ""), "rules_n": band.get("n", ""), "rule_failures": json.dumps(rec.get("rule_failures", {}))})
            print("  flows for", cid, flush=True)
            W = C.workload_from_record(rec); phase = s["phase"]; bw = float(s["bw"]); kappa = float(s["kappa"])
            row.update(F7.flow_structure(rec)); man.append(row)
            for o in acc["phases"][phase] or []:
                accts.append({"config_id": cid, "model": model, "phase": phase, "S": s["S"], "die_macros": s.get("die_macros", 8), "operator": o["name"], "kind": o["kind"], "P": o.get("P"), "C_in": o.get("C"), "M_out": o.get("M"), "N": o.get("N"), "resident_N": o.get("resident_N"), "dies": o["dies"],
                              "split": F7.tiling(rec["provenance"].get("tiling_id", "")).get(o["name"], ("", ""))[1], "compute_s": o["compute_s"], "write_s": o["write_s"], "energy_J": o["energy_J"], "die_flow_words": json.dumps(o.get("die_flow_words")), "weight_elements": (o.get("C", 0) or 0) * (o.get("M", 0) or 0) if o["kind"] == "static" else ""})
            lib = rec["candidates"]; runs = rec["search"]["runs"]; rep = rec["search"]["headline"]; st = rec["strongest"]; R = rec["N_s"] + rec["F_s"]; Ch = rec["attention"]["unit"]["link_bandwidth_gbps"] * 1e9
            Hd, Hb = Hf(lib["sequential"]), Hf(lib[st])
            for role, name in (("default", "sequential"), ("strongest named rule", rec["strongest_rule"]), ("strongest random", rec["strongest_random"]), ("best baseline", st), ("search representative", rep)):
                r = lib.get(name) or runs[name]; H = Hf(r)
                comp.append({"batch": batch, "unit": unit, "config_id": cid, "model": model, "phase": phase, "S": s["S"], "die_macros": s.get("die_macros", 8), "role": role, "layout": name, "statistic": "actual layout", "R_s": R, "H_full_s": H, "H_service_s": r["H_s"], "P_s": r["prop_s"], "T_s": r["T_s"], "E_J": r["E_J"],
                             "comm_speedup_H_default_over_H": Hd / H, "eta_vs_best_baseline": 1 - H / Hb, "G_vs_best_baseline": 1 - r["T_s"] / lib[st]["T_s"], "r0_best_baseline": Hb / lib[st]["T_s"], "B_eq_gbps": (V.solve_B(lib[st], H, Ch) or "") if role.startswith("search") else "", "protocol_id": V.protocol_id(rec)})
            bests = {}
            for n, r in runs.items():
                if r["sa_seed"] not in bests or r["T_s"] < runs[bests[r["sa_seed"]]]["T_s"]:
                    bests[r["sa_seed"]] = n
            for sd, n in sorted(bests.items()):
                r = runs[n]; H = Hf(r)
                seeds.append({"batch": batch, "unit": unit, "config_id": cid, "model": model, "phase": phase, "S": s["S"], "die_macros": s.get("die_macros", 8), "seed": sd, "best_run": n, "start": r["start"], "H_full_s": H, "T_s": r["T_s"], "comm_speedup_H_default_over_H": Hd / H, "eta_vs_best_baseline": 1 - H / Hb, "G_vs_best_baseline": 1 - r["T_s"] / lib[st]["T_s"], "is_representative": n == rep})
            # stage breakdown of the actual pair (small models only)
            if model in SMALL:
                res = stage_tables(unit, cid, s.get("die_macros", 8), [st, rep])
                layouts[cid] = {n: res[n]["pi"] for n in res}
                per = {}
                for n in res:
                    for r in res[n]["stages"]:
                        stages.append({"config_id": cid, "model": model, "layout": n, "role": "best baseline" if n == st else "search representative", **r})
                        per.setdefault(r["into"], {})[n] = r
                for into, d in per.items():
                    a, b = d[st], d[rep]
                    deltas.append({"config_id": cid, "model": model, "into": into, "layer": a["layer"], "stage": a["stage"], "H_baseline_s": a["service_s"] + a["propagation_s"], "H_representative_s": b["service_s"] + b["propagation_s"], "delta_s": (b["service_s"] + b["propagation_s"]) - (a["service_s"] + a["propagation_s"]), "binding_baseline": a["binding"], "binding_representative": b["binding"], "payload_words": a["payload_words"]})
    V.write_csv("small_model_manifest.csv", man); V.write_csv("small_model_operator_accounts.csv", accts); V.write_csv("small_model_comparison.csv", comp); V.write_csv("small_model_seed_statistics.csv", seeds)
    V.write_csv("small_model_stage_breakdown.csv", stages); V.write_csv("small_model_stage_delta.csv", deltas); V.write_json("small_model_layouts.json", layouts)
    for r in man:
        if r.get("status", "done") == "done":
            print(f"  {r['batch'][:2]} {r['model']:13s} {r['phase']:7s} S {r['S']:>4} m{r['die_macros']:<2} dies {r['n_cim_dies']:4d} {r['grid']:6s} | T best {r['T_best_baseline_s']*1e3:8.2f} search {r['T_search_s']*1e3:8.2f} ms | eta {r['eta_comm']*100:5.1f} r0 {r['r0']*100:5.1f} G {r['G']*100:5.1f} [{r['G_seed_min']*100:.1f},{r['G_seed_max']*100:.1f}] | H_def/H_best {r['comm_speedup_default_over_best']:.2f} | flows {r['n_flows_total']}")
        else:
            print("  ", r["config_id"], r["status"], r.get("reason", ""))


if __name__ == "__main__":
    main()
