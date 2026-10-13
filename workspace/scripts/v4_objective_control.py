"""Next-round item 1.3: why a fresh search at the decode workpoint ends
below the reused prefill layout -- a controlled comparison, not a new
search method.

Under the V3 objective T / T_base with a fixed normalized temperature t0,
a move that changes the communication term by dH changes the objective by
dH / T_base, so the annealer's effective temperature on the communication
term scales with 1 / r0 (r0 = (H + P) / T_base of the strongest baseline):
at decode (r0 about 8.5%) the same t0 is about 6.5x hotter, relative to the
term being optimised, than at prefill (r0 about 55%). The control keeps
the feasible space, the moves, the starts, the seeds and the budget and
changes one thing at a time:

  objective 't_norm' : T / T_base, t0 = 0.0094396 (the V3 run);
  objective 'h_norm' : (T - R) / (T_base - R) with the same t0, i.e. the
                       communication term normalised by its own baseline
                       value (R = N + F is placement-independent, so the two
                       objectives differ by a constant and a positive factor
                       1 / r0; this is the temperature rescaled by r0);
  starts            : the three V3 cold starts (strongest rule, strongest
                       random of the pool, random seed 0) and, marked
                       apart, the frozen prefill-512 layout as a warm start
                       (the annealer keeps the start as the incumbent, so
                       the warm run can never end above the reused layout);
  seeds 0..4; budget M(n).

Workpoints: the reference 2.7B at prefill 512 and decode 512, and the
confirmed 2.7B ratio-8 configuration at the same two workpoints. Pools:
500 fills at every workpoint. Three readings per workpoint and objective:
the frozen layout re-scored once (reuse), the cold search (best of the
three cold starts per seed, median over seeds), and the warm search.

    python3 scripts/v4_objective_control.py  -> analysis/v4/objective_control/{runs.csv, summary.csv, summary.md}
"""
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

OUT = os.path.join(WS, "analysis", "v4", "objective_control")
N_RANDOM = 500
SEEDS = (0, 1, 2, 3, 4)
CASES = [  # (confirm config id = source of the frozen prefill layout, d, dh, d_ff, grid)
    ("2p7B_dh80_ff10240_L32_colrow_prefill512_24x24_mesh_xy_k2_b0.4", 2560, 80, 10240, (24, 24)),
    ("2p7Bf_dh80_ff20480_L32_colrow_prefill512_30x30_mesh_xy_k2_b0.4", 2560, 80, 20480, (30, 30)),
]


def account_for(d, dh, d_ff, S):
    if (d, dh, d_ff, S) == (2560, 80, 10240, 512):
        acc = json.load(open(v3.REF_ACCOUNT)); status = "measured (frozen 2.7B S=512)"
    else:
        p = os.path.join(v3.V3, "accounts", f"d{d}_dh{dh}_ff{d_ff}_S{S}.json")
        acc = json.load(open(p)); status = f"measured ({os.path.basename(p)})"
    acc["config"]["n_layers"] = 32
    return acc, status


def frozen_layout(config_id):
    for line in open(os.path.join(v3.V3, "confirm", "configs.jsonl")):
        r = json.loads(line)
        if r["config_id"] == config_id:
            return ss.Pi.from_json(r["search"]["runs"][r["search"]["headline"]]["best_pi"]), r["search"]["headline"]
    raise KeyError(config_id)


