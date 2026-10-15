"""Next-round item 2 (E7): the three real models deployed on the platform
with the V3 protocol and the sweep driver's record format. Host-runnable
once the measured accounts exist (analysis/v4/accounts/<model>_S{S}.json).

Units:
  e7_ref    : each model at the reference workpoint (prefill 512, kappa 2,
              XY, 0.4 GB/s) on the near-square and the 2:1 grid;
  e7_len    : near-square grid, prefill and decode at S 128 / 256 / 512 /
              1024 / 2048 / 4096 (lengths above the model's positions or
              the attention die's capacity are recorded as such);
  e7_struct : near-square grid, prefill 512, kappa 1 / 2 / 4 x XY / YX.
Every record carries the cost grid (10 rates x 14 bandwidths) and the
provenance fields of the mechanism record (model_revision, tiling_id,
account_id, protocol_id).

    python3 scripts/v4_deploy.py --unit e7_ref [--n-random 100] [--seeds 0,1,2,3,4]
    python3 scripts/v4_deploy.py --unit e7_lencap      # S above the standard attention die, with the assumed larger attention die
    python3 scripts/v4_deploy.py --unit e7_geom        # aspect 2 / 4 x XY / YX x kappa 1 / 2 / 4
    CIMSIM_FABRIC=models/fabric/variants/mlx300_multidie_m16.yaml python3 scripts/v4_deploy.py --unit e8_cap --macros 16
"""
import argparse
import glob
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v3_sweep as v3          # noqa: E402
from scripts import v4_models as vm         # noqa: E402

V4 = os.path.join(WS, "analysis", "v4")
ACC = os.path.join(V4, "accounts")
REAL = ("opt6.7b", "gemma7b", "opt13b")


def offload_tag(o):
    if not o:
        return ""
    u = o.get("unit") or {}
    ov = "".join(f"_{k[:3]}{v:g}" for k, v in sorted(u.items()))
    return f"_off{o.get('position', 'center')}K{o.get('K', 1)}{'T' if o.get('resource_mode') == 'total' else ''}{'H' if o.get('split') == 'head' else ''}{ov}"


def spec_for(model, S=512, phase="prefill", aspect=1.0, grid=None, topology="mesh", routing="xy", kappa=2.0, bw=0.4, tiling="colrow", account_suffix="", macros=None, offload=None):
    cfg = vm.cfg_of(model)
    gtag = f"{grid[0]}x{grid[1]}" if grid else ("sq" if aspect == 1.0 else f"a{aspect:g}")
    cid = f"{model}_{phase}{S}_{tiling}_{gtag}_{topology}_{routing}_k{kappa:g}_b{bw:g}{account_suffix}{offload_tag(offload)}"
    if model == "ref2p7b":            # the frozen reference's accounts (block-level: any depth)
        acc = v3.REF_ACCOUNT if S == 512 else os.path.join(v3.V3, "accounts", f"d2560_dh80_ff10240_S{S}.json")
    else:
        acc = os.path.join(ACC, f"{model}_S{S}{account_suffix}.json")
    return {"model": model, "d": cfg.d_model, "dh": cfg.dh, "d_ff": cfg.d_ff, "L": cfg.n_layers, "S": S, "phase": phase, "tiling": tiling,
            "grid": grid, "aspect": aspect, "topology": topology, "routing": routing, "kappa": float(kappa), "bw": float(bw),
            "model_tag": model, "config_id": cid, "account_path": acc,
            "account_suffix": account_suffix, "die_macros": macros or 8, "max_positions": vm.MODELS[model]["max_positions"],
            "offload": offload}


OFF = {"position": "center", "K": 1, "resource_mode": "per_unit"}      # the reference offload configuration (DR-9 values, one central unit)


def with_unit(**kw):
    return {**OFF, "unit": kw}


# long lengths under an assumed larger attention die (the smallest variant that holds K and V); the static operators stay on the standard die
LENCAP = [("opt6.7b", 2048, 16), ("gemma7b", 2048, 16), ("gemma7b", 4096, 32), ("opt13b", 1024, 16), ("opt13b", 2048, 24)]
MACROS = (2, 4, 6, 8, 12, 16, 24, 32)


