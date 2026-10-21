"""Fig. 3(d): best-so-far communication cost against wall-clock time for one
representative search per configuration. The confirmed runs (analysis_v4
e9_confirm) kept only their endpoints, so each configuration's headline run
is re-executed exactly -- same start layout, same annealer seed, same budget
and the same H-normalised objective (T - R) / (T_base - R) -- with every
objective evaluation timestamped. The re-run must reproduce the recorded
endpoint (checked); the timing is a fresh single-threaded measurement.

    python3 scripts/v7_search_trajectory.py
      -> analysis/v7/search_trajectories.csv, search_trajectories.json
"""
import csv
import json
import os
import platform
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import cimsim_cli as cli                    # noqa: E402
import importlib.util, subprocess                        # noqa: E402
# the annealer exactly as the confirmation batch ran it (b9e5416, 2026-10-15):
# its acceptance test drew a random number for zero-change moves, the current
# one does not, so the current code walks a different random stream
_SA_REV = "b9e5416"
_src = subprocess.check_output(["git", "-C", os.path.dirname(WS), "show",
                                f"{_SA_REV}:workspace/scripts/search_sa.py"], text=True)
_spec = importlib.util.spec_from_loader("search_sa_e9", loader=None)
sa = importlib.util.module_from_spec(_spec)
sa.__file__ = os.path.join(WS, "scripts", "search_sa.py")
exec(compile(_src, f"search_sa.py@{_SA_REV}", "exec"), sa.__dict__)
from scripts import v3_sweep as v3                       # noqa: E402
from scripts import v6_common as C                       # noqa: E402

CASES = [("ref2p7b_prefill512_colrow_24x24_mesh_xy_k2_b0.4_offcenterK1", "2.7B ref."),
         ("opt6.7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1", "OPT-6.7B"),
         ("gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1", "Gemma-7B"),
         ("opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1", "OPT-13B")]
OUT = os.path.join(WS, "analysis", "v7")


def main():
    rows, summary = [], {}
    env = {"cpu": open("/proc/cpuinfo").read().split("model name")[1].split(":")[1].split("\n")[0].strip(),
           "python": sys.version.split()[0], "threads": 1, "load_average_at_start": os.getloadavg()}
    for cid, model in CASES:
        rec = C.find_record("e9_confirm", cid)
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
        sched = sa.Schedule(t0=v3.T0_NORM, alpha=v3.ALPHA, steps=s["steps"])
        J = cli.Objective(W, pi0, mu, "single", bw, 1.0, "t")
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
                        "annealer_revision": _SA_REV}
        print(f"{model:10s} {rec['n_dies']} dies  {s['steps']} steps  wall {wall:.1f} s (recorded {head['wall_s']:.1f})  "
              f"best H/H_base {r.best_j:.4f}  reproduces {rel:.1e}", flush=True)
    env["load_average_at_end"] = os.getloadavg()
    with open(os.path.join(OUT, "search_trajectories.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    json.dump({"note": __doc__, "environment": env, "runs": summary},
              open(os.path.join(OUT, "search_trajectories.json"), "w"), indent=1)
    print("->", OUT)


if __name__ == "__main__":
    main()