def main():
    os.makedirs(OUT, exist_ok=True)
    runs, summ = [], []
    for cid, d, dh, d_ff, grid in CASES:
        frozen, frozen_name = frozen_layout(cid)
        for phase in ("prefill", "decode"):
            S = 512
            acc, status = account_for(d, dh, d_ff, S)
            fab = v3.make_fabric(grid, "mesh", "xy")
            W = v3.V3Workload(fab, acc, ("M", "C")); W.port_ratio = 2.0
            mu = {phase: 1.0}
            comp, wr, elw = W.layer_terms_s(phase)
            R = (comp + wr + elw) * 32

            def ev(pi):
                sc = se.score(pi, W, mu=mu, caliber="single", d2d_gbps=0.4)
                dd = sc.per_phase[phase]["decomp"]
                return {"T_s": sc.t_opt_s, "H_s": dd["d2d_serial_s"], "prop_s": dd["propagation_s"], "A_words": dd["d2d_busiest_words"]}
            t0 = time.perf_counter()
            cands = {}
            for n in sb.NAMES:
                if n != "random":
                    try:
                        cands[n] = sb.generate(n, W, seed=0)
                    except Exception:
                        pass
            for s in range(N_RANDOM):
                cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
            rows = {n: ev(p) for n, p in cands.items()}
            rules = [n for n in cands if not n.startswith("random_s")]
            strongest = min(cands, key=lambda n: rows[n]["T_s"]); t_base = rows[strongest]["T_s"]
            r0 = (rows[strongest]["H_s"] + rows[strongest]["prop_s"]) / t_base
            fr = ev(frozen)
            starts = {"rule": min(rules, key=lambda n: rows[n]["T_s"]), "random_best": min((n for n in cands if n.startswith("random_s")), key=lambda n: rows[n]["T_s"]),
                      "random_s0": "random_s0", "frozen": frozen_name}
            pis = {**cands, frozen_name: frozen}
            chain = lw.block_chain(W.cfg, S, phase, on_chip=True, max_dies=10 ** 6, dims=("M", "C"))
            n_dies = sum(e["n_dies"] for e in chain) * 32
            steps = v3.budget(n_dies)
            n_slots = fab.level("die").per_parent
            sched = sa.Schedule(t0=v3.T0_NORM, alpha=v3.ALPHA, steps=steps)
            print(f"[{cid[:28]} {phase}] pool {len(cands)} in {time.perf_counter()-t0:.0f} s | strongest {strongest} {t_base*1e3:.2f} ms | r0 {r0*100:.1f}% | frozen {fr['T_s']*1e3:.2f} ms ({(1-fr['T_s']/t_base)*100:.2f}%) | steps {steps}", flush=True)
            res = {}
            for obj in ("t_norm", "h_norm"):
                for i, (sname, cname) in enumerate(sorted(starts.items())):
                    for s in SEEDS:
                        J = cli.Objective(W, pis[cname], mu, "single", 0.4, 1.0, "t")
                        if obj == "t_norm":
                            Jn = lambda pi, J=J: J(pi) / t_base
                        else:
                            Jn = lambda pi, J=J: (J(pi) - R) / (t_base - R)
                        t1 = time.perf_counter()
                        r = sa.anneal(Jn, pis[cname], n_slots, sched, seed=1000003 * s + i)
                        e = ev(r.best_pi)
                        res[(obj, sname, s)] = e["T_s"]
                        runs.append({"case": cid, "phase": phase, "S": S, "objective": obj, "start": sname, "start_layout": cname, "seed": s, "steps": steps,
                                     "start_T_ms": ev(pis[cname])["T_s"] * 1e3, "T_ms": e["T_s"] * 1e3, "H_ms": e["H_s"] * 1e3, "gain_vs_strongest_pct": (1 - e["T_s"] / t_base) * 100,
                                     "accepted": r.accepted, "proposed": r.proposed, "wall_s": time.perf_counter() - t1})
                cold = [min(res[(obj, sn, s)] for sn in ("rule", "random_best", "random_s0")) for s in SEEDS]
                warm = [res[(obj, "frozen", s)] for s in SEEDS]
                both = [min(a, b) for a, b in zip(cold, warm)]
                g = lambda xs: (1 - statistics.median(xs) / t_base) * 100
                summ.append({"case": cid, "phase": phase, "S": S, "objective": obj, "account": status, "strongest": strongest, "T_base_ms": t_base * 1e3, "r0_pct": r0 * 100,
                             "effective_t0_on_comm": v3.T0_NORM / r0 if obj == "t_norm" else v3.T0_NORM, "steps": steps,
                             "reuse_T_ms": fr["T_s"] * 1e3, "reuse_gain_pct": (1 - fr["T_s"] / t_base) * 100,
                             "cold_T_median_ms": statistics.median(cold) * 1e3, "cold_gain_pct": g(cold), "cold_gain_min_pct": (1 - max(cold) / t_base) * 100, "cold_gain_max_pct": (1 - min(cold) / t_base) * 100,
                             "warm_T_median_ms": statistics.median(warm) * 1e3, "warm_gain_pct": g(warm), "warm_gain_min_pct": (1 - max(warm) / t_base) * 100, "warm_gain_max_pct": (1 - min(warm) / t_base) * 100,
                             "best_of_cold_and_warm_gain_pct": g(both), "cold_minus_reuse_pts": g(cold) - (1 - fr["T_s"] / t_base) * 100, "warm_minus_reuse_pts": g(warm) - (1 - fr["T_s"] / t_base) * 100})
                print(f"   {obj}: reuse {(1-fr['T_s']/t_base)*100:.2f}% | cold {g(cold):.2f}% [{(1-max(cold)/t_base)*100:.2f}, {(1-min(cold)/t_base)*100:.2f}] | warm {g(warm):.2f}% [{(1-max(warm)/t_base)*100:.2f}, {(1-min(warm)/t_base)*100:.2f}]", flush=True)
    with open(os.path.join(OUT, "runs.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(runs[0].keys())); w.writeheader(); w.writerows(runs)
    with open(os.path.join(OUT, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys())); w.writeheader(); w.writerows(summ)
    md = ["# Item 1.3: objective scale and warm start at the decode workpoint (controlled)\n",
          "Same feasible space, moves, starts, seeds (0-4) and budget; 500-fill pools at every workpoint; gains against the workpoint's strongest baseline. "
          "'t_norm' is the V3 objective T/T_base; 'h_norm' is (T-R)/(T_base-R), the same objective with the temperature rescaled by r0. "
          "'cold' = best of the three cold starts per seed, median over seeds; 'warm' = the frozen prefill-512 layout as the start (incumbent kept); 'reuse' = the frozen layout re-scored once.\n",
          "| case | phase | strongest (ms) | r0 | objective | effective t0 on the comm term | reuse | cold [min, max] | warm [min, max] | cold - reuse | warm - reuse |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in summ:
        md.append(f"| {x['case'].split('_L32')[0]} | {x['phase']} {x['S']} | {x['T_base_ms']:.1f} | {x['r0_pct']:.1f}% | {x['objective']} | {x['effective_t0_on_comm']:.4f} | {x['reuse_gain_pct']:.2f}% | "
                  f"{x['cold_gain_pct']:.2f}% [{x['cold_gain_min_pct']:.2f}, {x['cold_gain_max_pct']:.2f}] | {x['warm_gain_pct']:.2f}% [{x['warm_gain_min_pct']:.2f}, {x['warm_gain_max_pct']:.2f}] | {x['cold_minus_reuse_pts']:+.2f} | {x['warm_minus_reuse_pts']:+.2f} |")
    open(os.path.join(OUT, "summary.md"), "w").write("\n".join(md) + "\n")
    print("->", OUT)


if __name__ == "__main__":
    main()
