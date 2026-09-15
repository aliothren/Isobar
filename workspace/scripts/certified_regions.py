"""A1: the CERTIFIED three-region classification -- the region-semantics
data layer behind the phase diagram's figure.

Per cell (device tier x link bandwidth) the communication and compute
terms of the 2.7B payload are compared under the BRACKET's two rails:

  certified compute-dominant   even the PESSIMISTIC communication rail
                               sits below compute
  certified communication-bound  even the OPTIMISTIC rail sits above it
  uncertain                    the rails straddle compute

Declared in advance (and reproduced here as a check, not a discovery):
on production, packet-free weaves the two rails COINCIDE -- the packet
toll is zero, Delta == 1.00 by construction -- so the uncertain band
has width zero and every production cell classifies outright. A middle
band exists only on packet-declared (Simba-class) fabrics, and the
last section of this script demonstrates one.

Communication here is the die-level hand-off term under the corrected
accounting (busiest-link volume / link rate, plus propagation);
compute is the layer stack's compute + write + elementwise terms at
the cell's device scale. Both come from score()'s own decomposition,
so the classification cannot disagree with the evaluator.

    python3 scripts/certified_regions.py -> analysis/certified_regions.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_space as ss

TIERS = (("NeuRRAM", 10.14), ("Mythic", 6.38), ("ISAAC", 1.6),
         ("HERMES", 0.133))
BWS = (0.1, 0.2, 0.4, 2.0, 8.0, 12.5)
OUT = os.path.join(se.A, "certified_regions.json")


def rails(W, pi, phase, bw, scale):
    """(optimistic comm, pessimistic comm, compute) seconds for one cell.
    The rails are score()'s own optimistic/pessimistic ends; the packet
    toll is the only thing that separates them."""
    sc = se.score(pi, W, mu={phase: 1.0}, caliber="single", d2d_gbps=bw,
                  device_scale=scale)
    d = sc.per_phase[phase]["decomp"]
    comm_opt = d["d2d_serial_s"] + d["propagation_s"]
    comm_pess = comm_opt + (sc.t_pess_s - sc.t_opt_s)
    compute = d["layers_s"]
    return comm_opt, comm_pess, compute


def classify(comm_opt, comm_pess, compute):
    if comm_pess < compute:
        return "certified compute-dominant"
    if comm_opt > compute:
        return "certified communication-bound"
    return "uncertain"


def main():
    W = se.Workload2p7B()
    pi = ss.pi_from_a4_payload()
    out = {"note": "A1 region semantics; rails = score()'s optimistic and "
                   "pessimistic ends; production weaves are packet-free so "
                   "the rails coincide (Delta == 1.00 by construction)",
           "quantifier": "certified",
           "evaluation_set": "closed-form per cell; no search",
           "tiers_row_time_us": dict(TIERS), "bandwidths_gbps": BWS,
           "cells": {}}
    for phase in ("prefill", "decode"):
        print(f"[{phase}] comm (hand-offs + propagation) vs compute, "
              f"per cell; * marks an uncertain band")
        print(f"{'tier':8} " + " ".join(f"{b:>10g}" for b in BWS))
        for tier, t_us in TIERS:
            scale = 10.14 / t_us
            row = []
            for bw in BWS:
                co, cp, comp = rails(W, pi, phase, bw, scale)
                verdict = classify(co, cp, comp)
                out["cells"][f"{phase}/{tier}/{bw}"] = {
                    "comm_opt_s": co, "comm_pess_s": cp, "compute_s": comp,
                    "comm_over_compute": co / comp, "verdict": verdict,
                    "rail_gap_s": cp - co}
                row.append(("C" if verdict.endswith("compute-dominant")
                            else "N" if verdict.endswith("bound") else "*")
                           + f"{co/comp:8.3f}")
            print(f"{tier:8} " + " ".join(f"{x:>10}" for x in row))
    n_unc = sum(1 for v in out["cells"].values()
                if v["verdict"] == "uncertain")
    max_gap = max(v["rail_gap_s"] for v in out["cells"].values())
    print(f"\nuncertain cells: {n_unc} of {len(out['cells'])}; widest rail "
          f"gap {max_gap:.3e} s -- the declared zero-width band on "
          f"packet-free production weaves")
    out["summary"] = {"n_cells": len(out["cells"]), "n_uncertain": n_unc,
                      "max_rail_gap_s": max_gap}

    # the packet-declared demonstration: the same payload on a weave that
    # DOES declare packets opens a real middle band
    import dataclasses as dc
    lk = W.fab.level("die").link
    levels = [dc.replace(l, link=dc.replace(l.link, packet_payload_bytes=32.0))
              if l.name == "die" else l for l in W.fab.levels]
    Wp = se.Workload2p7B()
    Wp.fab = dc.replace(W.fab, name="packet-demo", levels=levels).validate()
    Wp.die_ic = W.die_ic
    demo = {}
    print("\npacket-declared weave (32 B payload), prefill: the middle band")
    for bw in BWS:
        co, cp, comp = rails(Wp, pi, "prefill", bw, 1.0)
        v = classify(co, cp, comp)
        demo[bw] = {"comm_opt_s": co, "comm_pess_s": cp, "compute_s": comp,
                    "verdict": v}
        print(f"  {bw:>5g} GB/s: comm {co*1e3:9.2f} .. {cp*1e3:9.2f} ms vs "
              f"compute {comp*1e3:9.2f} ms -> {v}")
    out["packet_demo_prefill"] = demo
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
