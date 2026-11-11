"""The deployment experiments of the paper. Each experiment is a list of
configurations (model, phase, sequence length, die capacity, digital-unit
organisation, network) evaluated with one search protocol; a configuration
is priced from its per-operator account (results/accounts/), every baseline
layout of its pool is scored, and the annealer is run from three starts per
seed. One record per configuration is appended to
results/records/<experiment>/configs.jsonl, with summary tables beside it.

Protocols:
    confirmation  500 random fills, annealer seeds 5-14, objective H / H_base
    exploration   100 random fills, annealer seeds 0-4,  objective T / T_base
Both: three starts (strongest named rule, strongest random fill, random fill
0), budget max(1200, ceil(1200 n / 544)) steps for n movable dies, cooling
0.996, seed 1000003 s + start index.

Experiments (paper figure / table in brackets):
    reference       8 macros per die, one central digital unit; the 2.7B-class
                    reference and OPT-1.3B / 6.7B / 13B, Gemma-7B, prefill and
                    decode at 512 tokens                      [Figs. 1b, 3, 5, 6a]
    capacity16      16 macros per die, central unit, prefill   [Fig. 6b, Table III]
    distributed     8 macros per die, four units on head groups with the
                    reference total resources, prefill         [Fig. 6c]
    qkv_split       OPT-13B with column- and row-split QKV projections on a
                    common 49 x 49 mesh                        [Table II]
    capacity_sweep  4 / 8 / 16 / 32 macros per die (one --macros per run),
                    exploration protocol; Gemma-7B also on the 36 x 36 mesh
                                                               [Fig. 7a]
    organisation    Gemma-7B prefill: one unit, four units on layer groups,
                    four units on head groups, fixed total resources  [Fig. 7b]
    context_length  Gemma-7B prefill and decode, 128-4096 tokens  [Fig. 7d]

    python3 scripts/run_experiments.py --experiment reference
    python3 scripts/run_experiments.py --experiment capacity_sweep --macros 16
    python3 scripts/run_experiments.py --experiment reference --list
    python3 scripts/run_experiments.py --custom --model gemma7b --phase decode --S 1024 --units 4 --split head

The die capacity of the process follows --macros (models/fabric/variants for
4, 16 and 32 macros; the base die for 8). A configuration already present in
its configs.jsonl is skipped, so an interrupted run resumes.
"""
import argparse
import glob
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import paths                    # noqa: E402  (reads no fabric)

# ---- the process's die capacity must be fixed before any module that reads the fabric is imported
EXPERIMENT_MACROS = {"capacity16": 16}


def _variant_fabric(macros):
    return None if macros == 8 else os.path.join(paths.FABRICS, "variants", f"mlx300_multidie_m{macros}.yaml")


def _select_fabric(argv):
    macros = None
    if "--macros" in argv:
        macros = int(argv[argv.index("--macros") + 1])
    if "--experiment" in argv:
        macros = EXPERIMENT_MACROS.get(argv[argv.index("--experiment") + 1], macros)
    macros = macros or 8
    want = _variant_fabric(macros)
    have = os.environ.get("CIMSIM_FABRIC")
    if want is None:
        if have and "variants" in have:
            raise SystemExit(f"CIMSIM_FABRIC={have} selects a die-capacity variant; unset it for 8 macros per die")
    elif have and os.path.abspath(have) != os.path.abspath(want):
        raise SystemExit(f"CIMSIM_FABRIC={have} disagrees with {macros} macros per die ({want})")
    elif not have:
        os.environ["CIMSIM_FABRIC"] = want
    return macros


MACROS = _select_fabric(sys.argv)
from scripts import experiment as v3          # noqa: E402
from scripts import model_configs as vm       # noqa: E402

CONFIRMATION, EXPLORATION = v3.CONFIRMATION, v3.EXPLORATION
MODELS = ("opt1.3b", "opt6.7b", "gemma7b", "opt13b")
OFF = {"position": "center", "K": 1, "resource_mode": "per_unit"}       # one central digital unit at the reference resources


def offload_tag(o):
    if not o:
        return ""
    u = o.get("unit") or {}
    ov = "".join(f"_{k}{v:g}" for k, v in sorted(u.items()))
    return f"_off{o.get('position', 'center')}K{o.get('K', 1)}{'T' if o.get('resource_mode') == 'total' else ''}{'H' if o.get('split') == 'head' else ''}{ov}"


