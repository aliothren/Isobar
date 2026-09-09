"""A2 day 0 (C61): the identity rerun -- the gate before the row split.

The mapper has not fired since O17c; before the split switch moves, the
frozen probe points must reproduce under untouched settings, or any
later difference cannot be attributed to the single variable. This
script re-runs d in {1024, 2560, 4096} x S=512, all six block matmuls
(18 mapper runs, column split only, O17c settings verbatim via
run_scaling_probes.run_one), into a SEPARATE file -- the frozen
scaling_probes.json is read, never written -- and compares per (d, op).

JUDGMENT (amendment 3, pre-registered): three tiers.
  EXACT  bitwise equal.
  NOISE  float fields, relative drift <= 1e-9 (the fast suite's
         standing tight tolerance -- no new convention): recorded as
         mechanical noise, NOT a blocker.
  DRIFT  anything beyond, or ANY structural mismatch (dies, split,
         piece shapes, policy, bottleneck resource/direction):
         verdict STOP -- A2 suspends, the drift becomes its own item.

Usage (container): python3 scripts/a2_identity_rerun.py
Output: analysis/a2_identity_rerun.json (resumable like the probe
runner: finished ops are skipped on restart).
"""
import json
import os
import sys

sys.path.insert(0, "/home/workspace")
os.environ.setdefault("CIMSIM_FABRIC",
                      "/home/workspace/models/fabric/mlx300_multidie48.yaml")

import dataclasses

from scripts import llm_workload as lw
from scripts import mlx_system as mlx
from scripts import placement as pm
from scripts.run_scaling_probes import MATMUL, REF_WC, cfg_of, run_one

OUT = "/home/workspace/analysis"
FROZEN = os.path.join(OUT, "scaling_probes.json")
OUT_JSON = os.path.join(OUT, "a2_identity_rerun.json")
D_POINTS = [1024, 2560, 4096]
S = 512
NOISE_REL = 1e-9

STRUCT_FIELDS = ("kind", "policy", "P", "C", "M", "N", "dies", "split",
                 "piece_C", "piece_M")
FLOAT_FIELDS = ("compute_s", "write_s", "cycle_s", "ondie_serial_ref_s",
                "serial_over_compute")


def _rel(a, b):
    if a == b:
        return 0.0
    if a is None or b is None:
        return float("inf")
    m = max(abs(a), abs(b))
    return abs(a - b) / m if m else 0.0


def compare(frozen_op, new_op):
    """-> (tier, details): tier in EXACT | NOISE | DRIFT."""
    issues, worst = [], 0.0
    for f in STRUCT_FIELDS:
        if frozen_op.get(f) != new_op.get(f):
            issues.append(f"STRUCT {f}: {frozen_op.get(f)} -> {new_op.get(f)}")
    fb, nb = frozen_op["bottleneck"], new_op["bottleneck"]
    for f in ("resource", "direction"):
        if fb.get(f) != nb.get(f):
            issues.append(f"STRUCT bottleneck.{f}: {fb.get(f)} -> {nb.get(f)}")
    if issues:
        return "DRIFT", issues
    pairs = [(f, frozen_op.get(f), new_op.get(f)) for f in FLOAT_FIELDS]
    pairs += [(f"bottleneck.{f}", fb.get(f), nb.get(f))
              for f in ("volume", "seconds")]
    fe = {e["node"]: e for e in frozen_op["macro_edges"]}
    ne = {e["node"]: e for e in new_op["macro_edges"]}
    if set(fe) != set(ne):
        return "DRIFT", [f"macro_edges nodes {sorted(fe)} -> {sorted(ne)}"]
    for n in fe:
        for f in ("down", "up", "volume"):
            pairs.append((f"edge{n}.{f}", fe[n][f], ne[n][f]))
    for name, a, b in pairs:
        r = _rel(a, b)
        worst = max(worst, r)
        if r > NOISE_REL:
            issues.append(f"DRIFT {name}: {a} -> {b} (rel {r:.3e})")
    if issues:
        return "DRIFT", issues
    return ("EXACT" if worst == 0.0 else "NOISE"), [f"worst rel {worst:.3e}"]


def main():
    frozen = json.load(open(FROZEN))
    fz = {(p["d"], p["S"]): {o["name"]: o for o in p["ops"]}
          for p in frozen["points"]}

    done = {}
    if os.path.exists(OUT_JSON):
        old = json.load(open(OUT_JSON))
        done = {(r["d"], r["op"]): r for r in old.get("runs", [])}
        if done:
            print(f"resuming: {len(done)} finished reruns found", flush=True)

    fab = mlx.FABRIC
    max_dies = fab.level("die").per_parent
    fab_bw = dataclasses.replace(fab, levels=[
        dataclasses.replace(l, link=dataclasses.replace(
            l.link, bandwidth_words_per_cycle=REF_WC))
        if l.name == "macro" else l for l in fab.levels]).validate()
    pl = pm.sequential_fill(fab)
    pl_bw = pm.sequential_fill(fab_bw)

    runs = [r for r in done.values()]
    n, total = 0, len(D_POINTS) * len(MATMUL)
    for d in D_POINTS:
        cfg = cfg_of(d)
        ops = {o.name: o for o in lw.block_ops(cfg, S=S, phase="prefill")}
        for name in MATMUL:
            n += 1
            if (d, name) in done:
                print(f"[{n}/{total}] d={d} {name}: already rerun, skip",
                      flush=True)
                continue
            print(f"[{n}/{total}] d={d} {name}: mapper...", flush=True)
            new_op = run_one(ops[name], fab, fab_bw, pl, pl_bw, max_dies)
            tier, details = compare(fz[(d, S)][name], new_op)
            runs.append({"d": d, "op": name, "tier": tier,
                         "details": details, "rerun": new_op})
            print(f"    -> {tier}  {details[:2]}", flush=True)
            with open(OUT_JSON, "w") as f:
                json.dump({"noise_rel": NOISE_REL, "runs": runs}, f, indent=1)

    tiers = [r["tier"] for r in runs]
    verdict = ("STOP -- A2 SUSPENDS (drift is its own item)"
               if "DRIFT" in tiers else "PASS")
    summary = {"noise_rel": NOISE_REL,
               "counts": {t: tiers.count(t) for t in ("EXACT", "NOISE",
                                                      "DRIFT")},
               "verdict": verdict, "runs": runs}
    with open(OUT_JSON, "w") as f:
        json.dump(summary, f, indent=1)
    print(f"\nday-0 verdict: {verdict}  "
          f"(EXACT {tiers.count('EXACT')}, NOISE {tiers.count('NOISE')}, "
          f"DRIFT {tiers.count('DRIFT')} of {len(tiers)})")
    for r in runs:
        if r["tier"] != "EXACT":
            print(f"  {r['tier']}: d={r['d']} {r['op']} {r['details'][:3]}")


if __name__ == "__main__":
    main()
