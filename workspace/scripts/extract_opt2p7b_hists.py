"""Extract REAL operand value histograms from facebook/opt-2.7b -- the model
whose shapes (d=2560, ffn=10240, 32 layers, 32 heads) our 2.7B-class runs
use. Replaces the borrowed gpt2_medium distributions.

Torch-only process (never share an interpreter with timeloop). One forward
pass on a sample text with hooks on every decoder layer captures, per layer:
  Linear entries : q_proj, out_proj, fc1, fc2  (Inputs/Weights/Outputs)
  OPTAttention x2: QK^T   (Inputs=Q, Weights=K, Outputs=scores)
                   AV     (Inputs=softmax probs, Weights=V, Outputs=attn out)
Same 31-bin symmetric zero-centred format as models/workloads/gpt2_medium.

Usage (container): python3 scripts/extract_opt2p7b_hists.py
"""
import os
import sys

os.environ.setdefault("HF_HOME", "/home/workspace/.cache/hf")
sys.path.insert(0, "/home/workspace")

OUT = "/home/workspace/models/workloads/opt_2p7b"
NBINS = 31
TEXT = ("The transformer architecture has become the dominant approach for "
        "natural language processing, powering large language models that "
        "generate text, translate languages, and answer questions. Its "
        "attention mechanism lets every token attend to every other token, "
        "and its feed-forward layers store most of the parameters.")

HEADER = """{{{{include_text('../problem_base.yaml')}}}}
problem:
  <<<: *problem_base
  instance: {{{inst}}}

  name: {name}
  dnn_name: opt_2p7b
  notes: {notes}
  histograms:
    Inputs:  {i}
    Weights: {w}
    Outputs: {o}
"""


def hist(t):
    import numpy as np
    x = t.detach().float().numpy().reshape(-1)
    A = float(np.max(np.abs(x))) or 1.0
    h, _ = np.histogram(np.clip(x, -A, A), bins=np.linspace(-A, A, NBINS + 1))
    h = h.astype(float); s = h.sum()
    h = h / s if s else h + 1.0 / NBINS
    return "[" + ",".join(f"{v:.4g}" for v in h) + "]"


def main():
    import torch
    from transformers import AutoTokenizer, OPTModel
    print("loading facebook/opt-2.7b (fp32, CPU) ...", flush=True)
    tok = AutoTokenizer.from_pretrained("facebook/opt-2.7b")
    m = OPTModel.from_pretrained("facebook/opt-2.7b").eval()
    ids = tok(TEXT, return_tensors="pt")
    grabbed = {}

    def grab_io(tag):
        def fn(mod, inp, out):
            grabbed[tag] = (inp[0], out)
        return fn

    hooks = []
    for li, layer in enumerate(m.decoder.layers):
        at = layer.self_attn
        for nm, mod in (("q", at.q_proj), ("k", at.k_proj), ("v", at.v_proj),
                        ("out", at.out_proj), ("fc1", layer.fc1),
                        ("fc2", layer.fc2)):
            hooks.append(mod.register_forward_hook(grab_io(f"{li}.{nm}")))
    with torch.no_grad():
        m(**ids)
    for h in hooks:
        h.remove()
    print(f"forward done ({ids['input_ids'].shape[1]} tokens); writing YAMLs",
          flush=True)

    os.makedirs(OUT, exist_ok=True)
    d, ff, nh = 2560, 10240, 32
    dh = d // nh
    k = 0
    for li, layer in enumerate(m.decoder.layers):
        at = layer.self_attn
        lin = [("q", at.q_proj, f"C: {d}, M: {d}, P: 64"),
               ("out", at.out_proj, f"C: {d}, M: {d}, P: 64"),
               ("fc1", layer.fc1, f"C: {d}, M: {ff}, P: 64"),
               ("fc2", layer.fc2, f"C: {ff}, M: {d}, P: 64")]
        for nm, mod, inst in lin:
            x, y = grabbed[f"{li}.{nm}"]
            body = HEADER.format(inst=inst, name="Linear",
                                 notes=f"opt-2.7b layer {li} {nm}",
                                 i=hist(x), w=hist(mod.weight), o=hist(y))
            open(os.path.join(OUT, f"{k:03d}.yaml"), "w").write(body)
            k += 1
        # attention einsums from the captured projections
        q = grabbed[f"{li}.q"][1].view(1, -1, nh, dh).transpose(1, 2)
        kk = grabbed[f"{li}.k"][1].view(1, -1, nh, dh).transpose(1, 2)
        v = grabbed[f"{li}.v"][1].view(1, -1, nh, dh).transpose(1, 2)
        scores = (q @ kk.transpose(-1, -2)) / (dh ** 0.5)
        probs = torch.softmax(scores, dim=-1)
        attn = probs @ v
        for nm, i_, w_, o_ in (("qk^t", q, kk, scores),
                               ("av", probs, v, attn)):
            body = HEADER.format(inst=f"C: {dh}, M: 64, P: 64",
                                 name="OPTAttention",
                                 notes=f"opt-2.7b layer {li} {nm} einsum",
                                 i=hist(i_), w=hist(w_), o=hist(o_))
            open(os.path.join(OUT, f"{k:03d}.yaml"), "w").write(body)
            k += 1
        if li % 8 == 0:
            print(f"  layer {li} done", flush=True)
    print(f"wrote {k} YAMLs -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
