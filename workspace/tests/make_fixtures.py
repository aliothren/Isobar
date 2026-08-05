"""Freeze the D8 fixtures (run once inside the container; ~10 min of mapper).

Produces:
    fixtures/ffn1_prefill_stats.txt   frozen Timeloop stats file (golden input)
    fixtures/ffn1_golden_v0.json      component energies extracted INDEPENDENTLY
                                      of perceive() (plain line scan) + op total
    fixtures/slow_golden_v1.json      v1 golden for the slow suite

The independent extraction is deliberately a different code path from
placement_aware.perceive (line scan vs regex), so the perceive tests are not
self-referential. _v0 = the uniform-traffic model; re-baseline to _v1 with a
changelog entry when TrafficExtraction (workstream B) lands.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
FIX = os.path.join(HERE, "fixtures")
os.makedirs(FIX, exist_ok=True)

import scripts.crossbar_comm as cc            # noqa: E402
from scripts import llm_workload as lw        # noqa: E402


def extract_energies_line_scan(stats_path):
    """Independent of perceive(): walk '=== name ===' sections line by line and
    sum lines that START with 'Energy (total)' (excludes the Temporal Reduction
    / Address Generation variants, which carry prefixes)."""
    out, name = {}, None
    with open(stats_path) as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("=== ") and line.endswith(" ==="):
                name = line[4:-4]
                out.setdefault(name, 0.0)
            elif name and line.startswith("Energy (total)"):
                val = line.split(":")[1].strip().split()[0]
                out[name] += float(val) * 1e-12
    return {k: v for k, v in out.items() if v > 0}


def main():
    print("=== fixture 1: ffn1 prefill (the report's reference matmul) ===")
    r = lw.run_op(lw.Op("ffn1", "static", P=512, C=1024, M=4096), phase="prefill")
    src = os.path.join(r["output_dir"], "timeloop-mapper.stats.txt")
    dst = os.path.join(FIX, "ffn1_prefill_stats.txt")
    shutil.copyfile(src, dst)
    shutil.copyfile(os.path.join(r["output_dir"], "timeloop-mapper.map.txt"),
                    os.path.join(FIX, "ffn1_prefill_map.txt"))

    energies = extract_energies_line_scan(dst)
    golden = {"op_energy_J": r["compute_J"], "component_energy_J": energies}
    with open(os.path.join(FIX, "ffn1_golden_v0.json"), "w") as f:
        json.dump(golden, f, indent=1, sort_keys=True)
    print(f"  op total {r['compute_J']:.4e} J; {len(energies)} nonzero components")
    for k in ("router", "glb", "chip2chip_link"):
        print(f"    {k:<16} {energies.get(k, 0):.4e} J")

    print("=== fixture 2: tiny 2x2 op for the slow suite (v1 structured) ===")
    r2 = lw.run_op(lw.Op("tiny2x2", "static", P=8, C=512, M=256), phase="prefill")
    _, per_xb, _, _ = cc.build_flows(r2["output_dir"], verbose=False)
    act = per_xb[per_xb > 0]
    with open(os.path.join(FIX, "slow_golden_v1.json"), "w") as f:
        json.dump({"tiny2x2_max_over_min_active":
                   float(act.max() / act.min()) if len(act) else 0.0,
                   "tiny2x2_n_active": int(len(act))}, f, indent=1)
    print(f"  tiny2x2 active={len(act)}  max/min(active) = "
          f"{(act.max()/act.min()) if len(act) else 0:.3f}")
    print("fixtures written to", FIX)


if __name__ == "__main__":
    main()