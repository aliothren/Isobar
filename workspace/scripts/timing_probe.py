"""Item 5 of the pre-writing checklist: platform speed and search cost,
MEASURED. Four timings, reported separately, plus the hardware:

  preprocessing   Workload2p7B construction; the seven named seatings
  full score      se.score() on the A4 seating, single caliber, GRS
  incremental     one SA step through SessionJ (propose + apply + J)
                  and the J update alone, over a 400-step burst
  whole search    one seating leg, 1200 steps, GRS and weak cells

The abstract's "microseconds" claim is decided here: whichever of these
interfaces the text means, it must be the one that measures in
microseconds -- the JSON says which does and which does not.

    python3 scripts/timing_probe.py -> analysis/timing_probe.json
"""
import json
import os
import platform
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_linkage as sl
from scripts import search_sa as sa
from scripts import search_space as ss

OUT = os.path.join(se.A, "timing_probe.json")
GRS, WEAK = 12.5, 0.4


def hardware():
    model = "unknown"
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {"cpu": model, "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "note": "single-threaded pure Python; wall-clock via time.perf_counter"}


def timed(fn, n):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append(time.perf_counter() - t)
    return {"n": n, "median_s": statistics.median(xs), "min_s": min(xs),
            "max_s": max(xs)}


def main():
    out = {"hardware": hardware()}

    t = time.perf_counter()
    W = se.Workload2p7B()
    out["preprocessing"] = {"workload_construction_s": time.perf_counter() - t}
    t = time.perf_counter()
    pis = {n: sb.generate(n, W, seed=0) for n in sl.SEATING_SEEDS}
    out["preprocessing"]["named_seatings_s"] = time.perf_counter() - t
    out["preprocessing"]["named_seatings"] = list(sl.SEATING_SEEDS)
    pi = ss.pi_from_a4_payload()

    out["full_score"] = {
        "what": "se.score(pi, W, caliber='single', d2d_gbps=12.5) on the A4 "
                "seating -- the whole-model per-op evaluation with die flows",
        **timed(lambda: se.score(pi, W, caliber="single", d2d_gbps=GRS), 12)}

    # incremental: the session that the search actually runs on
    t = time.perf_counter()
    J = sl.SessionJ(W, pis["random"], "t", GRS)
    out["incremental"] = {"session_construction_s": time.perf_counter() - t}
    import random
    rng = random.Random(7)
    n_slots = W.fab.level("die").per_parent
    cur = pis["random"]
    step_t, upd_t, n_ok = [], [], 0
    for _ in range(400):
        t0 = time.perf_counter()
        delta, _kind = sa.propose(rng, cur.seat, n_slots)
        if delta is None:
            continue
        pi2 = sa.apply_delta(cur, delta)
        t1 = time.perf_counter()
        J(pi2)
        t2 = time.perf_counter()
        step_t.append(t2 - t0)
        upd_t.append(t2 - t1)
        n_ok += 1
        cur = pi2                      # walk on, as the anneal would
    out["incremental"].update({
        "what": "one SA step = propose + apply_delta + SessionJ update, "
                "random walk of 400 steps from the random seating",
        "steps_measured": n_ok,
        "step_median_s": statistics.median(step_t),
        "step_min_s": min(step_t), "step_max_s": max(step_t),
        "j_update_median_s": statistics.median(upd_t),
        "j_update_min_s": min(upd_t),
        "steps_per_s_median": 1.0 / statistics.median(step_t),
        "full_score_over_j_update":
            out["full_score"]["median_s"] / statistics.median(upd_t)})

    # whole search: one seating leg per cell (the standing schedule)
    out["whole_search"] = {}
    for cell, bw in (("grs", GRS), ("weak", WEAK)):
        t = time.perf_counter()
        r = sl.seating_leg(W, f"timing_{cell}", "t", bw)
        dt = time.perf_counter() - t
        sched = sl.SEATING_SCHED[bw]
        out["whole_search"][cell] = {
            "wall_s": dt, "starts": len(sl.SEATING_SEEDS),
            "steps_per_start": sched.steps, "alpha": sched.alpha,
            "t0_s": sched.t0,
            "s_per_start": dt / len(sl.SEATING_SEEDS),
            "best_t_single_s": r["best_t_single_s"]}
    json.dump(out, open(OUT, "w"), indent=1)

    h = out["hardware"]
    print(f"hardware: {h['cpu']} ({h['logical_cpus']} logical), Python "
          f"{h['python']}")
    p = out["preprocessing"]
    print(f"preprocessing: workload {p['workload_construction_s']*1e3:.0f} ms; "
          f"7 named seatings {p['named_seatings_s']*1e3:.0f} ms")
    f = out["full_score"]
    print(f"full score: median {f['median_s']*1e3:.1f} ms (min {f['min_s']*1e3:.1f})")
    i = out["incremental"]
    print(f"incremental: SA step median {i['step_median_s']*1e6:.0f} us "
          f"(J update {i['j_update_median_s']*1e6:.0f} us, min "
          f"{i['j_update_min_s']*1e6:.0f} us); {i['steps_per_s_median']:.0f} "
          f"steps/s; full/incremental = {i['full_score_over_j_update']:.0f}x")
    for cell, w in out["whole_search"].items():
        print(f"whole search [{cell}]: {w['wall_s']:.1f} s for {w['starts']} "
              f"starts x {w['steps_per_start']} steps = {w['s_per_start']:.1f} "
              f"s per start")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