def spec_for(model, S=512, phase="prefill", aspect=1.0, grid=None, topology="mesh", routing="xy", kappa=2.0, bw=0.4, tiling="colrow",
             account_suffix="", macros=None, offload=None, **extra):
    """One configuration. The config id names every field that varies across the experiments."""
    cfg = vm.cfg_of(model)
    gtag = f"{grid[0]}x{grid[1]}" if grid else ("sq" if aspect == 1.0 else f"a{aspect:g}")
    cid = f"{model}_{phase}{S}_{tiling}_{gtag}_{topology}_{routing}_k{kappa:g}_b{bw:g}{account_suffix}{offload_tag(offload)}"
    if model == "ref2p7b":            # the reference account (block level: any depth)
        acc = v3.REF_ACCOUNT if S == 512 else os.path.join(paths.REFERENCE, f"reference_2p7b_S{S}.json")
    else:
        acc = os.path.join(paths.ACCOUNTS, f"{model}_S{S}{account_suffix}.json")
    return {"model": model, "d": cfg.d_model, "dh": cfg.dh, "d_ff": cfg.d_ff, "L": cfg.n_layers, "S": S, "phase": phase, "tiling": tiling,
            "grid": grid, "aspect": aspect, "topology": topology, "routing": routing, "kappa": float(kappa), "bw": float(bw),
            "model_tag": model, "config_id": cid, "account_path": acc,
            "account_suffix": account_suffix, "die_macros": macros or 8, "max_positions": vm.MODELS[model]["max_positions"],
            "offload": offload, **extra}


def _suffix(n):
    return "" if n == 8 else f"_m{n}"


def experiment(name, macros=8):
    """(protocol, specs) of one experiment. sa_tie_draw = False marks the runs
    made with the annealer's other random-stream setting (search_sa.Schedule)."""
    total = {**OFF, "resource_mode": "total"}
    if name == "reference":
        specs = [spec_for("ref2p7b", phase=ph, grid=(24, 24), offload=OFF) for ph in ("prefill", "decode")]
        specs += [spec_for(m, phase=ph, offload=OFF) for m in MODELS for ph in ("prefill", "decode")]
        return CONFIRMATION, specs
    if name == "capacity16":
        return CONFIRMATION, [spec_for(m, account_suffix="_m16", macros=16, offload=OFF) for m in MODELS]
    if name == "distributed":
        specs = [spec_for(m, offload={**total, "K": 4, "split": "head"}) for m in MODELS if m != "opt1.3b"]
        # OPT-1.3B's natural 13 x 13 mesh holds its 168 dies and one unit only; the four units need 14 x 14
        specs.append(spec_for("opt1.3b", grid=(14, 14), offload={**total, "K": 4, "split": "head"}, sa_tie_draw=False))
        return CONFIRMATION, specs
    if name == "qkv_split":
        return CONFIRMATION, [spec_for("opt13b", tiling="col", account_suffix="_tlcol", offload=OFF),     # 15 dies per layer column-split: 2400 dies, 49 x 49
                              spec_for("opt13b", grid=(49, 49), offload=OFF)]                             # 10 dies per layer row-split, on the same mesh
    if name == "capacity_sweep":
        specs = [spec_for(m, account_suffix=_suffix(macros), macros=macros, offload=OFF,
                          **({"sa_tie_draw": False} if m == "opt1.3b" or (m == "opt13b" and macros == 4) else {}))
                 for m in MODELS]
        if macros in (16, 32):           # Gemma-7B on its 8-macro mesh (36 x 36): the capacity change without the mesh change
            specs.append(spec_for("gemma7b", grid=(36, 36), account_suffix=_suffix(macros), macros=macros, offload=OFF))
        return EXPLORATION, specs
    if name == "organisation":
        return EXPLORATION, [spec_for("gemma7b", offload={**total, "K": 1}),
                             spec_for("gemma7b", offload={**total, "K": 4}),
                             spec_for("gemma7b", offload={**total, "K": 4, "split": "head"})]
    if name == "context_length":
        return EXPLORATION, [spec_for("gemma7b", S=S, phase=ph, offload=OFF)
                             for ph in ("prefill", "decode") for S in (128, 256, 512, 1024, 2048, 4096)]
    raise SystemExit(f"unknown experiment {name}; choose from {', '.join(EXPERIMENTS)}")


EXPERIMENTS = ("reference", "capacity16", "distributed", "qkv_split", "capacity_sweep", "organisation", "context_length")


def record_dir(name, macros):
    return os.path.join(paths.RECORDS, name + (f"_m{macros}" if name == "capacity_sweep" else ""))


