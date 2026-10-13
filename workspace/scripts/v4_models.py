"""Next-round item 2: the three real models (and the reference) as workload
configurations, with their sources, and a snapshot of what the platform
maps from them.

Scope of every account in this campaign: the transformer block (the five
matmul die-sets qkv_proj / attention / out_proj / ffn1 / ffn2 and the
block's elementwise operators), repeated n_layers times. Embedding, the LM
head, the final norm and the positional encoding are outside the mapped
scope and are reported here by size only (the LM head is a matmul the
platform can price with lm_head_op; it is evaluated once per sequence and
is not part of the per-layer hand-off chain).

    python3 scripts/v4_models.py            -> analysis/v4/models/<name>.json and models.md
"""
import datetime
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import llm_workload as lw      # noqa: E402

OUT = os.path.join(WS, "analysis", "v4", "models")
RETRIEVED = "2026-10-12"

MODELS = {
    "opt6.7b": dict(
        cfg=dict(d_model=4096, n_heads=32, d_ff=16384, n_layers=32, name="opt-6.7b", vocab=50272, activation="relu"),
        max_positions=2048, positions="learned absolute (max_position_embeddings 2048)", norm="LayerNorm, pre-norm (do_layer_norm_before)",
        sources=[{"url": "https://huggingface.co/facebook/opt-6.7b/blob/main/config.json", "retrieved": RETRIEVED,
                  "values": "hidden_size 4096, ffn_dim 16384, num_attention_heads 32, num_hidden_layers 32, max_position_embeddings 2048, activation_function relu, vocab_size 50272, word_embed_proj_dim 4096, do_layer_norm_before true, torch_dtype float16, transformers_version 4.21.0.dev0"}],
        notes="MHA (head_dim 128 = 4096 / 32); FFN two plain projections with ReLU; biases in every projection (not mapped: a bias is an add on the digital unit, folded into the residual pass)."),
    "opt13b": dict(
        cfg=dict(d_model=5120, n_heads=40, d_ff=20480, n_layers=40, name="opt-13b", vocab=50272, activation="relu"),
        max_positions=2048, positions="learned absolute (max_position_embeddings 2048)", norm="LayerNorm, pre-norm (do_layer_norm_before)",
        sources=[{"url": "https://huggingface.co/facebook/opt-13b/blob/main/config.json", "retrieved": RETRIEVED,
                  "values": "hidden_size 5120, ffn_dim 20480, num_attention_heads 40, num_hidden_layers 40, max_position_embeddings 2048, activation_function relu, vocab_size 50272, word_embed_proj_dim 5120, do_layer_norm_before true, torch_dtype float16"}],
        notes="MHA (head_dim 128 = 5120 / 40); as opt6.7b otherwise."),
    "gemma7b": dict(
        cfg=dict(d_model=3072, n_heads=16, d_ff=24576, n_layers=28, name="gemma-7b", vocab=256000, head_dim=256, n_kv_heads=16, ffn_gated=True, activation="geglu"),
        max_positions=8192, positions="RoPE (trained context 8192)", norm="RMSNorm on the input of each sub-layer",
        sources=[{"url": "https://arxiv.org/html/2403.08295v4", "retrieved": RETRIEVED,
                  "values": "Table 1 (7B): d_model 3072, layers 28, feedforward hidden dims 49152, num heads 16, num KV heads 16, head size 256, vocab size 256128; Table 2: embedding parameters 786,825,216, non-embedding 7,751,248,896; GeGLU (approximated), RMSNorm, RoPE, context 8192"},
                 {"url": "https://ai.google.dev/gemma/docs/core/distributed_tuning?hl=en", "retrieved": RETRIEVED,
                  "values": "weight shapes of the released checkpoint: gate_proj and up_proj 3072 x 24576 each, down_proj 24576 x 3072; q_proj 3072 x 4096, k_proj / v_proj 3072 x 4096, o_proj 4096 x 3072; embedding 256000 x 3072"}],
        notes="The paper's 'feedforward hidden dims 49152' is the two branches together (gate 24576 + up 24576); d_ff here is one branch (24576) and the mapped ffn1 has 2 x 24576 columns, ffn2 24576 rows. Attention width 16 x 256 = 4096 differs from d_model 3072: qkv_proj is 3072 x 12288, out_proj 4096 x 3072. 16 query heads and 16 K/V heads (MHA). Vocab 256000 in the released checkpoint vs 256128 in the paper's table; the embedding is tied to the LM head. Column order declared for the mapped ffn1: gate_j and up_j interleaved so that each die holds matching pairs and forms gelu(gate) x up locally before the hand-off (a declaration of column order on a weight-stationary array, no cost)."),
    "ref2p7b": dict(
        cfg=dict(d_model=2560, n_heads=32, d_ff=10240, n_layers=32, name="gpt-2.7B-class", vocab=50257),
        max_positions=None, positions="(class model, as in the V3 records)", norm="LayerNorm",
        sources=[{"url": "(repository) analysis/scale_2p7b_per_op.json", "retrieved": "frozen 2026-09", "values": "d 2560, 32 heads (dh 80), d_ff 10240, 32 layers"}],
        notes="The frozen reference of the draft; listed for the common columns."),
}


def cfg_of(name):
    return lw.GptConfig(**MODELS[name]["cfg"])


