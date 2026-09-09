"""A2 days 3-4 (C61): the row-split scan -- forced C splits on the main path.

Pre-registration: FIXLIST O15, A2 EXECUTION (day-2 concretization). All
readouts land HERE (a NEW file, field row_split); scaling_probes.json is
frozen and never written.

MATRIX
  (a) natural spans, forced-C: d in {2560, 4096, 5120, 6144, 8192} x
      {qkv_proj, out_proj, ffn1, ffn2}, S = 512. A (d, op) with no
      feasible C-only tiling is a RESULT (feasibility-frontier row).
  (b) S weld pair: (2560, ffn2, S=128) -- ratios must be S-free.
  (c) the replication-alternative probe: d = 1024, VOLUNTARY 2-die C:2
      (probe knob min_dies=2; capacity still rules the floor elsewhere).

PER RUN, the two P1 lines (amendment 1: each level judged on its own):
  die line    psum-dominated iff 2 x up > down on the die edge
              (closed form: 2 M n > C; ffn2 at n=2 is an exact tie).
  macro line  psum iff 2 x out > in on the macro edge (the mapping's
              factors m_C, m_M recorded alongside).
Plus the probe-standard fields (run_one) so every row is comparable to
the frozen column-split rows.

Usage (container): python3 scripts/run_a2_row_split.py
Output: analysis/a2_row_split.json (resumable)
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
from scripts import traffic
from scripts.run_scaling_probes import REF_WC, cfg_of, run_one

OUT = "/home/workspace/analysis"
OUT_JSON = os.path.join(OUT, "a2_row_split.json")
FROZEN = os.path.join(OUT, "scaling_probes.json")

D_NATURAL = [2560, 4096, 5120, 6144, 8192]
STATICS = ("qkv_proj", "out_proj", "ffn1", "ffn2")


def matrix():
    pts = [(d, 512, op, None) for d in D_NATURAL for op in STATICS]
    pts.append((2560, 128, "ffn2", None))            # the S weld pair
    pts += [(1024, 512, op, 2) for op in STATICS]    # voluntary C:2
    return pts


def line_verdicts(res_dir, d, op):
    """The two P1 lines + the mapping's macro factors, from extraction."""
    ts = traffic.extract(res_dir)
    ev = ts.edge_volumes()
    out = {}
    die = next((s for s in ts.splits if s.level == "die"), None)
    if die is not None and "die" in ev:
        dn, up = ev["die"]["in"], ev["die"]["out"]
        out["die_line"] = {
            "down_words": dn, "up_words": up,
            "psum_dominated": 2 * up > dn,
            "tie": 2 * up == dn,
            "closed_form_2Mn_vs_C": {"2Mn": 2 * op.M * die.fanout,
                                     "C": op.C},
            "die_factors": dict(die.factors)}
    mac = next((s for s in ts.splits if s.level == "macro"), None)
    if mac is not None:
        dn, up = ev["macro"]["in"], ev["macro"]["out"]
        out["macro_line"] = {
            "down_words": dn, "up_words": up,
            "psum_dominated": 2 * up > dn,
            "tie": 2 * up == dn,
            "macro_factors": dict(mac.factors)}
    return out


def main():
    done = {}
    if os.path.exists(OUT_JSON):
        old = json.load(open(OUT_JSON))
        done = {(r["d"], r["S"], r["op"]): r for r in old.get("rows", [])}
        if done:
            print(f"resuming: {len(done)} rows found", flush=True)

    fab = mlx.FABRIC
    max_dies = fab.level("die").per_parent
    fab_bw = dataclasses.replace(fab, levels=[
        dataclasses.replace(l, link=dataclasses.replace(
            l.link, bandwidth_words_per_cycle=REF_WC))
        if l.name == "macro" else l for l in fab.levels]).validate()
    pl = pm.sequential_fill(fab)
    pl_bw = pm.sequential_fill(fab_bw)

    frozen = json.load(open(FROZEN))
    col = {(p["d"], p["S"]): {o["name"]: o for o in p["ops"]}
           for p in frozen["points"]}

    rows = list(done.values())
    pts = matrix()
    for i, (d, S, name, min_dies) in enumerate(pts, 1):
        if (d, S, name) in done:
            print(f"[{i}/{len(pts)}] d={d} S={S} {name}: done, skip",
                  flush=True)
            continue
        cfg = cfg_of(d)
        op = {o.name: o for o in lw.block_ops(cfg, S=S,
                                              phase="prefill")}[name]
        tag = f"[{i}/{len(pts)}] d={d} S={S} {name} (C={op.C} M={op.M}" \
              + (f", voluntary min_dies={min_dies})" if min_dies else ")")
        # feasibility first (closed form, no mapper)
        try:
            n, dim, _ = lw.plan_spatial(op, max_dies=max_dies, dims=("C",),
                                        min_dies=min_dies)
        except ValueError as e:
            print(f"{tag}: INFEASIBLE under C-only -- recorded", flush=True)
            rows.append({"d": d, "S": S, "op": name, "row_split": True,
                         "feasible": False, "reason": str(e)})
            _dump(rows)
            continue
        print(f"{tag} -> {n} die(s), split={dim}; mapper...", flush=True)
        rec = run_one(op, fab, fab_bw, pl, pl_bw, max_dies,
                      dims=("C",), min_dies=min_dies)
        rec.update({"d": d, "S": S, "op": name, "row_split": True,
                    "feasible": True, "voluntary_min_dies": min_dies})
        rec["lines"] = line_verdicts(rec["output_dir"], d, op)
        rows.append(rec)
        _dump(rows)
        col_row = col.get((d, S), {}).get(name)
        if col_row:
            print(f"    row_split serial/compute "
                  f"{rec['serial_over_compute']:.4f} vs column "
                  f"{col_row['serial_over_compute']:.4f}; bottleneck "
                  f"{rec['bottleneck']['direction']} vs "
                  f"{col_row['bottleneck']['direction']}", flush=True)
    _dump(rows)
    print("scan complete:", len(rows), "rows")


def _dump(rows):
    with open(OUT_JSON, "w") as f:
        json.dump({"regime": "residency tiler, ROW SPLIT (C) forced at the "
                             "die level (A2/C61); prefill; new rows only -- "
                             "the frozen column-split probes are untouched",
                   "rows": rows}, f, indent=1)


if __name__ == "__main__":
    main()