def run_spec(spec, protocol):
    """One record: the configuration evaluated and searched, or the reason it cannot be."""
    if spec["die_macros"] != 8:
        spec["die_cells"] = spec["die_macros"] * 32 * 256 * 256
    if spec["max_positions"] and spec["S"] > spec["max_positions"]:
        return {"config_id": spec["config_id"], "spec": spec, "status": "not supported by the model",
                "reason": f"S {spec['S']} > the model's positions {spec['max_positions']}"}
    kw = dict(objective=protocol["objective"])
    if spec.get("offload") and spec["model"] != "ref2p7b" and glob.glob(spec["account_path"].replace(".json", "_attn*.json")) and \
            (not os.path.exists(spec["account_path"]) or not (json.load(open(spec["account_path"])).get("phases") or {}).get(spec["phase"])):
        # attention on the digital unit: only the static operators are read from the account; at lengths where the
        # standard die cannot hold the attention's K and V the account measured with a larger attention die carries them
        spec["account_path"] = sorted(glob.glob(spec["account_path"].replace(".json", "_attn*.json")))[0]
    if not os.path.exists(spec["account_path"]):
        return {"config_id": spec["config_id"], "spec": spec, "status": "no account", "reason": f"missing {spec['account_path']}"}
    return v3.evaluate_config(spec, protocol["n_random"], protocol["seeds"], None, **kw)


