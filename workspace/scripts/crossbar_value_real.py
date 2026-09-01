"""
REAL per-crossbar value-dependent energy (Plan A), split into TWO processes so the
torch/transformers stack and the cimloop/timeloop stack never share an interpreter
(they segfault together -- an OpenMP clash):

  extract  : (torch only) load a real weight tensor, tile it into 256x256 blocks,
             histogram each block + the whole layer, save to JSON.
  simulate : (cimloop only) for each tile histogram, run CiMLoop's single-crossbar
             energy (system=ws_dummy_buffer_one_macro) with that weight distribution;
             sum the tiles. One macro run == one 256x256 crossbar; a layer weight
             [C x M] tiles into (C/256)x(M/256) blocks, so the tile-sum is the whole
             layer, but distribution-accurate per crossbar. The sum DIFFERS from the
             layer-uniform run (energy is nonlinear in the distribution) -- that gap
             is the genuine crossbar-aware information, not a redistribution.

Usage (two separate docker exec calls):
  python3 scripts/crossbar_value_real.py extract  <hists.json>
  python3 scripts/crossbar_value_real.py simulate <hists.json>
"""
import os, sys, json

os.environ.setdefault("HF_HOME", "/home/workspace/.cache/hf")
ARR = 256
NBINS = 31


def symmetric_hist(w, A, nbins=NBINS):
    """31-bin symmetric zero-centered normalized histogram (numpy only)."""
    import numpy as np
    edges = np.linspace(-A, A, nbins + 1)
    h, _ = np.histogram(np.clip(w, -A, A), bins=edges)
    h = h.astype(float)
    s = h.sum()
    return (h / s).tolist() if s else (np.ones(nbins) / nbins).tolist()


def extract(out_json):
    import numpy as np
    from transformers import GPT2Model
    import torch
    from transformers import GPT2Tokenizer
    print("loading gpt2-medium ...", flush=True)
    tok = GPT2Tokenizer.from_pretrained("gpt2-medium")
    m = GPT2Model.from_pretrained("gpt2-medium").eval()
    W = m.h[0].mlp.c_fc.weight.detach().numpy()      # Conv1D c_fc: [C=1024, M=4096]

    # capture the REAL ffn1 INPUT activations on a sample text (the value-dependent
    # energy is driven by inputs, not weights -- see the sensitivity probe).
    text = ("The transformer architecture has become the dominant approach for "
            "natural language processing, powering large language models that "
            "generate text, translate languages, and answer questions.")
    grab = {}
    h = m.h[0].mlp.c_fc.register_forward_hook(
        lambda mod, inp, out: grab.__setitem__("x", inp[0].detach().numpy()))
    with torch.no_grad():
        m(**tok(text, return_tensors="pt"))
    h.remove()
    X = grab["x"].reshape(-1, W.shape[0])            # [tokens, C=1024]

    C, M = W.shape
    Aw = float(np.max(np.abs(W))) or 1.0
    Ax = float(np.max(np.abs(X))) or 1.0
    nr, nc = C // ARR, M // ARR
    # weight tile per crossbar (r,c); input slice per contraction block r (256 chans)
    wtiles = [symmetric_hist(W[r*ARR:(r+1)*ARR, c*ARR:(c+1)*ARR].reshape(-1), Aw)
              for r in range(nr) for c in range(nc)]
    iblocks = [symmetric_hist(X[:, r*ARR:(r+1)*ARR].reshape(-1), Ax) for r in range(nr)]
    json.dump({"tag": "ffn1_gpt2medium", "shape": [C, M], "nr": nr, "nc": nc,
               "layer_whist": symmetric_hist(W.reshape(-1), Aw),
               "layer_ihist": symmetric_hist(X.reshape(-1), Ax),
               "wtiles": wtiles, "iblocks": iblocks}, open(out_json, "w"))
    print(f"saved {out_json}: W {C}x{M} -> {nr}x{nc}={len(wtiles)} tiles, "
          f"{nr} input blocks from {X.shape[0]} tokens", flush=True)


