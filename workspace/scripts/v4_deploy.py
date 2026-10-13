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


def spec_for(model, S=512, phase="prefill", aspect=1.0, grid=None, topology="mesh", routing="xy", kappa=2.0, bw=0.4, tiling="colrow", account_suffix="", macros=None):
    cfg = vm.cfg_of(model)
    gtag = f"{grid[0]}x{grid[1]}" if grid else ("sq" if aspect == 1.0 else f"a{aspect:g}")
    cid = f"{model}_{phase}{S}_{tiling}_{gtag}_{topology}_{routing}_k{kappa:g}_b{bw:g}{account_suffix}"
    return {"model": model, "d": cfg.d_model, "dh": cfg.dh, "d_ff": cfg.d_ff, "L": cfg.n_layers, "S": S, "phase": phase, "tiling": tiling,
            "grid": grid, "aspect": aspect, "topology": topology, "routing": routing, "kappa": float(kappa), "bw": float(bw),
            "model_tag": model, "config_id": cid, "account_path": os.path.join(ACC, f"{model}_S{S}{account_suffix}.json"),
            "account_suffix": account_suffix, "die_macros": macros or 8, "max_positions": vm.MODELS[model]["max_positions"]}


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
        return [spec_for(m, tiling=tl, account_suffix=f"_tl{tl}") for m in REAL for tl in ("row", "mixed", "mixed2")]
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
    args = ap.parse_args()
    specs = unit_specs(args.unit, args.macros)
    if args.unit in ("e8_cap", "e8_common"):
        from scripts import mlx_system as mlx
        assert mlx.N_MACROS_PER_DIE == (args.macros or 8), f"CIMSIM_FABRIC has {mlx.N_MACROS_PER_DIE} macros per die, --macros says {args.macros}"
    if args.only:
        keep = set(args.only.split(",")); specs = [s for s in specs if s["config_id"] in keep]
    if args.list:
        for s in specs:
            print(s["config_id"])
        print(len(specs), "configs"); return
    out = os.path.join(V4, args.unit + (f"_m{args.macros or 8}" if args.unit in ("e8_cap", "e8_common") else "")); os.makedirs(out, exist_ok=True)
    jl = os.path.join(out, "configs.jsonl")
    done = set()
    if os.path.exists(jl):
        for line in open(jl):
            done.add(json.loads(line)["config_id"])
    seeds = [int(x) for x in args.seeds.split(",")]
    protocol_id = f"pool{args.n_random}_seeds{min(seeds)}-{max(seeds)}_t0norm{v3.T0_NORM:.6f}_alpha{v3.ALPHA}_budgetM(n)"
    manifest = {"unit": args.unit, "n_random": args.n_random, "seeds": seeds, "t0_norm": v3.T0_NORM, "alpha": v3.ALPHA,
                "objective": "T / T_base (the V3 objective; the communication-term temperature is t0 / r0, see v4/objective_control)",
                "budget_rule": "max(1200, ceil(1200 n/544))", "starts": "strongest rule, strongest random of the pool, random seed 0",
                "seed_formula": "1000003 s + start index (starts sorted by name)", "protocol_id": protocol_id, "planned": [s["config_id"] for s in specs]}
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    with open(jl, "a") as f:
        for spec in specs:
            if spec["config_id"] in done:
                continue
            if spec["die_macros"] != 8:
                spec["die_cells"] = spec["die_macros"] * 32 * 256 * 256
            if spec["max_positions"] and spec["S"] > spec["max_positions"]:
                rec = {"config_id": spec["config_id"], "spec": spec, "status": "not supported by the model",
                       "reason": f"S {spec['S']} > the model's positions {spec['max_positions']}"}
            elif not os.path.exists(spec["account_path"]):
                from scripts import llm_workload as lw
                cfg = vm.cfg_of(spec["model"])
                cells = sum(lw.op_weight_cells(o) for o in lw.block_ops(cfg, spec["S"], spec["phase"]) if o.kind == "dynamic")
                if cells > lw.DIE_WEIGHT_CELLS:
                    rec = {"config_id": spec["config_id"], "spec": spec, "status": "infeasible",
                           "reason": f"capacity (one attention die): K/V arrays {cells} cells > die {lw.DIE_WEIGHT_CELLS}; no account measured"}
                else:
                    rec = {"config_id": spec["config_id"], "spec": spec, "status": "no account", "reason": f"missing {spec['account_path']}"}
            else:
                rec = v3.evaluate_config(spec, args.n_random, seeds, None)
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
