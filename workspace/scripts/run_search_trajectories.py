"""Fig. 3(d) data: best-so-far communication cost against wall-clock time
for one representative search per reference deployment. The records keep
only the search endpoints, so each configuration's representative run is
re-executed exactly (same start layout, annealer seed, budget, annealer
setting and the communication objective (T - R) / (T_base - R)) with every
objective evaluation timestamped. The re-run must reproduce the recorded
endpoint (checked); the timing is a fresh single-threaded measurement.

    python3 scripts/run_search_trajectories.py
      -> results/exports/search_trajectories.csv, search_trajectories.json
"""
import csv
import json
import os
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import experiment as v3                    # noqa: E402
from scripts import export_common as V                  # noqa: E402
from scripts import objective as ob                     # noqa: E402
from scripts import records as C                        # noqa: E402
from scripts import search_sa as sa                     # noqa: E402

CASES = [("ref2p7b_prefill512_colrow_24x24_mesh_xy_k2_b0.4_offcenterK1", "2.7B ref."),
         ("opt6.7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1", "OPT-6.7B"),
         ("gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1", "Gemma-7B"),
         ("opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1", "OPT-13B")]
OUT = V.EXPORTS


def main():
    rows, summary = [], {}
    env = {"cpu": open("/proc/cpuinfo").read().split("model name")[1].split(":")[1].split("\n")[0].strip(),
           "python": sys.version.split()[0], "threads": 1, "load_average_at_start": os.getloadavg()}
    for cid, model in CASES:
        rec = C.find_record("reference", cid)
        s = rec["search"]; assert s["objective"] == "h_norm"
        head = s["runs"][s["headline"]]
        phase, bw = rec["spec"]["phase"], float(rec["spec"]["bw"])
        mu = {phase: 1.0}
        W = C.workload_from_record(rec)
        start = head["start_layout"]
        pi0 = C.candidate_layout(W, start)
        i = [k for k, _ in sorted(s["starts"].items())].index(head["start"])
        seed = 1000003 * head["sa_seed"] + i
        t_base, R = rec["T_base_s"], rec["N_s"] + rec["F_s"]
        n_slots = W.usable_slots()
        sched = sa.Schedule(t0=v3.T0_NORM, alpha=v3.ALPHA, steps=s["steps"], tie_draw=bool(rec["spec"].get("sa_tie_draw", True)))
        J = ob.Objective(W, pi0, mu, "single", bw, 1.0, "t")
        trace = []
        t_start = [None]

        def Jn(pi):
            v = (J(pi) - R) / (t_base - R)
            trace.append((time.perf_counter() - t_start[0], v))
            return v
        t_start[0] = time.perf_counter()
        r = sa.anneal(Jn, pi0, n_slots, sched, seed=seed)
        wall = time.perf_counter() - t_start[0]
        T_end = r.best_j * (t_base - R) + R
        rel = abs(T_end - head["T_s"]) / head["T_s"]
        assert rel < 1e-9, (cid, T_end, head["T_s"])
        best = float("inf")
        for k, (t, v) in enumerate(trace):
            best = min(best, v)
            rows.append({"config_id": cid, "model": model, "n_dies": rec["n_dies"], "steps": s["steps"],
                         "run": s["headline"], "eval_index": k, "t_s": t, "J_norm": v, "best_norm": best})
        summary[cid] = {"model": model, "n_dies": rec["n_dies"], "run": s["headline"], "start_layout": start,
                        "sa_seed": head["sa_seed"], "anneal_seed": seed, "steps": s["steps"], "evaluations": len(trace),
                        "wall_s": wall, "recorded_wall_s": head["wall_s"], "best_norm": r.best_j,
                        "T_end_s": T_end, "recorded_T_s": head["T_s"], "reproduction_rel_err": rel,
                        "strongest_baseline": rec["strongest"], "T_base_s": t_base, "R_s": R,
                        "tie_draw": sched.tie_draw}
        print(f"{model:10s} {rec['n_dies']} dies  {s['steps']} steps  wall {wall:.1f} s (recorded {head['wall_s']:.1f})  "
              f"best H/H_base {r.best_j:.4f}  reproduces {rel:.1e}", flush=True)
    env["load_average_at_end"] = os.getloadavg(); env["code_version"] = V.code_version()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "search_trajectories.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    json.dump({"note": __doc__, "environment": env, "runs": summary},
              open(os.path.join(OUT, "search_trajectories.json"), "w"), indent=1)
    print("->", OUT)


if __name__ == "__main__":
    main()
