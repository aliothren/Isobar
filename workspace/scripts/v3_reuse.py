"""V3 E6: placement reuse across workpoints for a chosen configuration
(2026-10-09). Takes a config id from a sweep unit (default: the confirm
unit) and its headline layout, re-scores that layout at prefill S and
decode cache lengths with measured accounts (analysis/v3/accounts/), and
runs a fresh search at every workpoint under the V3 protocol. Reports
"fixed-mapping reuse" and "re-optimized in condition" apart, with the
fallback flag.

    python3 scripts/v3_reuse.py --unit confirm --config <config_id> [--lengths 128,512,1024]
Outputs analysis/v3/e6_reuse/<config_id>.json and reuse.csv
"""
import argparse
import csv
import json
import os
import statistics
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import cimsim_cli as cli            # noqa: E402
from scripts import llm_workload as lw           # noqa: E402
from scripts import search_baselines as sb       # noqa: E402
from scripts import search_eval as se            # noqa: E402
from scripts import search_sa as sa              # noqa: E402
from scripts import search_space as ss           # noqa: E402
from scripts import v3_sweep as v3               # noqa: E402

OUT = os.path.join(WS, "analysis", "v3", "e6_reuse")


def load_record(unit, config_id):
    for l in open(os.path.join(v3.V3, unit, "configs.jsonl")):
        r = json.loads(l)
        if r["config_id"] == config_id:
            return r
    raise KeyError(config_id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default="confirm")
    ap.add_argument("--config", required=True)
    ap.add_argument("--lengths", default="128,512,1024")
    ap.add_argument("--n-random", type=int, default=100)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    rec = load_record(args.unit, args.config)
    spec = rec["spec"]
    frozen = ss.Pi.from_json(rec["search"]["runs"][rec["search"]["headline"]]["best_pi"])
    fab = v3.make_fabric(tuple(rec["grid"]), spec["topology"], spec["routing"])
    lengths = [int(x) for x in args.lengths.split(",")]
    points = []
    for phase in ("prefill", "decode"):
        for S in lengths:
            acc_path = os.path.join(v3.V3, "accounts", f"d{spec['d']}_dh{spec['dh']}_ff{spec['d_ff']}_S{S}.json")
            if spec["d"] == 2560 and spec["dh"] == 80 and spec["d_ff"] == 10240:
                acc_path = os.path.join(WS, "analysis", "scale_2p7b_per_op.json") if S == 512 else os.path.join(WS, "analysis", f"scale_2p7b_per_op_S{S}.json")
                if not os.path.exists(acc_path):
                    acc_path = os.path.join(v3.V3, "accounts", f"d2560_dh80_ff10240_S{S}.json")
            if not os.path.exists(acc_path):
                points.append({"phase": phase, "S": S, "status": "no measured account", "account": acc_path}); continue
            account = json.load(open(acc_path))
            if not account.get("phases", {}).get(phase):
                points.append({"phase": phase, "S": S, "status": "infeasible", "reason": account.get("infeasible")}); continue
            account["config"]["n_layers"] = spec["L"]
            cfg = lw.GptConfig(d_model=spec["d"], n_heads=spec["d"] // spec["dh"], d_ff=spec["d_ff"], n_layers=spec["L"])
            att = sum(lw.op_weight_cells(o) for o in lw.block_ops(cfg, S, phase) if o.kind == "dynamic")
            if att > lw.DIE_WEIGHT_CELLS:
                points.append({"phase": phase, "S": S, "status": "infeasible", "reason": "attention K/V exceeds one die"}); continue
            W = v3.V3Workload(fab, account, v3.TILINGS[spec["tiling"]]); W.port_ratio = float(spec["kappa"])
            mu = {phase: 1.0}; bw = float(spec["bw"])
            ok, why = ss.legal(frozen, W.fab, W.inventory())
            if not ok:
                points.append({"phase": phase, "S": S, "status": "frozen layout illegal here", "reason": why}); continue

            def ev(pi):
                sc = se.score(pi, W, mu=mu, d2d_gbps=bw); d = sc.per_phase[phase]["decomp"]
                return {"T_s": sc.t_opt_s, "H_s": d["d2d_serial_s"], "R_s": d["layers_s"] + d["propagation_s"], "A_words": d["d2d_busiest_words"]}
            cands = {}
            for n in sb.NAMES:
                if n == "random":
                    continue
                try:
                    cands[n] = sb.generate(n, W, seed=0)
                except Exception:
                    pass
            for s in range(args.n_random):
                cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
            rows = {n: ev(p) for n, p in cands.items()}
            strongest = min(cands, key=lambda n: rows[n]["T_s"]); t_base = rows[strongest]["T_s"]
            fr = ev(frozen)
            reuse_gain = (1 - fr["T_s"] / t_base) * 100
            # fresh search, V3 protocol
            rules = [n for n in cands if not n.startswith("random_s")]
            starts = {"rule": min(rules, key=lambda n: rows[n]["T_s"]), "random_best": min([n for n in cands if n.startswith("random_s")], key=lambda n: rows[n]["T_s"]), "random_s0": "random_s0"}
            n_dies = sum(W.inventory().values()); steps = v3.budget(n_dies); n_slots = fab.level("die").per_parent
            runs = {}
            for i, (sn, cn) in enumerate(sorted(starts.items())):
                for s in range(5):
                    J = cli.Objective(W, cands[cn], mu, "single", bw, 1.0, "t")
                    r = sa.anneal(lambda pi, J=J: J(pi) / t_base, cands[cn], n_slots, sa.Schedule(t0=v3.T0_NORM, alpha=0.996, steps=steps), seed=1000003 * s + i)
                    e = ev(r.best_pi)
                    runs[f"sa_{sn}_s{s}"] = {**e, "gain_pct": (1 - e["T_s"] / t_base) * 100, "best_pi": r.best_pi.to_json()}
            per_seed = {s: min((runs[f"sa_{sn}_s{s}"]["T_s"], f"sa_{sn}_s{s}") for sn in starts) for s in range(5)}
            order = sorted(per_seed, key=lambda s: per_seed[s][0]); hs = order[2]
            search_T = per_seed[hs][0]; search_gain = (1 - search_T / t_base) * 100
            gains = [(1 - per_seed[s][0] / t_base) * 100 for s in range(5)]
            fallback = search_T >= fr["T_s"]
            points.append({"phase": phase, "S": S, "status": "done", "account": os.path.basename(acc_path), "strongest": strongest, "T_base_s": t_base,
                           "comm_share_ref": rows[strongest]["H_s"] / t_base, "reuse": {**fr, "gain_pct": reuse_gain},
                           "search": {"steps": steps, "starts": starts, "runs": runs, "headline": per_seed[hs][1], "T_s": search_T,
                                      "gain_pct": search_gain, "gain_range_pct": [min(gains), max(gains)]},
                           "reuse_plus_search_gain_pct": max(reuse_gain, search_gain), "fallback_to_frozen": fallback,
                           "delta_search_minus_reuse_pts": search_gain - reuse_gain})
            print(f"[{args.config}] {phase} S={S}: strongest {strongest} {t_base*1e3:.1f} ms | reuse {reuse_gain:.2f}% | search {search_gain:.2f}% [{min(gains):.2f},{max(gains):.2f}] | fallback {fallback} | share {rows[strongest]['H_s']/t_base*100:.1f}%", flush=True)
    res = {"config_id": args.config, "unit": args.unit, "frozen_layout": rec["search"]["headline"], "spec": spec, "grid": rec["grid"], "points": points}
    json.dump(res, open(os.path.join(OUT, f"{args.config}.json"), "w"), indent=1)
    with open(os.path.join(OUT, f"{args.config}.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["phase", "S", "status", "account", "strongest", "T_base_ms", "comm_share_ref_pct", "reuse_T_ms", "reuse_gain_pct", "search_T_ms", "search_gain_pct", "search_min", "search_max", "reuse_plus_search_pct", "fallback"])
        for p in points:
            if p["status"] != "done":
                w.writerow([p["phase"], p["S"], p["status"], p.get("account", ""), "", "", "", "", "", "", "", "", "", "", ""]); continue
            w.writerow([p["phase"], p["S"], "done", p["account"], p["strongest"], f"{p['T_base_s']*1e3:.3f}", f"{p['comm_share_ref']*100:.2f}", f"{p['reuse']['T_s']*1e3:.3f}",
                        f"{p['reuse']['gain_pct']:.3f}", f"{p['search']['T_s']*1e3:.3f}", f"{p['search']['gain_pct']:.3f}", f"{p['search']['gain_range_pct'][0]:.3f}",
                        f"{p['search']['gain_range_pct'][1]:.3f}", f"{p['reuse_plus_search_gain_pct']:.3f}", p["fallback_to_frozen"]])
    print("->", OUT)


if __name__ == "__main__":
    main()