def extract_cnn(out_json):
    """A CNN conv layer: no LayerNorm, trained (non-Gaussian) filters, and ReLU'd
    inputs whose channels differ a lot in sparsity -> a stronger test for per-crossbar
    value-dependent variation than a layernormed transformer."""
    import numpy as np, torch
    import torch.nn.functional as F
    import torchvision.models as M
    print("loading resnet18 ...", flush=True)
    net = M.resnet18(weights=M.ResNet18_Weights.DEFAULT).eval()
    conv = net.layer4[1].conv1                        # in=512, out=512, 3x3 (deep, post-ReLU)
    grab = {}
    hd = conv.register_forward_hook(
        lambda mod, inp, out: grab.__setitem__("x", inp[0].detach()))
    with torch.no_grad():
        torch.manual_seed(0)                          # hygiene 23 (C40): the sampling
        # draw is seeded, so the CNN value histograms are reproducible (the
        # 1.199-vs-1.204 rerun drift disappears from the next value-stage
        # regeneration onward; the published 1.204x stays until then).
        # Review answer (C40-r): this randn is the ONLY stochastic source on
        # the path -- numpy here does deterministic histogramming/reshapes
        # and the GPT-2 branch uses a fixed sample text; nothing else to seed.
        net(torch.randn(8, 3, 224, 224))              # 8 sampled images -> deep activations
    hd.remove()
    X = grab["x"]                                     # [8, 512, 7, 7], ReLU'd, sparse
    kh, kw = conv.kernel_size
    unf = F.unfold(X, (kh, kw), padding=conv.padding, stride=conv.stride)  # [8, 512*9, L]
    Xc = unf.permute(1, 0, 2).reshape(unf.shape[1], -1).numpy()            # [C=4608, 8L]
    Wt = conv.weight.detach()                         # [out=512, in=512, 3,3]
    W = Wt.reshape(Wt.shape[0], -1).numpy().T         # [C=in*kh*kw=4608, M=out=512]

    C, Mo = W.shape
    Aw = float(np.max(np.abs(W))) or 1.0
    Ax = float(np.max(np.abs(Xc))) or 1.0
    nr, nc = C // ARR, Mo // ARR
    wtiles = [symmetric_hist(W[r*ARR:(r+1)*ARR, c*ARR:(c+1)*ARR].reshape(-1), Aw)
              for r in range(nr) for c in range(nc)]
    iblocks = [symmetric_hist(Xc[r*ARR:(r+1)*ARR, :].reshape(-1), Ax) for r in range(nr)]
    # report input-block sparsity spread (fraction of near-zero mass per block)
    zc = [ib[len(ib)//2] for ib in iblocks]
    json.dump({"tag": "resnet18_layer4.1.conv1", "shape": [C, Mo], "nr": nr, "nc": nc,
               "layer_whist": symmetric_hist(W.reshape(-1), Aw),
               "layer_ihist": symmetric_hist(Xc.reshape(-1), Ax),
               "wtiles": wtiles, "iblocks": iblocks}, open(out_json, "w"))
    print(f"saved {out_json}: W {C}x{Mo} -> {nr}x{nc}={len(wtiles)} tiles, "
          f"{nr} input blocks; per-block zero-mass min {min(zc):.2f} max {max(zc):.2f}",
          flush=True)


def simulate(in_json, macro="wan_nature_2022"):
    import numpy as np
    sys.path.insert(0, "/home/workspace")
    from scripts import utils as utl
    from scripts import value_stats as vs
    d = json.load(open(in_json))
    io = vs.representative_histograms("gpt2_medium", ("Conv1D", "Linear"))
    print(f"device macro = {macro}", flush=True)

    def macro_energy(weight_hist, input_hist):
        spec = utl.get_spec(macro=macro,
                            system="ws_dummy_buffer_one_macro", max_utilization=True)
        spec.problem["histograms"] = {"Inputs": input_hist, "Weights": weight_hist,
                                      "Outputs": io["Outputs"]}
        return utl.run_mapper(spec).energy

    nr, nc = d["nr"], d["nc"]
    n = nr * nc
    print(f"[{d['tag']}] {nr}x{nc}={n} crossbars; per crossbar (r,c): "
          f"weight tile[r,c] + input block[r]", flush=True)
    # uniform: layer weight + layer input, applied to every crossbar
    e_uni = macro_energy(d["layer_whist"], d["layer_ihist"]) * n
    # REAL: each crossbar uses its own weight tile AND its contraction block's input
    per = np.array([macro_energy(d["wtiles"][r*nc + c], d["iblocks"][r])
                    for r in range(nr) for c in range(nc)])
    e_real = per.sum()
    print(f"  uniform (layer hists x{n})  : {e_uni:.4e} J")
    print(f"  REAL   (per-crossbar in+wt) : {e_real:.4e} J  "
          f"({100*(e_real/e_uni-1):+.2f}% vs uniform)")
    print(f"  per-crossbar energy: min {per.min():.3e}  max {per.max():.3e}  "
          f"max/min {per.max()/per.min():.3f}x")
    out = in_json.replace(".json", f"_{macro}_energy.json")
    json.dump({"tag": d["tag"], "macro": macro, "nr": nr, "nc": nc,
               "uniform_total": e_uni, "real_total": e_real,
               "ratio": float(per.max() / per.min()),
               "per_crossbar": per.tolist()}, open(out, "w"))
    print(f"  saved per-crossbar energies -> {out}", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "extract"
    path = (sys.argv[2] if len(sys.argv) > 2
            else "/home/workspace/analysis/tile_hists_ffn1.json")
    if cmd == "simulate":
        simulate(path, sys.argv[3] if len(sys.argv) > 3 else "wan_nature_2022")
    else:
        {"extract": extract, "extract_cnn": extract_cnn}[cmd](path)
