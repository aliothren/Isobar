# Sources of the GPU baselines

`gpu_baselines.csv` lists every GPU value used in Table III, each tagged as `figure reading`, `reported in text`, `derived` or `recomputed`. `hydra_input_lengths.csv` is the input-length frequency table of the Gemma-7B requests. Both files are written by `../scripts/gpu_baselines.py`.

## OPT-13B on one A100 (CXL-PNM, HPCA 2024)

*An LPDDR-based CXL-PNM Platform for TCO-efficient Inference of Transformer-based Large Language Models*, HPCA 2024, pp. 970–982, DOI 10.1109/HPCA57654.2024.00078.

- Setup (section VII): one A100 40 GB (1.55 TB/s), FasterTransformer, OPT-13B on a single device, 64 input and up to 1024 output tokens.
- Output throughput: 47.33 tokens/s (Fig. 10, GPU bar at [64:1024]).
- GPU power: 253 W (section VIII-A).
- Derived: request time T = 1024 / 47.33 = 21.635 s, request energy E = 253 W × T = 5473.7 J (5.345 J per output token; 0.19 token/J in Fig. 10(b)). The throughput covers prefill and generation; the denominator is the 1024 output tokens.
- The GPU data type and beam width are not reported for this point.

## Gemma-7B on a Jetson AGX Thor (Hydra)

*Hydra: Phase-Aware Workload Characterization of LLM Inference across Edge SoC Generations, Backends, and Quantization Levels*, arXiv:2608.25053. Data: github.com/amirtaherin/hydra at commit `1879bf8aff86ff8ed5388b245a351ff20a785f38`, archive `data/unified/hydra_unified.tar.xz.part00/01` (checked against the repository's SHA256SUMS). File used: `hydra-results/thor/results_llamacpp_thor/UNIFIED_gemma-7B_Q8_0_.csv` (sha256 `c9139dd8d288b929403f2a667484d58b6048495384cb80d4a8743a96df2df822`, 541 rows). The raw file is not redistributed here. To recompute:

```bash
git clone https://github.com/amirtaherin/hydra && cd hydra && git checkout 1879bf8aff86ff8ed5388b245a351ff20a785f38
mkdir -p /tmp/hydra_unified && cat data/unified/hydra_unified.tar.xz.part0* | tar -xJ -C /tmp/hydra_unified
# from workspace/ of this repository:
python3 gpu_comparison/scripts/gpu_baselines.py \
    --hydra-csv "$(find /tmp/hydra_unified -path '*hydra-results/thor/results_llamacpp_thor/UNIFIED_gemma-7B_Q8_0_.csv')"
```

Recomputed from the raw fields:

- 541 IFEval requests, batch 1, llama.cpp with full GPU offload, Q8_0 weights, greedy decoding.
- Input lengths 13–345 tokens (mean 47.329, 84 distinct values); every request generates 500 output tokens.
- Mean request time (`end_to_end_latency`): 24.826 s.
- Mean board energy, per request `vin_cur_prompt_mean / 1000 × end_to_end_latency`, then averaged: 1898.7 J (3.797 J per output token). The board input (VIN) covers the whole module: GPU, CPU, memory and I/O, including static power.
- The GPU-rail energy (`vdd_gpu_cur_prompt_mean`, 794.7 J) is a component of the board energy and is kept as a diagnostic only.