def block_params(cfg):
    """Mapped parameters per layer (the matmul weights of the block) and the model-end sizes."""
    ops = {o.name: o for o in lw.block_ops(cfg, 1, "prefill")}
    per_layer = sum(ops[n].C * ops[n].M for n in ("qkv_proj", "out_proj", "ffn1", "ffn2"))
    return {"per_layer_matmul_params": per_layer, "block_params_all_layers": per_layer * cfg.n_layers,
            "embedding_params": cfg.vocab * cfg.d_model, "lm_head_params": cfg.vocab * cfg.d_model,
            "lm_head_tied_to_embedding": cfg.name.startswith("gemma") or cfg.name.startswith("opt")}


def snapshot(name):
    m = MODELS[name]
    cfg = cfg_of(name)
    out = {"name": name, "config": {**m["cfg"], "head_dim_effective": cfg.dh, "kv_heads_effective": cfg.kv_heads, "attn_width": cfg.attn_width},
           "max_positions": m["max_positions"], "positions": m["positions"], "norm": m["norm"], "sources": m["sources"], "notes": m["notes"],
           "scope": "transformer block x n_layers (qkv_proj, attention die with qk^t / softmax / av, out_proj, ffn1, ffn2, block elementwise); embedding, LM head, final norm and positions outside the mapped scope",
           "params": block_params(cfg), "phases": {}, "attention_die_capacity": {}}
    for phase in ("prefill", "decode"):
        out["phases"][phase] = {}
        for S in (128, 256, 512, 1024, 2048, 4096):
            ops = [{"name": o.name, "kind": o.kind, "P": o.P, "C": o.C, "M": o.M, "N": o.N, "out_M": o.out_M, "resident_N": o.resident_N,
                    "resident_cells": lw.op_weight_cells(o), "write_cells": o.write_cells, "write_rows": o.write_rows} for o in lw.block_ops(cfg, S, phase)]
            att = sum(o["resident_cells"] for o in ops if o["kind"] == "dynamic")
            feas = att <= lw.DIE_WEIGHT_CELLS
            rec = {"ops": ops, "attention_cells": att, "attention_fits_one_die": feas,
                   "model_length_limit": (m["max_positions"] is not None and S > m["max_positions"]),
                   "elementwise": [e.name for e in lw.block_elementwise_ops(cfg, S, phase)]}
            if feas:
                try:
                    chain = lw.block_chain(cfg, S, phase, on_chip=True, max_dies=10 ** 6, dims=("M", "C"))
                    rec["chain"] = [{"name": e["name"], "n_dies": e["n_dies"], "split": e["split"], "in_words": e["in_words"], "out_words": e["out_words"]} for e in chain]
                    rec["dies_per_layer"] = sum(e["n_dies"] for e in chain)
                    rec["dies_total"] = rec["dies_per_layer"] * cfg.n_layers
                except ValueError as e:
                    rec["chain_error"] = str(e)
            out["phases"][phase][str(S)] = rec
            out["attention_die_capacity"][f"{phase}/{S}"] = {"cells": att, "die_cells": lw.DIE_WEIGHT_CELLS, "fits": feas}
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    md = ["# Real models in this campaign (snapshots in this directory; sources with retrieval date inside each JSON)\n",
          "| model | d_model | heads (q / kv) x head_dim | attn width | d_ff (mapped ffn1 columns) | layers | activation | positions | vocab | mapped block params | embedding params | dies per layer (prefill 512, colrow) | dies total | attention die fits at S |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in MODELS:
        s = snapshot(name)
        json.dump(s, open(os.path.join(OUT, f"{name}.json"), "w"), indent=1)
        c, p = s["config"], s["params"]
        pf = s["phases"]["prefill"]["512"]
        fits = [S for S in (128, 256, 512, 1024, 2048, 4096) if s["attention_die_capacity"][f"prefill/{S}"]["fits"]]
        chain_txt = "; ".join(f"{e['name']} {e['n_dies']}" for e in pf.get("chain", []))
        md.append(f"| {name} | {c['d_model']} | {c['n_heads']} / {c['kv_heads_effective']} x {c['head_dim_effective']} | {c['attn_width']} | {c['d_ff']} ({[o for o in pf['ops'] if o['name']=='ffn1'][0]['M']}) | {c['n_layers']} | {c.get('activation', 'gelu')} | {s['max_positions'] or '-'} | {c['vocab']} | "
                  f"{p['block_params_all_layers']/1e9:.2f} B | {p['embedding_params']/1e6:.0f} M | {pf.get('dies_per_layer', '-')} ({chain_txt}) | {pf.get('dies_total', '-')} | {', '.join(map(str, fits))} |")
        print(name, "dies/layer", pf.get("dies_per_layer"), "total", pf.get("dies_total"), "fits", fits)
    md.append("\nLength limits: OPT's learned positions stop at 2048 (S above that is 'not supported by the model', listed apart); the attention die's K/V capacity (one die per layer holds K and V of all heads at the resident cell count) is the mapping limit; where it fails the length is listed as 'capacity (one attention die)' and a split-attention structure would be a separate configuration.")
    open(os.path.join(OUT, "models.md"), "w").write("\n".join(md) + "\n")
    print("->", OUT)


if __name__ == "__main__":
    main()
