"""Attention per-row compute calibration for the derived accounts (V3,
2026-10-08): one mapper run per attention operator (qk^t, av) at a grid of
sequence lengths and head dimensions, prefill and decode, on the
reference 2.7B-class configuration otherwise (resident, one die). Writes
analysis/v3/attention_calibration.json keyed "phase/op/S<S>/dh<dh>" with
the measured compute seconds per row and the energy per MAC, which
scripts/v3_sweep.py reads when it derives an account.

    python3 scripts/v3_attention_calib.py [S list] [dh list]
"""
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
os.environ.setdefault("CIMSIM_FABRIC", os.path.join(WS, "models", "fabric", "mlx300_multidie.yaml"))
from scripts import llm_workload as lw   # noqa: E402

OUT = os.path.join(WS, "analysis", "v3", "attention_calibration.json")
S_LIST = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1 else "128,256,512,1024,1536".split(","))]
DH_LIST = [int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else "64,80,128".split(","))]


def main():
    table = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for dh in DH_LIST:
        d = 2560 if 2560 % dh == 0 else (dh * (2560 // dh))
        cfg = lw.GptConfig(d_model=d, n_heads=d // dh, d_ff=4 * d, n_layers=32, name=f"calib_d{d}_dh{dh}")
        for S in S_LIST:
            for phase in ("prefill", "decode"):
                for op in lw.block_ops(cfg, S, phase):
                    if op.kind != "dynamic":
                        continue
                    key = f"{phase}/{op.name}/S{S}/dh{dh}"
                    if key in table:
                        continue
                    if lw.op_weight_cells(op) > lw.DIE_WEIGHT_CELLS:
                        table[key] = {"status": "infeasible (exceeds one die)"}
                        continue
                    print(f"[{key}] P={op.P} C={op.C} M={op.M} N={op.N}", flush=True)
                    r = lw.run_op(op, phase=phase, overcapacity="reject", save_comm=False, hist_source="opt_2p7b",
                                  strict_traffic=False)
                    macs = op.P * op.C * op.M * op.N
                    table[key] = {"status": "measured", "d": d, "n_heads": cfg.n_heads,
                                  "compute_s": r["compute_latency_s"], "s_per_row": r["compute_latency_s"] / op.P,
                                  "write_s": r["write_latency_s"], "energy_J": r["total_J"],
                                  "pj_per_mac": (r["total_J"] - op.write_cells * lw.E_WRITE_PER_CELL_J) / macs * 1e12,
                                  "cycle_s": r["result"].cycle_seconds,
                                  "traffic_guard_error": r["traffic_guard_error"]}
                    print(f"    compute {r['compute_latency_s']*1e3:.4f} ms = {table[key]['s_per_row']*1e6:.3f} us/row | "
                          f"E {r['total_J']*1e3:.4f} mJ", flush=True)
                    json.dump(table, open(OUT, "w"), indent=1)
    json.dump(table, open(OUT, "w"), indent=1)
    print("->", OUT)


if __name__ == "__main__":
    main()
