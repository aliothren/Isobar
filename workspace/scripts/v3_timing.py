"""V3 E5: controlled evaluation timing versus instance size (2026-10-08).

Instances: the 2.7B-class block chain at depths L (17 L dies on the
smallest near-square grid) and the width family at L = 32; single-threaded,
warm-up first, then repeats; medians and percentiles. Timing scopes:
  account_load      reading the per-operator account JSON (the mapper's
                    output; the mapper run itself is NOT timed here)
  workload_build    V3Workload construction (fabric, placement, interconnect)
  traffic_extract   the logical hand-off flows of one placement
                    (cimsim_cli.handoff_flows: block chain + R-split flows)
  loads_build       routing and accumulating every flow's loads (resource_loads
                    over all hand-offs)
  full_score        search_eval.score on a fixed candidate (30 repeats; 100 when n_dies <= 128)
  incremental       ScoreSession.update over 200 legal moves drawn by the
                    annealer's proposal (per move family)
  consistency       incremental == full on 20 sampled moves (max relative error)
  search            one anneal of budget M(n) including session construction
    python3 scripts/v3_timing.py -> analysis/v3/e5/timing.json, timing.csv
"""
import csv
import json
import os
import platform
import random
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
from scripts import v3_sweep as v3               # noqa: E402

OUT = os.path.join(WS, "analysis", "v3", "e5")
BW = 0.4


def pct(xs, q):
    xs = sorted(xs); k = (len(xs) - 1) * q; f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def summarize(xs):
    return {"n": len(xs), "median_ms": statistics.median(xs) * 1e3, "p10_ms": pct(xs, 0.1) * 1e3,
            "p90_ms": pct(xs, 0.9) * 1e3, "min_ms": min(xs) * 1e3, "max_ms": max(xs) * 1e3}


