"""Next-round item 4.3: placement reuse on the real models. The layout
selected at prefill 512 on the near-square grid (the headline of the
e7_ref record) is re-scored at every other workpoint (prefill / decode x
S 128 / 256 / 512 / 1024) against that workpoint's own strongest baseline
(7 rules + a 500-fill pool drawn there), beside a cold search (the three
V3 starts x 5 seeds, V3 objective and budget) and a warm search (the
frozen layout as the start, incumbent kept; labelled apart).

    python3 scripts/v4_reuse.py opt6.7b [--n-random 500] [--lengths 128,256,512,1024]
      -> analysis/v4/e7_reuse/<model>.json, <model>.csv
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import cimsim_cli as cli            # noqa: E402
from scripts import llm_workload as lw           # noqa: E402
from scripts import search_baselines as sb       # noqa: E402
from scripts import search_eval as se            # noqa: E402
from scripts import search_sa as sa              # noqa: E402
from scripts import search_space as ss           # noqa: E402
from scripts import v3_sweep as v3               # noqa: E402

V4 = os.path.join(WS, "analysis", "v4")
OUT = os.path.join(V4, "e7_reuse")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--n-random", type=int, default=500)
    ap.add_argument("--lengths", default="128,256,512,1024")
    ap.add_argument("--source-unit", default="e7_ref")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    rec = None
    for line in open(os.path.join(V4, args.source_unit, "configs.jsonl")):
        r = json.loads(line)
        if r["spec"]["model"] == args.model and r["spec"].get("aspect") == 1.0 and r["spec"]["phase"] == "prefill" and r["spec"]["S"] == 512 and r["status"] == "done":
            rec = r; break
    if rec is None:
        raise SystemExit(f"no done prefill-512 near-square record for {args.model} in {args.source_unit}")
    spec = rec["spec"]
    frozen = ss.Pi.from_json(rec["search"]["runs"][rec["search"]["headline"]]["best_pi"])
    fab = v3.make_fabric(tuple(rec["grid"]), spec["topology"], spec["routing"])
    bw, kappa = float(spec["bw"]), float(spec["kappa"])
    points = []
    for phase in ("prefill", "decode"):
        for S in [int(x) for x in args.lengths.split(",")]:
            acc_path = os.path.join(V4, "accounts", f"{args.model}_S{S}.json")
            if not os.path.exists(acc_path):
                points.append({"phase": phase, "S": S, "status": "no measured account"}); continue
            account = json.load(open(acc_path))
            if not account.get("phases", {}).get(phase):
                points.append({"phase": phase, "S": S, "status": "infeasible", "reason": account.get("infeasible", {}).get(phase)}); continue
            account["config"]["n_layers"] = spec["L"]
            W = v3.V3Workload(fab, account, v3.TILINGS[spec["tiling"]]); W.port_ratio = kappa
            cells = sum(lw.op_weight_cells(o) for o in lw.block_ops(W.cfg, S, phase) if o.kind == "dynamic")
            if cells > lw.DIE_WEIGHT_CELLS:
                points.append({"phase": phase, "S": S, "status": "infeasible", "reason": "capacity (one attention die)"}); continue
            mu = {phase: 1.0}
            ok, why = ss.legal(frozen, W.fab, W.inventory())
            if not ok:
                points.append({"phase": phase, "S": S, "status": "frozen layout illegal here", "reason": why}); continue

            def ev(pi):
                sc = se.score(pi, W, mu=mu, d2d_gbps=bw); d = sc.per_phase[phase]["decomp"]
                return {"T_s": sc.t_opt_s, "H_s": d["d2d_serial_s"], "P_s": d["propagation_s"], "R_s": d["layers_s"], "A_words": d["d2d_busiest_words"], "E_J": sc.e_J}
            t0 = time.perf_counter()
            cands = {}
            for n in sb.NAMES:
                if n != "random":
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
            rules = [n for n in cands if not n.startswith("random_s")]
            starts = {"rule": min(rules, key=lambda n: rows[n]["T_s"]), "random_best": min([n for n in cands if n.startswith("random_s")], key=lambda n: rows[n]["T_s"]), "random_s0": "random_s0"}
            pis = {**cands, "frozen": frozen}
            n_dies = sum(W.inventory().values()); steps = v3.budget(n_dies); n_slots = fab.level("die").per_parent
            runs = {}
            for i, (sn, cn) in enumerate(sorted({**starts, "frozen": "frozen"}.items())):
                for s in range(5):
                    J = cli.Objective(W, pis[cn], mu, "single", bw, 1.0, "t")
                    r = sa.anneal(lambda pi, J=J: J(pi) / t_base, pis[cn], n_slots, sa.Schedule(t0=v3.T0_NORM, alpha=v3.ALPHA, steps=steps), seed=1000003 * s + i)
                    e = ev(r.best_pi)
                    runs[f"sa_{sn}_s{s}"] = {**e, "start": sn, "seed": s, "gain_pct": (1 - e["T_s"] / t_base) * 100}
            cold = [min(runs[f"sa_{sn}_s{s}"]["T_s"] for sn in starts) for s in range(5)]
            warm = [runs[f"sa_frozen_s{s}"]["T_s"] for s in range(5)]
            g = lambda xs: (1 - statistics.median(xs) / t_base) * 100
            pt = {"phase": phase, "S": S, "status": "done", "account": os.path.basename(acc_path), "n_random": args.n_random, "strongest": strongest, "T_base_s": t_base,
                  "comm_share_ref": (rows[strongest]["H_s"] + rows[strongest]["P_s"]) / t_base, "H0_s": rows[strongest]["H_s"], "P0_s": rows[strongest]["P_s"], "R0_s": rows[strongest]["R_s"],
                  "reuse": {**fr, "gain_pct": reuse_gain, "eta_pct": (1 - fr["H_s"] / rows[strongest]["H_s"]) * 100},
                  "cold": {"T_median_s": statistics.median(cold), "gain_pct": g(cold), "gain_min_pct": (1 - max(cold) / t_base) * 100, "gain_max_pct": (1 - min(cold) / t_base) * 100},
                  "warm": {"T_median_s": statistics.median(warm), "gain_pct": g(warm), "gain_min_pct": (1 - max(warm) / t_base) * 100, "gain_max_pct": (1 - min(warm) / t_base) * 100},
                  "steps": steps, "runs": runs, "wall_s": time.perf_counter() - t0}
            points.append(pt)
            print(f"[{args.model}] {phase} S={S}: strongest {strongest} {t_base*1e3:.1f} ms | share {pt['comm_share_ref']*100:.1f}% | reuse {reuse_gain:.2f}% (eta {pt['reuse']['eta_pct']:.1f}%) | cold {g(cold):.2f}% [{pt['cold']['gain_min_pct']:.2f}, {pt['cold']['gain_max_pct']:.2f}] | warm {g(warm):.2f}% | {pt['wall_s']:.0f} s", flush=True)
    res = {"model": args.model, "source_record": rec["config_id"], "frozen_layout": rec["search"]["headline"], "grid": rec["grid"], "points": points}
    json.dump(res, open(os.path.join(OUT, f"{args.model}.json"), "w"), indent=1)
    with open(os.path.join(OUT, f"{args.model}.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["phase", "S", "status", "account", "strongest", "T_base_ms", "comm_share_ref_pct", "reuse_T_ms", "reuse_gain_pct", "reuse_eta_pct", "cold_gain_pct", "cold_min", "cold_max", "warm_gain_pct", "warm_min", "warm_max", "reason"])
        for p in points:
            if p["status"] != "done":
                w.writerow([p["phase"], p["S"], p["status"], "", "", "", "", "", "", "", "", "", "", "", "", "", p.get("reason", "")]); continue
            w.writerow([p["phase"], p["S"], "done", p["account"], p["strongest"], f"{p['T_base_s']*1e3:.3f}", f"{p['comm_share_ref']*100:.2f}", f"{p['reuse']['T_s']*1e3:.3f}", f"{p['reuse']['gain_pct']:.3f}", f"{p['reuse']['eta_pct']:.3f}",
                        f"{p['cold']['gain_pct']:.3f}", f"{p['cold']['gain_min_pct']:.3f}", f"{p['cold']['gain_max_pct']:.3f}", f"{p['warm']['gain_pct']:.3f}", f"{p['warm']['gain_min_pct']:.3f}", f"{p['warm']['gain_max_pct']:.3f}", ""])
    print("->", OUT)


if __name__ == "__main__":
    main()