def unit_specs(unit, macros=None):
    if unit == "e7_ref":
        return [spec_for(m, aspect=a) for m in REAL for a in (1.0, 2.0)]
    if unit == "e7_len":
        return [spec_for(m, S=S, phase=ph) for m in REAL for ph in ("prefill", "decode") for S in (128, 256, 512, 1024, 2048, 4096)]
    if unit == "e7_struct":
        return [spec_for(m, kappa=k, routing=r) for m in REAL for k in (1, 2, 4) for r in ("xy", "yx")]
    if unit == "e7_lencap":
        return [spec_for(m, S=S, phase=ph, account_suffix=f"_attn{n}") for m, S, n in LENCAP for ph in ("prefill", "decode")]
    if unit == "e7_geom":     # geometry x routing x port ratio beyond the reference cells (the 2:1 XY kappa 2 cell is in e7_ref)
        return [spec_for(m, aspect=a, routing=r, kappa=k) for m in REAL for a in (2.0, 4.0) for r in ("xy", "yx") for k in (1, 2, 4)
                if not (a == 2.0 and r == "xy" and k == 2)]
    if unit == "e7_tiling":   # item 4.1: substantively different legal tilings, each with its own mapper account (suffix _tl{name}); colrow is e7_ref
        return [spec_for(m, tiling=tl, account_suffix=f"_tl{tl}") for m in REAL for tl in ("row", "mixed", "mixed2")] + \
               [spec_for("opt13b", tiling="col", account_suffix="_tlcol")]     # col differs from colrow only on OPT-13B (qkv_proj column-split at 15 dies instead of row-split at 10)
    # ---- the offload round (Isobar_attention_offload_experiments): attention on a digital unit in the package
    if unit == "e9_pair":     # batch 1: the reference 2.7B and Gemma-7B, prefill / decode at S 512, ReRAM attention die vs the central unit
        return [spec_for(m, S=512, phase=ph, grid=g, offload=o) for m, g in (("ref2p7b", (24, 24)), ("gemma7b", None)) for ph in ("prefill", "decode") for o in (None, OFF)]
    if unit == "e9_ref":      # batch 2: the three real models, central unit, prefill / decode x lengths
        return [spec_for(m, S=S, phase=ph, offload=OFF) for m in REAL for ph in ("prefill", "decode") for S in (128, 256, 512, 1024, 2048, 4096)]
    if unit == "e9_scan":     # batch 2: Gemma-7B single-variable scans (prefill / decode, S 512)
        out = []
        for ph in ("prefill", "decode"):
            for q in (0.25e12, 0.5e12, 1e12, 2e12, 4e12, 8e12, 16e12):
                out.append(spec_for("gemma7b", phase=ph, offload=with_unit(mac_per_second=q)))
            for kv in (3.2e9, 6.4e9, 12.8e9, 25.6e9, 51.2e9, 102.4e9, 204.8e9):
                out.append(spec_for("gemma7b", phase=ph, offload=with_unit(kv_words_per_second=kv)))
            for ch in (0.2, 0.4, 0.8, 1.6, 3.125, 6.25, 12.5, 25, 50, 100):
                out.append(spec_for("gemma7b", phase=ph, offload=with_unit(link_bandwidth_gbps=ch)))
            for cap in (0.5e9, 1e9, 2e9, 4e9, 8e9):
                out.append(spec_for("gemma7b", phase=ph, offload=with_unit(kv_capacity_words=cap)))
            for bm in (0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.5, 25, 50):
                out.append(spec_for("gemma7b", phase=ph, bw=bm, offload=OFF))
        seen, uniq = set(), []
        for s in out:
            if s["config_id"] not in seen:
                seen.add(s["config_id"]); uniq.append(s)
        return uniq
    if unit == "e9_hub":      # batch 3: hub position and count (Gemma-7B and OPT-13B; OPT-6.7B at the reference)
        out = []
        for m in ("gemma7b", "opt13b", "opt6.7b"):
            for ph in ("prefill", "decode"):
                for pos in ("center", "edge", "corner"):
                    out.append(spec_for(m, phase=ph, offload={**OFF, "position": pos}))
                for K in (2, 4):
                    out.append(spec_for(m, phase=ph, offload={**OFF, "K": K, "resource_mode": "total"}))
                    out.append(spec_for(m, phase=ph, offload={**OFF, "K": K, "resource_mode": "per_unit"}))
        seen, uniq = set(), []
        for s in out:
            if s["config_id"] not in seen:
                seen.add(s["config_id"]); uniq.append(s)
        return uniq
    if unit == "e9_head":     # batch 3 control: fixed total resources, K = 1 / 2 / 4, one unit per layer (layer groups) vs every layer over all units (head groups); Gemma-7B, S 512
        out = []
        for ph in ("prefill", "decode"):
            out.append(spec_for("gemma7b", phase=ph, offload={**OFF, "K": 1, "resource_mode": "total"}))
            for K in (2, 4):
                for sp in ("layer", "head"):
                    out.append(spec_for("gemma7b", phase=ph, offload={**OFF, "K": K, "resource_mode": "total", "split": sp}))
        return out
    if unit == "e9_struct":   # batch 3: geometry x routing x port ratio under the central unit (Gemma-7B, OPT-13B)
        return [spec_for(m, aspect=a, routing=r, kappa=k, offload=OFF) for m in ("gemma7b", "opt13b") for a in (1.0, 2.0, 4.0) for r in ("xy", "yx") for k in (1, 2, 4)]
    # ---- follow-up round (Isobar_followup_execution): offload backend throughout
    if unit == "e10_cap":      # 6.1 CIM die capacity under the central unit (per macro count; CIMSIM_FABRIC set), natural near-square grid
        n = macros or 8
        models = {4: ("opt6.7b", "gemma7b"), 8: REAL, 16: REAL, 32: REAL}.get(n, ())     # OPT-13B at 4 macros: no static-operator account yet (mapper needed)
        return [spec_for(m, account_suffix=("" if n == 8 else f"_m{n}"), macros=n, offload=OFF) for m in models]
    if unit == "e10_cap_common":   # 6.1 common-grid control: Gemma on the reference 36 x 36 grid at 16 and 32 macros (8 is e9_ref)
        n = macros or 8
        return [spec_for("gemma7b", grid=(36, 36), account_suffix=("" if n == 8 else f"_m{n}"), macros=n, offload=OFF)] if n in (16, 32) else []
    if unit == "e10_tiling":   # 6.2 OPT-13B legal QKV split: column-split input (_tlcol) vs the row-split colrow input, central unit
        return [spec_for("opt13b", tiling="col", account_suffix="_tlcol", offload=OFF), spec_for("opt13b", offload=OFF)]
    if unit == "e10_head":     # 7.1 distributed digital units: K = 4, fixed total resources, head groups, OPT-6.7B and OPT-13B (Gemma in e9_head); plus OPT-13B K = 4 per-unit layer groups for the expanded case
        out = [spec_for(m, phase=ph, offload={**OFF, "K": 4, "resource_mode": "total", "split": "head"}) for m in ("opt6.7b", "opt13b") for ph in ("prefill", "decode")]
        return out
    if unit == "e10_ws":       # 9.2 workspace and length thresholds: Gemma K = 1 and K = 4 fixed-total head groups at S 1024 and 2048
        out = []
        for S in (1024, 2048):
            for ph in ("prefill", "decode"):
                out.append(spec_for("gemma7b", S=S, phase=ph, offload={**OFF, "K": 1, "resource_mode": "total"}))
                out.append(spec_for("gemma7b", S=S, phase=ph, offload={**OFF, "K": 4, "resource_mode": "total", "split": "head"}))
        return out
    if unit == "e10_confirm":  # 7.2 representative configurations confirmed: 16-macro capacity (three models), K = 4 fixed-total head groups (three models), OPT-13B K = 4 per-unit layer groups, OPT-13B column-split QKV
        out = [spec_for(m, offload={**OFF, "K": 4, "resource_mode": "total", "split": "head"}) for m in REAL]
        out.append(spec_for("opt13b", offload={**OFF, "K": 4, "resource_mode": "per_unit"}))
        out.append(spec_for("opt13b", tiling="col", account_suffix="_tlcol", offload=OFF))
        return out
    if unit == "e10_confirm_cap":   # the 16-macro points (CIMSIM_FABRIC = the 16-macro variant)
        return [spec_for(m, account_suffix="_m16", macros=16, offload=OFF) for m in REAL]
    if unit == "e9_confirm":  # offload batch 4: the reference points under the central unit (500 fills, seeds 5-14, communication-normalised objective); representatives of the scans are appended by hand in analysis/v4/e9_confirm_specs.json
        out = [spec_for("ref2p7b", S=512, phase=ph, grid=(24, 24), offload=OFF) for ph in ("prefill", "decode")]
        out += [spec_for(m, S=512, phase=ph, offload=OFF) for m in REAL for ph in ("prefill", "decode")]
        extra = os.path.join(V4, "e9_confirm_specs.json")
        if os.path.exists(extra):
            for s in json.load(open(extra)):
                out.append(spec_for(**s))
        return out
    if unit == "e7_confirm":  # confirmation of the real-model reference points and the new main-case candidates (500 fills, seeds 5-14, communication-normalised objective)
        return [spec_for("opt6.7b"), spec_for("gemma7b"), spec_for("opt13b"),
                spec_for("opt13b", aspect=4.0, routing="xy", kappa=4), spec_for("gemma7b", aspect=4.0, routing="yx", kappa=4), spec_for("opt6.7b", aspect=4.0, routing="xy", kappa=4)]
    if unit == "e8_struct":   # port ratio x routing at the capacity transitions (per macro count, CIMSIM_FABRIC set)
        n = macros or 8
        models = {16: REAL, 4: ("opt6.7b",), 32: ("gemma7b", "opt13b")}.get(n, ())
        return [spec_for(m, kappa=k, routing=r, account_suffix=("" if n == 8 else f"_m{n}"), macros=n) for m in models for k in (1, 2, 4) for r in ("xy", "yx")
                if not (k == 2 and r == "xy")]
    if unit == "e8_common":   # item 3.2 control: a capacity's configuration on the OTHER capacity's die grid (same network, routing, link bandwidth, port ratio; empty slots differ)
        n = macros or 8
        table = {16: [("opt6.7b", (29, 29)), ("gemma7b", (36, 36)), ("opt13b", (48, 48))],     # the 2x die on the base die's grids
                 8: [("opt6.7b", (40, 40))],                                                    # the base die on the 1/2x die's grid
                 24: [("gemma7b", (36, 36)), ("opt13b", (48, 48))], 32: [("gemma7b", (36, 36)), ("opt13b", (48, 48)), ("opt6.7b", (29, 29))]}
        return [spec_for(m, grid=g, account_suffix=("" if n == 8 else f"_m{n}"), macros=n) for m, g in table.get(n, [])]
    if unit == "e8_cap":      # the capacity axis: run one process per macro count with CIMSIM_FABRIC set to that variant (the tiler follows the fabric)
        n = macros or 8
        return [spec_for(m, aspect=a, account_suffix=("" if n == 8 else f"_m{n}"), macros=n) for m in REAL for a in (1.0, 2.0)]
    raise ValueError(unit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", required=True)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--n-random", type=int, default=100)
    ap.add_argument("--seeds", default="0,1,2,3,4")
    ap.add_argument("--only", default="")
    ap.add_argument("--macros", type=int, default=None, help="e8_cap: macros per die of this process's fabric (CIMSIM_FABRIC must point at the matching variant)")
    ap.add_argument("--objective", default="t_norm", choices=("t_norm", "h_norm"), help="t_norm: T/T_base (V3); h_norm: (T-R)/(T_base-R), the temperature on the communication term")
    args = ap.parse_args()
    specs = unit_specs(args.unit, args.macros)
    if args.unit in ("e8_cap", "e8_common", "e8_struct", "e10_cap", "e10_cap_common", "e10_confirm_cap"):
        from scripts import mlx_system as mlx
        assert mlx.N_MACROS_PER_DIE == (args.macros or 8), f"CIMSIM_FABRIC has {mlx.N_MACROS_PER_DIE} macros per die, --macros says {args.macros}"
    if args.only:
        keep = set(args.only.split(",")); specs = [s for s in specs if s["config_id"] in keep]
    if args.list:
        for s in specs:
            print(s["config_id"])
        print(len(specs), "configs"); return
    out = os.path.join(V4, args.unit + (f"_m{args.macros or 8}" if args.unit in ("e8_cap", "e8_common", "e8_struct", "e10_cap", "e10_cap_common") else "")); os.makedirs(out, exist_ok=True)
    jl = os.path.join(out, "configs.jsonl")
    done = set()
    if os.path.exists(jl):
        for line in open(jl):
            done.add(json.loads(line)["config_id"])
    seeds = [int(x) for x in args.seeds.split(",")]
    protocol_id = f"pool{args.n_random}_seeds{min(seeds)}-{max(seeds)}_obj{args.objective}_t0norm{v3.T0_NORM:.6f}_alpha{v3.ALPHA}_budgetM(n)"
    manifest = {"unit": args.unit, "n_random": args.n_random, "seeds": seeds, "t0_norm": v3.T0_NORM, "alpha": v3.ALPHA,
                "objective": args.objective + (" = T / T_base (the V3 objective; the communication-term temperature is t0 / r0, see v4/objective_control)" if args.objective == "t_norm"
                                               else " = (T - R) / (T_base - R): t0 on the communication term (item 1.3)"),
                "budget_rule": "max(1200, ceil(1200 n/544))", "starts": "strongest rule, strongest random of the pool, random seed 0",
                "seed_formula": "1000003 s + start index (starts sorted by name)", "protocol_id": protocol_id, "planned": [s["config_id"] for s in specs]}
    with open(os.path.join(out, "manifest.json"), "w") as mf:      # explicit close: a launch-time manifest was found empty
        json.dump(manifest, mf, indent=1)
    with open(jl, "a") as f:
        for spec in specs:
            if spec["config_id"] in done:
                continue
            if spec["die_macros"] != 8:
                spec["die_cells"] = spec["die_macros"] * 32 * 256 * 256
            if spec["max_positions"] and spec["S"] > spec["max_positions"]:
                rec = {"config_id": spec["config_id"], "spec": spec, "status": "not supported by the model",
                       "reason": f"S {spec['S']} > the model's positions {spec['max_positions']}"}
            elif spec.get("offload") and spec["model"] != "ref2p7b" and glob.glob(spec["account_path"].replace(".json", "_attn*.json")) and \
                    (not os.path.exists(spec["account_path"]) or not (json.load(open(spec["account_path"])).get("phases") or {}).get(spec["phase"])):
                # offloaded: only the static operators are read from the account; the assumed-attention-die account of that
                # length carries them (derived exactly by P scaling from the measured standard-die account)
                spec["account_path"] = sorted(glob.glob(spec["account_path"].replace(".json", "_attn*.json")))[0]
                rec = v3.evaluate_config(spec, args.n_random, seeds, None, objective=args.objective)
            elif not os.path.exists(spec["account_path"]):
                from scripts import llm_workload as lw
                cfg = vm.cfg_of(spec["model"])
                cells = sum(lw.op_weight_cells(o) for o in lw.block_ops(cfg, spec["S"], spec["phase"]) if o.kind == "dynamic")
                if cells > lw.DIE_WEIGHT_CELLS and not spec.get("offload"):
                    rec = {"config_id": spec["config_id"], "spec": spec, "status": "infeasible",
                           "reason": f"capacity (one attention die): K/V arrays {cells} cells > die {lw.DIE_WEIGHT_CELLS}; no account measured"}
                else:
                    rec = {"config_id": spec["config_id"], "spec": spec, "status": "no account", "reason": f"missing {spec['account_path']}"}
            else:
                rec = v3.evaluate_config(spec, args.n_random, seeds, None, objective=args.objective)
                if rec["status"] == "infeasible" and "attention" in rec.get("reason", ""):
                    rec["reason"] = "capacity (one attention die): " + rec["reason"]
            acc = json.load(open(spec["account_path"])) if os.path.exists(spec["account_path"]) else {}
            chain_txt = "/".join(f"{n}{k}{s or ''}" for n, k, s in rec.get("chain", []))
            rec["provenance"] = {"model": spec["model"], "model_revision": acc.get("model_revision"), "account_id": os.path.basename(spec["account_path"]),
                                 "tiling_id": f"{spec['tiling']}:{chain_txt}" if chain_txt else spec["tiling"],
                                 "protocol_id": protocol_id, "scope": acc.get("scope")}
            f.write(json.dumps(rec) + "\n"); f.flush()
            if rec["status"] != "done":
                print(f"[{spec['config_id']}] {rec['status']}: {rec['reason']}", flush=True)
    v3.write_tables(out)


if __name__ == "__main__":
    main()