def time_instance(spec):
    d, dh, dff, L, S = spec["d"], spec["dh"], spec["d_ff"], spec["L"], 512
    t = time.perf_counter()
    acc_path = os.path.join(WS, "analysis", "v3", "accounts", f"d{d}_dh{dh}_ff{dff}_S{S}.json")
    if d == 2560 and dh == 80 and dff == 10240:
        acc_path = os.path.join(WS, "analysis", "scale_2p7b_per_op.json")
    account = json.load(open(acc_path)); account["config"]["n_layers"] = L
    t_acc = time.perf_counter() - t
    cfg = lw.GptConfig(d_model=d, n_heads=d // dh, d_ff=dff, n_layers=L)
    chain = lw.block_chain(cfg, S, "prefill", on_chip=True, max_dies=10 ** 6)
    n_dies = sum(e["n_dies"] for e in chain) * L
    grid = v3.grid_for(n_dies, 1.0)
    t = time.perf_counter()
    W = v3.V3Workload(v3.make_fabric(grid), account); W.port_ratio = 2.0
    t_build = time.perf_counter() - t
    mu = {"prefill": 1.0}
    pi = sb.generate("random", W, seed=0)
    # traffic extraction and loads
    xs = []
    for _ in range(10):
        t = time.perf_counter(); hs = cli.handoff_flows(W, pi, "prefill"); xs.append(time.perf_counter() - t)
    t_extract = summarize(xs)
    n_flows = sum(len(fl) for _, fl in hs)
    xs = []
    for _ in range(10):
        t = time.perf_counter()
        for _, fl in hs:
            se.resource_loads(fl, W.die_ic, ports=True, kappa=2.0)
        xs.append(time.perf_counter() - t)
    t_loads = summarize(xs)
    # full score
    reps = 100 if n_dies <= 128 else 30
    se.score(pi, W, mu=mu, d2d_gbps=BW)                      # warm-up
    xs = []
    for _ in range(reps):
        t = time.perf_counter(); se.score(pi, W, mu=mu, d2d_gbps=BW); xs.append(time.perf_counter() - t)
    t_full = summarize(xs)
    # incremental
    t = time.perf_counter(); sess = se.ScoreSession(pi, W, mu=mu, d2d_gbps=BW); t_sess = time.perf_counter() - t
    rng = random.Random(7)
    n_slots = W.fab.level("die").per_parent
    per_kind = {}
    cons_err = 0.0
    cur = pi
    for i in range(200):
        delta, kind = sa.propose(rng, cur.seat, n_slots)
        if delta is None:
            continue
        t = time.perf_counter(); sc = sess.update(delta); dt = time.perf_counter() - t
        per_kind.setdefault(kind, []).append(dt)
        cur = sess.pi
        if i % 10 == 0:
            full = se.score(cur, W, mu=mu, d2d_gbps=BW)
            cons_err = max(cons_err, abs(full.t_opt_s - sc.t_opt_s) / full.t_opt_s)
    t_inc = {k: summarize(v) for k, v in per_kind.items()}
    all_inc = [x for v in per_kind.values() for x in v]
    # one search at the budget rule
    steps = v3.budget(n_dies)
    J = cli.Objective(W, pi, mu, "single", BW, 1.0, "t")
    t = time.perf_counter(); sa.anneal(lambda p: J(p), pi, n_slots, sa.Schedule(t0=0.02, alpha=0.996, steps=steps), seed=1); t_search = time.perf_counter() - t
    return {"d": d, "dh": dh, "d_ff": dff, "L": L, "n_dies": n_dies, "grid": grid, "n_handoffs": len(hs), "n_flows": n_flows,
            "account_load_ms": t_acc * 1e3, "workload_build_ms": t_build * 1e3, "traffic_extract": t_extract,
            "loads_build": t_loads, "full_score": t_full, "session_build_ms": t_sess * 1e3,
            "incremental_all": summarize(all_inc), "incremental_by_move": t_inc, "consistency_max_rel_err": cons_err,
            "search_steps": steps, "search_wall_s": t_search, "search_ms_per_step": t_search / steps * 1e3,
            "full_over_incremental": t_full["median_ms"] / summarize(all_inc)["median_ms"]}


def main():
    os.makedirs(OUT, exist_ok=True)
    specs = [{"d": 2560, "dh": 80, "d_ff": 10240, "L": L} for L in (1, 2, 4, 8, 16, 32, 48, 64, 128)]
    fam = [(512, 64, 2048), (1024, 64, 4096), (1536, 64, 6144), (2048, 64, 8192), (3072, 64, 12288), (4096, 64, 16384)]
    for d, dh, ff in fam:
        if os.path.exists(os.path.join(WS, "analysis", "v3", "accounts", f"d{d}_dh{dh}_ff{ff}_S512.json")):
            specs.append({"d": d, "dh": dh, "d_ff": ff, "L": 32})
    out = {"environment": {"cpu": platform.processor() or open("/proc/cpuinfo").read().split("model name")[1].split("\n")[0].strip(": \t"),
                           "python": platform.python_version(), "platform": platform.platform(),
                           "load_average_at_start": os.getloadavg(), "note": "single-threaded pure Python; perf_counter wall clock"},
           "instances": []}
    for s in specs:
        print(s, flush=True)
        r = time_instance(s)
        out["instances"].append(r)
        print(f"   {r['n_dies']} dies, {r['n_flows']} flows: full {r['full_score']['median_ms']:.1f} ms | inc {r['incremental_all']['median_ms']:.2f} ms | "
              f"search {r['search_steps']} steps {r['search_wall_s']:.1f} s | consistency {r['consistency_max_rel_err']:.1e}", flush=True)
        json.dump(out, open(os.path.join(OUT, "timing.json"), "w"), indent=1)
    with open(os.path.join(OUT, "timing.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["d", "dh", "d_ff", "L", "n_dies", "grid", "n_handoffs", "n_flows", "account_load_ms", "workload_build_ms",
                    "traffic_extract_ms", "loads_build_ms", "full_score_median_ms", "full_p10_ms", "full_p90_ms", "session_build_ms",
                    "incremental_median_ms", "inc_p10_ms", "inc_p90_ms", "consistency_max_rel_err", "search_steps", "search_wall_s",
                    "search_ms_per_step", "full_over_incremental"])
        for r in out["instances"]:
            w.writerow([r["d"], r["dh"], r["d_ff"], r["L"], r["n_dies"], "x".join(map(str, r["grid"])), r["n_handoffs"], r["n_flows"],
                        f"{r['account_load_ms']:.2f}", f"{r['workload_build_ms']:.2f}", f"{r['traffic_extract']['median_ms']:.2f}",
                        f"{r['loads_build']['median_ms']:.2f}", f"{r['full_score']['median_ms']:.2f}", f"{r['full_score']['p10_ms']:.2f}",
                        f"{r['full_score']['p90_ms']:.2f}", f"{r['session_build_ms']:.2f}", f"{r['incremental_all']['median_ms']:.3f}",
                        f"{r['incremental_all']['p10_ms']:.3f}", f"{r['incremental_all']['p90_ms']:.3f}", f"{r['consistency_max_rel_err']:.2e}",
                        r["search_steps"], f"{r['search_wall_s']:.1f}", f"{r['search_ms_per_step']:.3f}", f"{r['full_over_incremental']:.1f}"])
    print("->", OUT)


if __name__ == "__main__":
    main()
