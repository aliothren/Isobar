"""The model-end operators outside the mapped scope (transformer backbone):
the LM head (one matmul d_model x vocab, evaluated for the last token, by
the mapper) and the embedding read (closed-form), per real model, so the
full generation latency can be assembled from the per-layer records.
Container only.

    python3 scripts/v4_model_end.py   -> analysis/v4/models/model_end_costs.json
"""
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
os.environ.setdefault("CIMSIM_FABRIC", os.path.join(WS, "models", "fabric", "mlx300_multidie.yaml"))
from scripts import llm_workload as lw      # noqa: E402
from scripts import v4_models as vm         # noqa: E402

OUT = os.path.join(WS, "analysis", "v4", "models", "model_end_costs.json")


def main():
    out = {}
    for name in ("opt6.7b", "gemma7b", "opt13b"):
        cfg = vm.cfg_of(name)
        rec = {"vocab": cfg.vocab, "lm_head_padded_M": 1 << (cfg.vocab - 1).bit_length(), "phases": {}}
        for phase in ("prefill", "decode"):
            op = lw.lm_head_op(cfg, 512, phase)
            print(f"[{name} {phase}] lm_head P={op.P} C={op.C} M={op.M}", flush=True)
            r = lw.run_op(op, phase=phase, overcapacity="spatial_multi_die", save_comm=False, hist_source="opt_2p7b", strict_traffic=False, spatial_max_dies=10 ** 6)
            emb = lw.embedding_cost(cfg, 512, phase)
            rec["phases"][phase] = {"lm_head": {"dies": r["dies_for_op"], "compute_s": r["compute_latency_s"], "write_s": r["write_latency_s"], "energy_J": r["total_J"],
                                                "note": "one matmul for the last token (P = 1) per sequence; vocab padded to the next power of two for the residency tiler"},
                                    "embedding": emb}
            print(f"    lm_head dies {r['dies_for_op']} compute {r['compute_latency_s']*1e3:.4f} ms E {r['total_J']*1e3:.4f} mJ | embedding {emb['words']} words {emb['energy_J']*1e3:.4f} mJ timed {emb['timed']}", flush=True)
        out[name] = rec
    json.dump(out, open(OUT, "w"), indent=1)
    print("->", OUT)


if __name__ == "__main__":
    main()
