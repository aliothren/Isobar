"""The operators outside the transformer blocks: the LM head (one matmul
d_model x vocab for the last token, measured with the CiMLoop mapper; the
vocabulary is padded to the next power of two for the residency tiler) and
the embedding read (closed form), per evaluated model. The full-request
energy comparison (gpu_comparison/) adds them to the per-layer records.
Runs in the container (the mapper).

    python3 scripts/measure_model_end.py [model ...]     (default: opt6.7b gemma7b opt13b)
      -> results/accounts/model_end_costs.json   (entries of other models already in the file are kept)
"""
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
os.environ.setdefault("CIMSIM_FABRIC", os.path.join(WS, "models", "fabric", "mlx300_multidie.yaml"))
from scripts import llm_workload as lw      # noqa: E402
from scripts import model_configs as vm         # noqa: E402
from scripts import paths                       # noqa: E402

OUT = paths.MODEL_END_COSTS


def main():
    names = sys.argv[1:] or ["opt6.7b", "gemma7b", "opt13b"]
    unknown = [n for n in names if n not in vm.MODELS]
    if unknown:
        raise SystemExit(f"unknown model(s) {unknown}; known: {sorted(vm.MODELS)}")
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for name in names:
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
    paths.ensure(os.path.dirname(OUT))
    json.dump(out, open(OUT, "w"), indent=1)
    print("->", OUT)


if __name__ == "__main__":
    main()
