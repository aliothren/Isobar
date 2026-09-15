"""D.3 item 1 (the 2.7B hand-off accounting review): the A4 whole-machine
column re-issued under the busiest-link hand-off term -- prefill and
decode, four bandwidth anchors x four device tiers (the phase-diagram
table's tiers: NeuRRAM 10.14 us, Mythic 6.38, ISAAC 1.6, HERMES 0.133;
device_scale = 10.14 / row time, compute-only per O17). For every cell:
new latency, the old (one-stream-per-hand-off) latency recovered
exactly through the pinned relation old = new + sum(total - busiest) /
rate, the delta, and the two shares the D.2 ruling keeps apart --
the D2D TOTAL hand-off share (all hand-offs, intra + inter, / whole
latency) and the inter-layer CUT-FEE share (the 31 layer-boundary
hand-offs alone / whole latency).

    python3 scripts/rerun_a4_column.py -> analysis/a4_column_v2.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import search_eval as se
from scripts import search_space as ss

TIERS = (("NeuRRAM", 10.14), ("Mythic", 6.38), ("ISAAC", 1.6),
         ("HERMES", 0.133))
BWS = (12.5, 2.0, 0.4, 0.1)
OUT = os.path.join(se.A, "a4_column_v2.json")


def main():
    W = se.Workload2p7B()
    pi = ss.pi_from_a4_payload()
    out = {"tiers_row_time_us": dict(TIERS), "bandwidths_gbps": BWS,
           "cells": {}}
    for phase in ("prefill", "decode"):
        bs = W.boundaries(pi, phase)
        tot = sum(b["words"] for b in bs)
        busy = sum(b["busiest_words"] for b in bs)
        inter_busy = sum(b["busiest_words"] for b in bs if b["inter_layer"])
        print(f"[{phase}] boundaries {len(bs)} | total words {tot/1e6:.1f}M | "
              f"busiest sum {busy/1e6:.1f}M (ratio {busy/tot:.4f}) | "
              f"inter-layer busiest {inter_busy/1e6:.1f}M")
        print(f"{'tier':8} {'bw':>5} {'new ms':>10} {'old ms':>10} "
              f"{'delta':>8} {'D2D share':>10} {'cut-fee sh':>11}")
        for tier, t_us in TIERS:
            scale = 10.14 / t_us
            for bw in BWS:
                sc = se.score(pi, W, mu={phase: 1.0}, caliber="single",
                              d2d_gbps=bw, device_scale=scale)
                wps = bw * 1e9
                new = sc.t_opt_s
                old = new + (tot - busy) / wps
                d2d_share = (busy / wps) / new
                fee_share = (inter_busy / wps) / new
                key = f"{phase}/{tier}/{bw}"
                out["cells"][key] = {
                    "new_s": new, "old_s": old, "delta_rel": (old - new) / old,
                    "d2d_total_share_new": d2d_share,
                    "cut_fee_share_new": fee_share}
                print(f"{tier:8} {bw:5} {new*1e3:10.2f} {old*1e3:10.2f} "
                      f"{(old-new)/old:8.2%} {d2d_share:10.2%} {fee_share:11.2%}")
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
