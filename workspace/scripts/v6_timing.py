"""Follow-up P1 (section 8): platform timing of the offload backend on the
current configurations of the reference 2.7B, OPT-6.7B, Gemma-7B and
OPT-13B (central unit, prefill 512): initialisation (account load,
workload build, session build), full evaluation, incremental update on a
fixed exchange sequence, parameter re-pricing from stored components,
and a fixed-budget search. Repeated runs give medians and p10 / p90;
initialisation and steady state are separate; the environment and the
load are recorded. Run at a stable load.

    python3 scripts/v6_timing.py [--repeats 7] [--moves 200]
      -> analysis/v6/runtime_samples.csv, runtime_summary.csv, runtime_environment.json
"""
import argparse
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
from scripts import cimsim_cli as cli                    # noqa: E402
from scripts import search_sa as sa                      # noqa: E402
from scripts import search_space as ss                   # noqa: E402
from scripts import v3_sweep as v3                       # noqa: E402
from scripts import v6_common as C                       # noqa: E402

CASES = [("e9_confirm", "ref2p7b_prefill512_colrow_24x24_mesh_xy_k2_b0.4_offcenterK1"), ("e9_confirm", "opt6.7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"),
         ("e9_confirm", "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"), ("e9_confirm", "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1")]


def q(xs, p):
    xs = sorted(xs); k = (len(xs) - 1) * p; f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--repeats", type=int, default=7); ap.add_argument("--moves", type=int, default=200); args = ap.parse_args()
    samples, summary = [], []
    env = {"cpu": platform.processor() or open("/proc/cpuinfo").read().split("model name")[1].split(":")[1].split("\n")[0].strip(), "python": sys.version.split()[0], "threads": 1,
           "load_average_at_start": os.getloadavg(), "code_version": __import__("subprocess").check_output(["git", "-C", os.path.dirname(WS), "rev-parse", "--short", "HEAD"], text=True).strip(),
           "note": "single-threaded pure Python; perf_counter wall clock; load from other users' processes is reported, not controlled"}
    for unit, cid in CASES:
        rec = C.find_record(unit, cid); phase = rec["spec"]["phase"]; bw = float(rec["spec"]["bw"])
        # initialisation
        t0 = time.perf_counter(); W = C.workload_from_record(rec); t_init = time.perf_counter() - t0
        pi = ss.Pi.from_json(rec["search"]["runs"][rec["search"]["headline"]]["best_pi"])
        t0 = time.perf_counter(); J = cli.Objective(W, pi, {phase: 1.0}, "single", bw, 1.0, "t"); t_sess = time.perf_counter() - t0
        n_flows = sum(len(fl) for _, fl in cli.handoff_flows(W, pi, phase)); n_stages = len(J.sess.bs[phase])
        path_len = sum(b["max_hops"] for b in J.sess.bs[phase])
        # full evaluation
        full = []
        for _ in range(args.repeats):
            t0 = time.perf_counter(); C.se.score(pi, W, mu={phase: 1.0}, d2d_gbps=bw); full.append(time.perf_counter() - t0)
        # incremental on a fixed exchange sequence (the same sequence every repeat; the session is rebuilt per repeat)
        rng = random.Random(7); seq = []
        n_slots = W.usable_slots()
        cur = pi
        for _ in range(args.moves):
            delta, kind = sa.propose(rng, cur.seat, n_slots, ("exchange", "migrate"))
            if delta:
                seq.append(delta); cur = sa.apply_delta(cur, delta)
        inc, inc_consistency = [], []
        for _ in range(args.repeats):
            J = cli.Objective(W, pi, {phase: 1.0}, "single", bw, 1.0, "t"); cur = pi
            t0 = time.perf_counter()
            for delta in seq:
                cur = sa.apply_delta(cur, delta); J(cur)
            inc.append((time.perf_counter() - t0) / len(seq))
        # consistency of the incremental against the full at the end of the sequence
        inc_consistency.append(abs(J(cur) - C.se.score(cur, W, mu={phase: 1.0}, d2d_gbps=bw).t_opt_s) / J(cur))
        # parameter re-pricing from stored components (one grid point over the saved library)
        rep = []
        lib = rec["candidates"]
        for _ in range(args.repeats):
            t0 = time.perf_counter()
            Ch = rec["attention"]["unit"]["link_bandwidth_gbps"] * 1e9
            for n, row in lib.items():
                sum(max(max(l, dp) / (0.8e9), h / Ch) for l, dp, h in row["comp"])
            rep.append((time.perf_counter() - t0) / len(lib))
        # fixed-budget search
        steps = v3.budget(rec["n_dies"]); search = []
        for s in range(3):
            J = cli.Objective(W, pi, {phase: 1.0}, "single", bw, 1.0, "t")
            t0 = time.perf_counter(); r = sa.anneal(lambda p: J(p) / rec["T_base_s"], pi, n_slots, sa.Schedule(t0=v3.T0_NORM, alpha=v3.ALPHA, steps=steps), seed=s)
            search.append({"wall_s": time.perf_counter() - t0, "steps": steps, "evaluations": J.calls, "proposed": r.proposed})
        for i, (f, g) in enumerate(zip(full, inc)):
            samples.append({"config_id": cid, "repeat": i, "init_s": t_init if i == 0 else "", "session_build_s": t_sess if i == 0 else "", "full_eval_s": f, "incremental_per_move_s": g, "repricing_per_candidate_s": rep[i]})
        for s_ in search:
            samples.append({"config_id": cid, "repeat": "search", "init_s": "", "session_build_s": "", "full_eval_s": "", "incremental_per_move_s": "", "repricing_per_candidate_s": "", **s_})
        summary.append({"config_id": cid, "n_dies": rec["n_dies"], "n_flows": n_flows, "n_stages": n_stages, "path_total_hops": path_len, "init_s": t_init, "session_build_s": t_sess,
                        "full_eval_median_s": statistics.median(full), "full_eval_p10_s": q(full, .1), "full_eval_p90_s": q(full, .9),
                        "incremental_median_s": statistics.median(inc), "incremental_p10_s": q(inc, .1), "incremental_p90_s": q(inc, .9), "incremental_relative_error": max(inc_consistency), "full_over_incremental_speedup": statistics.median(full) / statistics.median(inc),
                        "repricing_per_candidate_median_s": statistics.median(rep), "search_steps": steps, "search_wall_median_s": statistics.median(x["wall_s"] for x in search),
                        "search_evaluations": search[0]["evaluations"], "load_average": os.getloadavg()})
        print(f"{cid[:48]:48s} dies {rec['n_dies']} flows {n_flows} | init {t_init:.2f} s sess {t_sess:.2f} s | full {statistics.median(full)*1e3:.1f} ms | inc {statistics.median(inc)*1e3:.2f} ms | reprice {statistics.median(rep)*1e6:.0f} us/cand | search {steps} steps {statistics.median(x['wall_s'] for x in search):.1f} s | load {os.getloadavg()[0]:.1f}", flush=True)
    os.makedirs(C.V6, exist_ok=True)
    keys = []
    for s in samples:
        for k in s:
            if k not in keys:
                keys.append(k)
    with open(os.path.join(C.V6, "runtime_samples.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(samples)
    with open(os.path.join(C.V6, "runtime_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys())); w.writeheader(); w.writerows(summary)
    env["load_average_at_end"] = os.getloadavg()
    json.dump(env, open(os.path.join(C.V6, "runtime_environment.json"), "w"), indent=1)
    print("->", C.V6)


if __name__ == "__main__":
    main()