def main():
    ap = argparse.ArgumentParser(description="run the paper's deployment experiments, or one custom configuration")
    ap.add_argument("--experiment", choices=EXPERIMENTS)
    ap.add_argument("--macros", type=int, default=None, choices=(4, 8, 16, 32), help="macros per die (capacity_sweep, custom)")
    ap.add_argument("--list", action="store_true", help="print the configuration ids and stop")
    ap.add_argument("--only", default="", help="comma-separated configuration ids")
    ap.add_argument("--name", default=None, help="record directory under results/records/ (default: custom, or the experiment's own)")
    ap.add_argument("--redo", action="store_true", help="recompute configurations that already have a record, replacing it")
    ap.add_argument("--n-random", type=int, default=None, help="override the protocol's random-fill pool size")
    ap.add_argument("--seeds", default=None, help="override the protocol's annealer seeds, e.g. 0,1")
    ap.add_argument("--objective", default=None, choices=("t_norm", "h_norm"))
    c = ap.add_argument_group("custom configuration")
    c.add_argument("--custom", action="store_true")
    c.add_argument("--model", default="gemma7b", choices=sorted(vm.MODELS))
    c.add_argument("--phase", default="prefill", choices=("prefill", "decode"))
    c.add_argument("--S", type=int, default=512, help="prefill length / decode context")
    c.add_argument("--bw", type=float, default=0.4, help="mesh link bandwidth per direction, GB/s")
    c.add_argument("--kappa", type=float, default=2.0, help="CIM die port bandwidth / link bandwidth")
    c.add_argument("--routing", default="xy", choices=("xy", "yx"))
    c.add_argument("--grid", default=None, help="mesh X,Y (default: the smallest near-square mesh)")
    c.add_argument("--tiling", default="colrow", choices=sorted(v3.TILINGS))
    c.add_argument("--units", type=int, default=1, help="digital attention units")
    c.add_argument("--position", default="center", choices=("center", "edge", "corner"))
    c.add_argument("--split", default="layer", choices=("layer", "head"), help="units take layer groups or head groups")
    c.add_argument("--resources", default="per_unit", choices=("per_unit", "total"),
                   help="per_unit: every unit has the reference resources; total: the reference resources are divided")
    c.add_argument("--unit-param", action="append", default=[], metavar="NAME=VALUE",
                   help="override one digital-unit parameter of offload.REF_UNIT, e.g. kv_words_per_second=51.2e9 (repeatable)")
    c.add_argument("--protocol", default="exploration", choices=("exploration", "confirmation"))
    args = ap.parse_args()
    if args.custom:
        name = "custom"
        protocol = dict(EXPLORATION if args.protocol == "exploration" else CONFIRMATION)
        off = {"position": args.position, "K": args.units, "resource_mode": args.resources}
        if args.split == "head":
            off["split"] = "head"
        if args.unit_param:
            from scripts import offload as offload_mod
            unit = {}
            for kv in args.unit_param:
                k, _, v = kv.partition("=")
                if k not in offload_mod.REF_UNIT or k == "algorithm":
                    ap.error(f"--unit-param {k}: not a numeric parameter of offload.REF_UNIT")
                unit[k] = float(v)
            off["unit"] = unit
        suffix = _suffix(MACROS) + ("" if args.tiling == "colrow" else f"_tl{args.tiling}")
        specs = [spec_for(args.model, S=args.S, phase=args.phase, grid=tuple(int(x) for x in args.grid.split(",")) if args.grid else None,
                          routing=args.routing, kappa=args.kappa, bw=args.bw, tiling=args.tiling, account_suffix=suffix, macros=MACROS, offload=off)]
        out = os.path.join(paths.RECORDS, args.name or "custom")
    elif args.experiment:
        name = args.experiment
        protocol, specs = experiment(name, MACROS)
        protocol = dict(protocol)
        out = os.path.join(paths.RECORDS, args.name) if args.name else record_dir(name, MACROS)
    else:
        ap.error("give --experiment NAME or --custom")
    if args.n_random is not None:
        protocol["n_random"] = args.n_random
    if args.seeds is not None:
        protocol["seeds"] = [int(x) for x in args.seeds.split(",")]
    if args.objective is not None:
        protocol["objective"] = args.objective
    if args.only:
        keep = set(args.only.split(",")); specs = [s for s in specs if s["config_id"] in keep]
    if args.list:
        for s in specs:
            print(s["config_id"])
        print(len(specs), "configurations;", f"{protocol['n_random']} random fills, seeds {protocol['seeds']}, objective {protocol['objective']}")
        return
    os.makedirs(out, exist_ok=True)
    jl = os.path.join(out, "configs.jsonl")
    # A record is reused only if it finished and used the same search settings; a record that did not
    # finish (e.g. "no account") is recomputed; --redo recomputes everything selected.
    existing = {}
    if os.path.exists(jl):
        for line in open(jl):
            r = json.loads(line)
            existing[r["config_id"]] = r
    want = (protocol["n_random"], list(protocol["seeds"]), protocol["objective"])
    done, replace, clash = set(), set(), []
    for spec in specs:
        r = existing.get(spec["config_id"])
        if r is None:
            continue
        if args.redo or r.get("status") != "done":
            replace.add(spec["config_id"])
        elif (r.get("n_random"), list(r["search"]["seeds"]), r["search"].get("objective", "t_norm")) == want:
            done.add(spec["config_id"])
        else:
            clash.append(spec["config_id"])
    if clash:
        raise SystemExit(f"{len(clash)} configuration(s) in {out} were searched with other settings ({clash[0]} ...): "
                         "use --name to keep both results in a new directory, or --redo to replace them")
    if replace:
        with open(jl, "w") as f:
            for cid, r in existing.items():
                if cid not in replace:
                    f.write(json.dumps(r) + "\n")
    if done:
        print(f"{len(done)} configuration(s) already in {out} with the same settings: skipped (--redo to recompute)")
    seeds = protocol["seeds"]
    protocol_id = f"pool{protocol['n_random']}_seeds{min(seeds)}-{max(seeds)}_obj{protocol['objective']}_t0norm{v3.T0_NORM:.6f}_alpha{v3.ALPHA}_budgetM(n)"
    manifest = {"experiment": name, "macros_per_die": MACROS, "n_random": protocol["n_random"], "seeds": seeds, "t0_norm": v3.T0_NORM, "alpha": v3.ALPHA,
                "objective": protocol["objective"] + (" = T / T_base" if protocol["objective"] == "t_norm" else " = (T - R) / (T_base - R) = H / H_base"),
                "budget_rule": "max(1200, ceil(1200 n/544))", "starts": "strongest rule, strongest random of the pool, random seed 0",
                "seed_formula": "1000003 s + start index (starts sorted by name)", "protocol_id": protocol_id, "planned": [s["config_id"] for s in specs]}
    with open(os.path.join(out, "manifest.json"), "w") as mf:
        json.dump(manifest, mf, indent=1)
    with open(jl, "a") as f:
        for spec in specs:
            if spec["config_id"] in done:
                continue
            rec = run_spec(spec, protocol)
            acc = json.load(open(spec["account_path"])) if os.path.exists(spec["account_path"]) else {}
            chain_txt = "/".join(f"{n}{k}{s or ''}" for n, k, s in rec.get("chain", []))
            rec["provenance"] = {"model": spec["model"], "model_revision": acc.get("model_revision"), "account_id": os.path.basename(spec["account_path"]),
                                 "tiling_id": f"{spec['tiling']}:{chain_txt}" if chain_txt else spec["tiling"],
                                 "protocol_id": protocol_id, "scope": acc.get("scope")}
            f.write(json.dumps(rec) + "\n"); f.flush()
            if rec["status"] != "done":
                print(f"[{spec['config_id']}] {rec['status']}: {rec['reason']}", flush=True)
    v3.write_tables(out)
    print("->", out)


if __name__ == "__main__":
    main()
